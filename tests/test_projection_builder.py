"""Phase 5 — perspective-specific projections select the right slice.

Each perspective in PILOT_SPEC.md §14.2 sees a different cut of the same
state. These tests assert against the demo's final state (v3), where the
claims, evidence, assumptions, hypotheses, questions, and relations are all
populated, so every perspective has something to include and something to hide.
"""

from __future__ import annotations

from spc_state.models import Perspective, SemanticState
from spc_state.projection import build_projection

GOAL = "test goal"


def _final(demo_history: list[SemanticState]) -> SemanticState:
    """The post-critic state v3."""
    return demo_history[3]


# ---------------------------------------------------------------------------
# Critic — weak claims, weak evidence, assumptions, contradictions.
# ---------------------------------------------------------------------------


def test_critic_sees_only_weak_claims_and_weak_evidence(demo_history) -> None:
    state = _final(demo_history)
    inc = build_projection(state, perspective=Perspective.CRITIC, goal=GOAL).included_objects

    # claim_001 is weak (inferred, confidence 0.62 after the critic's own
    # earlier pass); claim_002/claim_003 are observed and high-confidence.
    assert inc.claims == ["claim_001"]
    # ev_001 is MEDIUM reliability (weak); ev_002/ev_003 are HIGH.
    assert inc.evidence == ["ev_001"]
    # The critic always sees every assumption.
    assert "assumption_001" in inc.assumptions


def test_critic_keeps_dependency_edges_within_its_slice(demo_history) -> None:
    state = _final(demo_history)
    inc = build_projection(state, perspective=Perspective.CRITIC, goal=GOAL).included_objects
    # rel_001 (claim_001 -> assumption_001) and rel_002 (q_002 -> claim_001)
    # both have endpoints inside the critic slice.
    assert set(inc.relations) == {"rel_001", "rel_002"}


# ---------------------------------------------------------------------------
# Writer — high-confidence claims only, no raw evidence, writer notes on.
# ---------------------------------------------------------------------------


def test_writer_sees_strong_claims_not_weak_ones(demo_history) -> None:
    state = _final(demo_history)
    proj = build_projection(state, perspective=Perspective.WRITER, goal=GOAL)
    inc = proj.included_objects

    assert "claim_001" not in inc.claims  # weak — hidden from the writer
    assert set(inc.claims) == {"claim_002", "claim_003"}
    assert inc.evidence == []  # writer works from claims, not raw spans
    assert proj.projection_policy.include_low_confidence_claims is False
    assert proj.projection_policy.include_writer_notes is True


# ---------------------------------------------------------------------------
# Planner — decision skeleton, no evidence spans.
# ---------------------------------------------------------------------------


def test_planner_sees_structure_but_not_evidence(demo_history) -> None:
    state = _final(demo_history)
    proj = build_projection(state, perspective=Perspective.PLANNER, goal=GOAL)
    inc = proj.included_objects

    assert set(inc.claims) == {"claim_001", "claim_002", "claim_003"}
    assert "hyp_001" in inc.hypotheses
    assert set(inc.questions) == {"q_001", "q_002"}
    assert inc.evidence == []
    assert proj.projection_policy.include_evidence_spans is False


# ---------------------------------------------------------------------------
# Retriever — evidence gaps and open questions.
# ---------------------------------------------------------------------------


def test_retriever_sees_open_questions_and_all_evidence(demo_history) -> None:
    state = _final(demo_history)
    inc = build_projection(state, perspective=Perspective.RETRIEVER, goal=GOAL).included_objects

    assert set(inc.questions) == {"q_001", "q_002"}  # both still open
    assert set(inc.evidence) == {"ev_001", "ev_002", "ev_003"}
    # claim_001 is still an evidence gap (weak); the strong claims are not.
    assert inc.claims == ["claim_001"]


# ---------------------------------------------------------------------------
# Verifier — claims + evidence + provenance, no hypotheses/questions.
# ---------------------------------------------------------------------------


def test_verifier_sees_claims_and_evidence_not_hypotheses(demo_history) -> None:
    state = _final(demo_history)
    inc = build_projection(state, perspective=Perspective.VERIFIER, goal=GOAL).included_objects

    assert set(inc.claims) == {"claim_001", "claim_002", "claim_003"}
    assert set(inc.evidence) == {"ev_001", "ev_002", "ev_003"}
    assert inc.hypotheses == []
    assert inc.questions == []


# ---------------------------------------------------------------------------
# Executive — recommendation + high-impact risks.
# ---------------------------------------------------------------------------


def test_executive_sees_hypothesis_and_high_impact_assumption(demo_history) -> None:
    state = _final(demo_history)
    inc = build_projection(state, perspective=Perspective.EXECUTIVE, goal=GOAL).included_objects

    assert "hyp_001" in inc.hypotheses
    assert inc.assumptions == ["assumption_001"]  # the one HIGH-impact assumption
    assert "claim_001" not in inc.claims  # weak claims don't reach the exec view


# ---------------------------------------------------------------------------
# Extract — passthrough over the (initially empty) state.
# ---------------------------------------------------------------------------


def test_extract_is_passthrough_and_empty_on_v0(demo_history) -> None:
    v0 = demo_history[0]
    inc = build_projection(v0, perspective=Perspective.EXTRACT, goal=GOAL).included_objects
    assert inc.claims == []
    assert inc.evidence == []
    assert inc.assumptions == []


def test_extract_passes_everything_through_on_v3(demo_history) -> None:
    state = _final(demo_history)
    inc = build_projection(state, perspective=Perspective.EXTRACT, goal=GOAL).included_objects
    assert set(inc.claims) == {"claim_001", "claim_002", "claim_003"}
    assert set(inc.evidence) == {"ev_001", "ev_002", "ev_003"}
