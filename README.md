# defense-logistics

Logistics reports are messy. People radio in stock counts, drivers say they dropped off one
number, receivers count a different one, and someone always sends a correction at 1600. This
project takes those raw reports and turns them into one graph of the supply network: which
sites exist, what moved between them, and what each site says it has.

## What's here

- `graph_builder.py` — the V1 graph builder. Three LLM "agents" (Scout, Receiver, Auditor)
  each read the same report and pull out sites, transfers, and stock counts. Anything 2 of
  the 3 agree on gets kept. That's it, no fancy weighting yet.
- `server.py` + `ui/index.html` — a little dashboard. Upload a report, watch the three agents
  run, see the graph get drawn.
- `tests/` — one example report that works, and one that breaks it on purpose.
- `world.json`, `claims.py`, `estimator.py`, `orb/` — the synthetic world and estimators from
  the earlier checkpoint. Not wired into the graph builder yet.

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env        # paste your Anthropic API key in there
```

## Run it

```bash
python server.py
```

Open http://localhost:8000, drop in `tests/fixtures/example_report.txt`, hit **Build graph**.

Or skip the UI:

```bash
python graph_builder.py tests/fixtures/example_report.txt -o graph.json
```

## Tests

```bash
pytest tests/
```

`example_report.txt` should pass. `breaking_report.txt` is expected to fail (it's marked xfail).
It has site nicknames, a count split across two posts, a correction that contradicts an earlier
number, and a shipment going backwards. V1 doesn't handle any of that yet — upload it to the
dashboard to see the graph come out weird.

## What's next

- Use the graph as input to the estimators (`estimator.py`) to flag bad claims
- Handle corrections, aliases, and cycles
- Take in spreadsheets and other file types, not just text
