"""commit_patch tests — the only legal path to a new state version."""

from __future__ import annotations

import datetime as dt

import pytest

from spc_state.models import (
    Claim,
    ClaimType,
    EpistemicStatus,
    ObjectStatus,
    PatchStatus,
    Question,
    SemanticPatch,
    SemanticState,
    TransformRecord,
)
from spc_state.models.patch import AddObjects, ArchiveObject, UpdateObject
from spc_state.runtime.commit import CommitError, commit_patch

UTC = dt.timezone.utc


def _state_with_one_claim() -> SemanticState:
    now = dt.datetime(2026, 6, 26, tzinfo=UTC)
    state = SemanticState(
        state_id="sr_001",
        project_id="spc_pilot_001",
        name="commit test",
        state_version=0,
        created_at=now,
        updated_at=now,
    )
    # Promote to v1 via model_copy so we have something to update.
    return state.model_copy(
        update={
            "state_version": 1,
            "previous_state_version": 0,
            "updated_at": now,
            "claims": {
                "claim_001": Claim(
                    id="claim_001",
                    text="x",
                    claim_type=ClaimType.ANALYTICAL,
                    epistemic_status=EpistemicStatus.SPECULATIVE,
                    confidence=0.74,
                )
            },
        }
    )


def _patch(state: SemanticState, **overrides) -> SemanticPatch:
    now = dt.datetime(2026, 6, 26, 0, 10, tzinfo=UTC)
    base = {
        "patch_id": "patch_test",
        "patch_version": "0.1.0",
        "base_state_id": state.state_id,
        "base_state_version": state.state_version,
        "proposed_by": "test@0.1.0",
        "created_at": now,
        "read_set": [],
        "add_objects": AddObjects(),
        "update_objects": [],
        "add_relations": [],
        "archive_objects": [],
        "transform_record": TransformRecord(
            id="t_test",
            transform_type="test",
            operator="test_op",
            operator_version="test@0.1.0",
            input_state_version=state.state_version,
            read_set=[],
            write_set=[],
        ),
        "status": PatchStatus.PROPOSED,
    }
    base.update(overrides)
    return SemanticPatch.model_validate(base)


def test_commit_bumps_version_and_records_provenance() -> None:
    state = _state_with_one_claim()
    patch = _patch(
        state,
        add_objects=AddObjects(questions=[Question(id="q_new", text="?")]),
        transform_record=TransformRecord(
            id="t_test",
            transform_type="test",
            operator="test_op",
            operator_version="test@0.1.0",
            input_state_version=state.state_version,
            read_set=[],
            write_set=["q_new"],
        ),
    )

    now = dt.datetime(2026, 6, 26, 0, 15, tzinfo=UTC)
    new_state = commit_patch(state, patch, now=now)

    assert new_state.state_version == state.state_version + 1
    assert new_state.previous_state_version == state.state_version
    assert new_state.updated_at == now
    assert "q_new" in new_state.questions
    assert new_state.audit.committed_patches[-1] == "patch_test"
    # transform_log got the new entry with output_state_version filled in.
    assert new_state.transform_log[-1].output_state_version == new_state.state_version


def test_commit_does_not_mutate_base_state() -> None:
    state = _state_with_one_claim()
    snapshot = state.model_dump_json()
    patch = _patch(
        state,
        add_objects=AddObjects(questions=[Question(id="q_new", text="?")]),
        transform_record=TransformRecord(
            id="t_test",
            transform_type="test",
            operator="test_op",
            operator_version="test@0.1.0",
            input_state_version=state.state_version,
            read_set=[],
            write_set=["q_new"],
        ),
    )
    commit_patch(state, patch, now=dt.datetime(2026, 6, 26, tzinfo=UTC))
    assert state.model_dump_json() == snapshot


def test_commit_update_field() -> None:
    state = _state_with_one_claim()
    update = UpdateObject.model_validate(
        {
            "object_id": "claim_001",
            "field": "confidence",
            "from": 0.74,
            "to": 0.62,
            "reason": "evidence weaker than thought",
        }
    )
    patch = _patch(
        state,
        update_objects=[update],
        transform_record=TransformRecord(
            id="t_test",
            transform_type="test",
            operator="test_op",
            operator_version="test@0.1.0",
            input_state_version=state.state_version,
            read_set=["claim_001"],
            write_set=["claim_001"],
        ),
    )

    new_state = commit_patch(state, patch, now=dt.datetime(2026, 6, 26, tzinfo=UTC))
    assert new_state.claims["claim_001"].confidence == 0.62
    # The original state is untouched.
    assert state.claims["claim_001"].confidence == 0.74


def test_commit_archive_flips_status() -> None:
    state = _state_with_one_claim()
    patch = _patch(
        state,
        archive_objects=[ArchiveObject(object_id="claim_001", reason="superseded")],
        transform_record=TransformRecord(
            id="t_test",
            transform_type="test",
            operator="test_op",
            operator_version="test@0.1.0",
            input_state_version=state.state_version,
            read_set=["claim_001"],
            write_set=["claim_001"],
        ),
    )
    new_state = commit_patch(state, patch, now=dt.datetime(2026, 6, 26, tzinfo=UTC))
    assert new_state.claims["claim_001"].status is ObjectStatus.ARCHIVED


def test_commit_raises_if_update_target_missing() -> None:
    state = _state_with_one_claim()
    update = UpdateObject.model_validate(
        {"object_id": "ghost", "field": "confidence", "from": 0.5, "to": 0.4, "reason": "x"}
    )
    patch = _patch(
        state,
        update_objects=[update],
        transform_record=TransformRecord(
            id="t_test",
            transform_type="test",
            operator="test_op",
            operator_version="test@0.1.0",
            input_state_version=state.state_version,
            read_set=[],
            write_set=["ghost"],
        ),
    )
    with pytest.raises(CommitError):
        commit_patch(state, patch, now=dt.datetime(2026, 6, 26, tzinfo=UTC))
