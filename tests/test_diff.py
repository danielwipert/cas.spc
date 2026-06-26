"""Phase 4 — state-version diff by object type."""

from __future__ import annotations

from spc_state.diff import StateDiff, diff_states
from spc_state.models import SemanticState


def test_diff_v1_to_v3_added_and_changed(demo_history: list[SemanticState]) -> None:
    v1, v3 = demo_history[1], demo_history[3]
    diff = diff_states(v1, v3)

    assert diff.from_version == 1
    assert diff.to_version == 3
    assert diff.state_id == "sr_001"
    assert not diff.is_empty()

    # Planner + critic added a hypothesis, an inference, two questions, two
    # relations; nothing was removed.
    assert diff.by_type["hypothesis"].added == ["hyp_001"]
    assert diff.by_type["inference"].added == ["inf_001"]
    assert diff.by_type["question"].added == ["q_001", "q_002"]
    assert diff.by_type["relation"].added == ["rel_001", "rel_002"]
    assert diff.total_removed == 0


def test_diff_reports_field_change_on_claim_confidence(
    demo_history: list[SemanticState],
) -> None:
    diff = diff_states(demo_history[2], demo_history[3])
    changed = diff.by_type["claim"].changed
    assert len(changed) == 1
    ch = changed[0]
    assert ch.object_id == "claim_001"
    fields = {fc.field: (fc.from_value, fc.to_value) for fc in ch.field_changes}
    assert fields["confidence"] == (0.74, 0.62)


def test_diff_only_records_changed_types(demo_history: list[SemanticState]) -> None:
    # v2 -> v3: only claims (confidence), questions, relations change.
    diff = diff_states(demo_history[2], demo_history[3])
    assert set(diff.by_type) == {"claim", "question", "relation"}
    # Untouched types do not appear at all.
    assert "evidence" not in diff.by_type
    assert "assumption" not in diff.by_type


def test_identical_states_diff_is_empty(demo_history: list[SemanticState]) -> None:
    diff = diff_states(demo_history[3], demo_history[3])
    assert diff.is_empty()
    assert diff.by_type == {}


def test_diff_round_trips_through_json(demo_history: list[SemanticState]) -> None:
    # v2 -> v3 carries the claim_001 confidence change, so the from/to aliases
    # are exercised (a pure add/remove diff has no FieldChange entries).
    diff = diff_states(demo_history[2], demo_history[3])
    raw = diff.model_dump_json(by_alias=True)
    again = StateDiff.model_validate_json(raw)
    assert again == diff
    # The from/to aliases survive the round trip.
    assert '"from"' in raw and '"to"' in raw


def test_diff_does_not_mutate_inputs(demo_history: list[SemanticState]) -> None:
    v1, v3 = demo_history[1], demo_history[3]
    before_v1 = v1.model_dump_json()
    before_v3 = v3.model_dump_json()
    diff_states(v1, v3)
    assert v1.model_dump_json() == before_v1
    assert v3.model_dump_json() == before_v3
