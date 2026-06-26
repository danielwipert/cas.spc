"""Phase 4 exit gate — answer spec §8.4 follow-ups from state, not re-prompting.

Every assertion here is derived purely from the committed state history: no
operator is re-run and no model is called. This is what distinguishes the SPC
engine from the JSON-handoff baseline.
"""

from __future__ import annotations

from spc_state.models import EpistemicStatus, SemanticState
from spc_state.receipt import FollowUps


def test_what_did_the_critic_add(demo_history: list[SemanticState]) -> None:
    contribution = FollowUps(demo_history).what_did_operator_add("critic_transform")
    assert contribution.added_object_ids == ["claim_001", "q_002", "rel_002"]
    assert ("claim_001", 0.74, 0.62) in contribution.confidence_changes
    assert "0.74" in contribution.text and "0.62" in contribution.text


def test_which_claims_are_weakest(demo_history: list[SemanticState]) -> None:
    ranked = FollowUps(demo_history).weakest_claims()
    # Ascending confidence: claim_001 (0.62) is weakest.
    assert ranked.claim_ids[0] == "claim_001"
    assert ranked.claim_ids == ["claim_001", "claim_003", "claim_002"]


def test_weakest_claims_respects_limit(demo_history: list[SemanticState]) -> None:
    assert FollowUps(demo_history).weakest_claims(limit=1).claim_ids == ["claim_001"]


def test_assumptions_affecting_conclusion(demo_history: list[SemanticState]) -> None:
    answer = FollowUps(demo_history).assumptions_affecting_conclusion()
    top = answer.assumptions[0]
    assert top.assumption_id == "assumption_001"
    assert top.impact == "high"
    assert "claim_001" in top.dependent_claim_ids


def test_source_supporting_claim(demo_history: list[SemanticState]) -> None:
    support = FollowUps(demo_history).source_supporting_claim("claim_001")
    assert support.evidence_ids == ["ev_001"]
    assert "ev_001" in support.text


def test_changes_between_v1_and_v3(demo_history: list[SemanticState]) -> None:
    answer = FollowUps(demo_history).changes_between(1, 3)
    assert answer.diff.from_version == 1
    assert answer.diff.to_version == 3
    assert answer.diff.total_added == 6  # inf, hyp, q_001, q_002, rel_001, rel_002
    assert answer.diff.total_changed == 1  # claim_001 confidence


def test_unresolved_questions(demo_history: list[SemanticState]) -> None:
    answer = FollowUps(demo_history).unresolved_questions()
    assert answer.question_ids == ["q_001", "q_002"]


def test_recommendation_depends_on_assumption(demo_history: list[SemanticState]) -> None:
    answer = FollowUps(demo_history).recommendation_dependencies("assumption_001")
    # The claim depends on the assumption directly; the hypothesis (the
    # recommendation) depends on it transitively via its supporting claim.
    assert "claim_001" in answer.dependent_object_ids
    assert "hyp_001" in answer.dependent_object_ids


def test_inferred_versus_observed_claims(demo_history: list[SemanticState]) -> None:
    fu = FollowUps(demo_history)
    inferred = fu.claims_by_status(EpistemicStatus.INFERRED).claim_ids
    observed = fu.claims_by_status(EpistemicStatus.OBSERVED).claim_ids
    assert inferred == ["claim_001"]
    assert observed == ["claim_002", "claim_003"]


def test_followups_requires_history() -> None:
    import pytest

    with pytest.raises(ValueError):
        FollowUps([])
