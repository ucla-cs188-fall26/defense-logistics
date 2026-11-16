"""
graph_builder.py
----------------
V1 graph builder: one report file in, one graph dict out.

Three LLM extractors (Scout, Receiver, Auditor) each read the same report and
return sites, transfers, and stock counts. Their outputs are merged by simple
majority vote: a site, edge, or claim is kept only if at least 2 of the 3
extractors produced it. No disagreement weights, no L1, no tabular parsing.

Output shape (same as orb/supply_world.py so compile() can take it later):
  {
    "nodes":  [{"id": "DEPOT"}, ...],
    "edges":  [{"id": "e0", "from": "DEPOT", "to": "BASE_A"}, ...],
    "claims": [{"id": "c0", "type": "node", "ref": "DEPOT", "value": 740.0,
                "source": "SGT Price", "weight": 1.0}, ...],
    "dropped": [...]   # things only one extractor saw
  }

Usage:
  python graph_builder.py tests/fixtures/example_report.txt -o graph.json
  python server.py        # upload reports in the browser and watch the build
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, Optional

import anthropic
from dotenv import load_dotenv
from pydantic import BaseModel

MODEL = "claude-opus-5"
MAJORITY = 2  # out of 3 extractors


# ── what each extractor returns ──────────────────────────────────────────────

class Stock(BaseModel):
    site: str
    value: float
    reporter: str


class Transfer(BaseModel):
    from_site: str
    to_site: str
    value: float
    reporter: str


class Extraction(BaseModel):
    sites: list[str]
    stocks: list[Stock]
    transfers: list[Transfer]


# ── the three agents ─────────────────────────────────────────────────────────

SHARED_RULES = """
You are reading a raw logistics report and turning it into structured claims.

Rules:
- Site IDs are the uppercase codes written in the report (e.g. DEPOT, BASE_A, POST_1).
  Copy them exactly. Never invent or rename a site.
- Only include a site in `sites` if it reports a stock count or actually sends or
  receives a transfer in this report. A site that is merely mentioned (planned,
  cancelled, no movement) is NOT included.
- `stocks`: one entry each time someone states how much a site currently has on hand.
- `transfers`: one entry each time someone states an amount that moved from one site
  to another. If the sender and the receiver each report the same shipment, that is
  TWO transfer entries (one per reporter), even if the numbers differ.
- `value` is the number as stated. Do not add, net, or correct numbers.
- `reporter` is a short label for who said it (a name or role from the report).
"""

AGENTS = {
    "scout": "You are the Scout. Sweep the whole report and list every site and every "
             "movement between sites. Be complete.",
    "receiver": "You are the Receiver. Focus on what each site says it has on hand and "
                "what it signed for on arrival. Report numbers exactly as counted.",
    "auditor": "You are the Auditor. Be strict: only extract a stock or transfer when the "
               "report states an explicit number for it. Ignore plans and hearsay.",
}


def run_agent(client: anthropic.Anthropic, name: str, report: str) -> Extraction:
    response = client.messages.parse(
        model=MODEL,
        max_tokens=16000,
        system=AGENTS[name] + "\n" + SHARED_RULES,
        messages=[{"role": "user", "content": f"<report>\n{report}\n</report>"}],
        output_format=Extraction,
    )
    if response.stop_reason == "refusal":
        raise RuntimeError(f"{name}: model refused ({response.stop_details})")
    return response.parsed_output


# ── majority merge ───────────────────────────────────────────────────────────

def _norm(site: str) -> str:
    return site.strip().upper().replace(" ", "_")


def merge(extractions: dict[str, Extraction]) -> dict:
    """Keep anything that at least MAJORITY extractors agree on exactly."""
    site_votes: Counter = Counter()
    claim_votes: Counter = Counter()      # key -> number of agents that produced it
    claim_sources: dict = {}              # key -> first reporter label seen

    for ext in extractions.values():
        seen_claims = set()
        for s in set(_norm(x) for x in ext.sites):
            site_votes[s] += 1
        for st in ext.stocks:
            key = ("node", _norm(st.site), round(st.value, 2))
            seen_claims.add(key)
            claim_sources.setdefault(key, st.reporter)
        for tr in ext.transfers:
            key = ("edge", (_norm(tr.from_site), _norm(tr.to_site)), round(tr.value, 2))
            seen_claims.add(key)
            claim_sources.setdefault(key, tr.reporter)
        for key in seen_claims:           # one vote per agent per claim
            claim_votes[key] += 1

    nodes = sorted(s for s, n in site_votes.items() if n >= MAJORITY)
    kept = [k for k, n in claim_votes.items() if n >= MAJORITY]
    dropped = [k for k, n in claim_votes.items() if n < MAJORITY]
    dropped += [("site", s) for s, n in site_votes.items() if n < MAJORITY]

    # Edges come from the surviving transfer claims.
    edge_pairs = sorted({k[1] for k in kept if k[0] == "edge"})
    edge_id = {pair: f"e{i}" for i, pair in enumerate(edge_pairs)}
    edges = [{"id": edge_id[p], "from": p[0], "to": p[1]} for p in edge_pairs]

    claims = []
    for i, key in enumerate(sorted(kept, key=str)):
        kind, ref, value = key
        claims.append({
            "id": f"c{i}",
            "type": kind,
            "ref": ref if kind == "node" else edge_id[ref],
            "value": value,
            "source": claim_sources[key],
            "weight": 1.0,
        })

    return {
        "nodes": [{"id": n} for n in nodes],
        "edges": edges,
        "claims": claims,
        "dropped": [json.loads(json.dumps(d)) for d in dropped],
    }


# ── entry point ──────────────────────────────────────────────────────────────

def build_graph_from_text(report: str, on_event: Optional[Callable[[dict], None]] = None) -> dict:
    """
    Run the three agents on `report` and merge. `on_event` (optional) receives
    progress dicts as things happen, so a UI can watch the build:
      {"event": "agent_start", "agent": name}
      {"event": "agent_done",  "agent": name, "extraction": {...}, "seconds": s}
      {"event": "agent_error", "agent": name, "error": "..."}
      {"event": "merged", "graph": {...}}
    """
    emit = on_event or (lambda e: None)
    load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))
    client = anthropic.Anthropic()

    def timed(name):
        emit({"event": "agent_start", "agent": name})
        t0 = time.time()
        return name, run_agent(client, name, report), time.time() - t0

    extractions = {}
    with ThreadPoolExecutor(max_workers=len(AGENTS)) as pool:
        futures = [pool.submit(timed, name) for name in AGENTS]
        for fut in as_completed(futures):
            try:
                name, ext, secs = fut.result()
            except Exception as e:            # one bad agent shouldn't kill the build
                emit({"event": "agent_error", "agent": "?", "error": f"{type(e).__name__}: {e}"})
                continue
            extractions[name] = ext
            emit({"event": "agent_done", "agent": name, "extraction": ext.model_dump(),
                  "seconds": round(secs, 1)})

    if not extractions:
        raise RuntimeError("all agents failed")

    graph = merge(extractions)
    graph["agents"] = {name: ext.model_dump() for name, ext in extractions.items()}
    emit({"event": "merged", "graph": graph})
    return graph


def build_graph(report_path: str) -> dict:
    with open(report_path) as f:
        return build_graph_from_text(f.read())


def main():
    ap = argparse.ArgumentParser(description="Build a supply graph from one report file.")
    ap.add_argument("report")
    ap.add_argument("-o", "--out", default="graph.json")
    args = ap.parse_args()

    graph = build_graph(args.report)
    with open(args.out, "w") as f:
        json.dump(graph, f, indent=2)

    print(f"{len(graph['nodes'])} nodes, {len(graph['edges'])} edges, "
          f"{len(graph['claims'])} claims, {len(graph['dropped'])} dropped -> {args.out}")
    for n in graph["nodes"]:
        print(f"  node {n['id']}")
    for e in graph["edges"]:
        print(f"  edge {e['id']}: {e['from']} -> {e['to']}")
    for c in graph["claims"]:
        print(f"  claim {c['id']}: {c['type']:4s} {c['ref']:6s} = {c['value']:<8g} ({c['source']})")
    if graph["dropped"]:
        print("  dropped (no majority):")
        for d in graph["dropped"]:
            print(f"    {d}")


if __name__ == "__main__":
    sys.exit(main())
