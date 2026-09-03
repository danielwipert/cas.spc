"""T4 — Mermaid state-graph export (TASKS.md).

`render_mermaid_graph` is a read-only projection of `SemanticState`: one node
per active object, one edge per active relation whose endpoints are both
active nodes. These tests lock the shape against the `demo_history` fixture
(the same canonical extract -> plan -> critique run used by the diff/receipt/
follow-up tests) and probe the edge cases the acceptance criteria call out:
determinism, stable ordering, and never inventing an edge the state doesn't
assert.
"""

from __future__ import annotations

import datetime as dt

from spc_state.models import (
    ClaimType,
    EpistemicStatus,
    ObjectStatus,
    Reliability,
    SemanticState,
)
from spc_state.models.objects import Claim, Contradiction, Entity, Evidence, Relation
from spc_state.receipt.graph import render_mermaid_graph
from spc_state.runtime import bootstrap_state

NOW = dt.datetime(2026, 6, 26, tzinfo=dt.UTC)


def _state(**overrides) -> SemanticState:
    base = bootstrap_state(state_id="s1", project_id="p1", name="n", now=NOW)
    return base.model_copy(update=overrides)


def _claim(cid: str, text: str, *, confidence: float = 0.8, status=ObjectStatus.ACTIVE) -> Claim:
    return Claim(
        id=cid,
        text=text,
        epistemic_status=EpistemicStatus.OBSERVED,
        claim_type=ClaimType.FACTUAL,
        confidence=confidence,
        status=status,
    )


def _evidence(eid: str, quote: str) -> Evidence:
    return Evidence(
        id=eid,
        source_type="document",
        source_id="doc_001",
        quote_or_span=quote,
        reliability=Reliability.MEDIUM,
    )


# ---------------------------------------------------------------------------
# The full demo state — a node per active object, an edge per relation.
# ---------------------------------------------------------------------------


def test_demo_state_has_a_node_per_active_object(demo_history: list[SemanticState]) -> None:
    final = demo_history[-1]
    graph = render_mermaid_graph(final)

    assert graph.startswith("flowchart TD")
    for cid in final.claims:
        assert f"{cid}[" in graph
    for eid in final.evidence:
        assert f"{eid}[" in graph
    for aid in final.assumptions:
        assert f"{aid}[" in graph
    for hid in final.hypotheses:
        assert f"{hid}[" in graph
    for qid in final.questions:
        assert f"{qid}[" in graph
    for iid in final.inferences:
        assert f"{iid}[" in graph
    # No object type is invented — nothing renders beyond what state holds.
    assert final.entities == {} and final.contradictions == {}


def test_demo_state_has_an_edge_per_relation(demo_history: list[SemanticState]) -> None:
    final = demo_history[-1]
    graph = render_mermaid_graph(final)

    assert len(final.relations) == 2  # pin the fixture's own shape
    for r in final.relations:
        assert f"{r.source} -->|{r.predicate}| {r.target}" in graph
    # The two examples TASKS.md names for T4, both present in this fixture.
    assert "claim_001 -->|depends_on| assumption_001" in graph
    assert "q_002 -->|questions| claim_001" in graph


def test_output_is_deterministic_across_calls(demo_history: list[SemanticState]) -> None:
    final = demo_history[-1]
    assert render_mermaid_graph(final) == render_mermaid_graph(final)


def test_node_and_edge_order_is_stable_and_type_grouped(
    demo_history: list[SemanticState],
) -> None:
    """Objects render in a fixed type order, sorted by id within each type —
    not insertion order, which would vary with how the state was built up."""
    graph = render_mermaid_graph(demo_history[-1])
    lines = [ln.strip() for ln in graph.splitlines()]

    claim_node_lines = [ln for ln in lines if ln.startswith("claim_00") and "[" in ln]
    assert claim_node_lines == sorted(claim_node_lines)  # claim_001, claim_002, claim_003

    claims_idx = next(i for i, ln in enumerate(lines) if ln.startswith("claim_001["))
    evidence_idx = next(i for i, ln in enumerate(lines) if ln.startswith("ev_001["))
    assumption_idx = next(i for i, ln in enumerate(lines) if ln.startswith("assumption_001["))
    assert claims_idx < evidence_idx < assumption_idx  # claims, then evidence, then assumptions


# ---------------------------------------------------------------------------
# Archived objects and orphaned relations are excluded.
# ---------------------------------------------------------------------------


def test_archived_claim_gets_no_node() -> None:
    state = _state(
        claims={
            "claim_001": _claim("claim_001", "Live claim."),
            "claim_002": _claim("claim_002", "Dead claim.", status=ObjectStatus.ARCHIVED),
        }
    )
    graph = render_mermaid_graph(state)
    assert "claim_001[" in graph
    assert "claim_002[" not in graph


def test_relation_to_an_archived_object_is_dropped() -> None:
    """A faithful projection never draws an edge to a node it omitted."""
    state = _state(
        claims={
            "claim_001": _claim("claim_001", "Live claim."),
            "claim_002": _claim("claim_002", "Dead claim.", status=ObjectStatus.ARCHIVED),
        },
        relations=[
            Relation(id="rel_001", source="claim_001", predicate="depends_on", target="claim_002")
        ],
    )
    graph = render_mermaid_graph(state)
    assert "claim_001 -->" not in graph
    assert "-->|depends_on|" not in graph


def test_archived_relation_itself_is_dropped() -> None:
    state = _state(
        claims={
            "claim_001": _claim("claim_001", "A."),
            "claim_002": _claim("claim_002", "B."),
        },
        relations=[
            Relation(
                id="rel_001",
                source="claim_001",
                predicate="depends_on",
                target="claim_002",
                status=ObjectStatus.ARCHIVED,
            )
        ],
    )
    graph = render_mermaid_graph(state)
    assert "claim_001[" in graph and "claim_002[" in graph
    assert "-->" not in graph


# ---------------------------------------------------------------------------
# Object types no shipped operator currently populates — still real model
# types the graph must render if a future operator (or a hand-built state)
# uses them.
# ---------------------------------------------------------------------------


def test_entity_node_uses_its_name() -> None:
    state = _state(entities={"entity_001": Entity(id="entity_001", name="Acme Corp")})
    graph = render_mermaid_graph(state)
    assert 'entity_001["Entity: Acme Corp"]' in graph


def test_contradiction_node_names_both_claims() -> None:
    state = _state(
        claims={
            "claim_001": _claim("claim_001", "Revenue rose."),
            "claim_002": _claim("claim_002", "Revenue fell."),
        },
        contradictions={
            "contradiction_001": Contradiction(
                id="contradiction_001", claim_a="claim_001", claim_b="claim_002"
            )
        },
    )
    graph = render_mermaid_graph(state)
    line = next(ln for ln in graph.splitlines() if "contradiction_001[" in ln)
    assert "claim_001 vs claim_002" in line


# ---------------------------------------------------------------------------
# Empty state and label hygiene.
# ---------------------------------------------------------------------------


def test_empty_state_is_a_bare_flowchart() -> None:
    graph = render_mermaid_graph(_state())
    assert graph == "flowchart TD"


def test_long_and_quoted_text_is_escaped_and_truncated() -> None:
    long_text = "A" * 200
    state = _state(claims={"claim_001": _claim("claim_001", f'Says "{long_text}"')})
    graph = render_mermaid_graph(state)

    line = next(ln for ln in graph.splitlines() if "claim_001[" in ln)
    # No unescaped double quotes inside the label body, and it stays short.
    label_body = line.split('["', 1)[1].rsplit('"]', 1)[0]
    assert '"' not in label_body
    assert len(label_body) < len(long_text)
    assert label_body.endswith("…")
