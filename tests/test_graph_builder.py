"""
One end-to-end example: build a graph from tests/fixtures/example_report.txt
using the three LLM extractors and majority merge. Needs ANTHROPIC_API_KEY
(in .env or the environment); skipped otherwise.
"""

import os
import sys

import pytest
from dotenv import load_dotenv

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
load_dotenv(os.path.join(ROOT, ".env"))

from graph_builder import build_graph  # noqa: E402

FIXTURE = os.path.join(ROOT, "tests", "fixtures", "example_report.txt")


@pytest.mark.skipif(not os.getenv("ANTHROPIC_API_KEY"), reason="needs ANTHROPIC_API_KEY")
def test_builds_graph_from_example_report():
    graph = build_graph(FIXTURE)

    assert {n["id"] for n in graph["nodes"]} == {"DEPOT", "BASE_A", "BASE_B", "POST_1", "POST_2"}

    assert {(e["from"], e["to"]) for e in graph["edges"]} == {
        ("DEPOT", "BASE_A"), ("DEPOT", "BASE_B"), ("BASE_A", "POST_1"), ("BASE_A", "POST_2"),
    }

    stock = {(c["ref"], c["value"]) for c in graph["claims"] if c["type"] == "node"}
    assert {("DEPOT", 740), ("BASE_A", 185), ("BASE_B", 100), ("POST_1", 105), ("POST_2", 60)} <= stock

    edge_id = {(e["from"], e["to"]): e["id"] for e in graph["edges"]}
    depot_to_b = {c["value"] for c in graph["claims"]
                  if c["type"] == "edge" and c["ref"] == edge_id[("DEPOT", "BASE_B")]}
    assert {60, 58} <= depot_to_b   # driver said 60, receiver counted 58 -- both kept


BREAKING = os.path.join(ROOT, "tests", "fixtures", "breaking_report.txt")


@pytest.mark.skipif(not os.getenv("ANTHROPIC_API_KEY"), reason="needs ANTHROPIC_API_KEY")
@pytest.mark.xfail(strict=False, reason=(
    "V1 breaks on this report: site aliases (Alpha/Bravo), a combined count across two posts, "
    "a correction that conflicts with an earlier number, and a return shipment (cycle)."
))
def test_breaking_report_is_not_handled_yet():
    graph = build_graph(BREAKING)

    assert {n["id"] for n in graph["nodes"]} == {"DEPOT", "BASE_A", "BASE_B", "POST_1", "POST_2"}

    edge_id = {(e["from"], e["to"]): e["id"] for e in graph["edges"]}
    assert ("BASE_A", "POST_1") in edge_id and ("BASE_A", "POST_2") in edge_id  # "100 between them"

    depot_to_a = {c["value"] for c in graph["claims"]
                  if c["type"] == "edge" and c["ref"] == edge_id[("DEPOT", "BASE_A")]}
    assert depot_to_a == {125}      # the correction should replace 120, V1 keeps both

    assert ("BASE_B", "DEPOT") not in edge_id   # return shipment makes a cycle; tree assumed later
