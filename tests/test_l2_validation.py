"""L2 — referential and provenance validation tests. See PILOT_SPEC.md §16.2."""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import pytest

from spc_state.models import SemanticPatch, SemanticState, ValidationSeverity
from spc_state.validation.l2 import validate_patch

FIXTURES = Path(__file__).resolve().parent / "fixtures"
UTC = dt.timezone.utc


@pytest.fixture
def base_state() -> SemanticState:
    payload = json.loads((FIXTURES / "semantic_state_v001.json").read_text(encoding="utf-8"))
    return SemanticState.model_validate(payload)


@pytest.fixture
def critic_patch_payload() -> dict:
    return json.loads((FIXTURES / "semantic_patch_critic.json").read_text(encoding="utf-8"))


def _patch_with(payload: dict, **overrides) -> SemanticPatch:
    merged = {**payload, **overrides}
    return SemanticPatch.model_validate(merged)


def test_base_version_mismatch_is_error(base_state, critic_patch_payload) -> None:
    # The fixture's base_state_version is 2; our base_state is version 1.
    patch = SemanticPatch.model_validate(critic_patch_payload)
    issues = validate_patch(base_state, patch)
    codes = {i.code for i in issues if i.severity is ValidationSeverity.ERROR}
    assert "L2.BASE_STATE_VERSION_MISMATCH" in codes


def test_unresolved_read_set_ref_is_error(base_state, critic_patch_payload) -> None:
    # claim_002 / assumption_001 are in read_set; claim_002 isn't in v1 yet.
    patch = SemanticPatch.model_validate(critic_patch_payload)
    issues = validate_patch(base_state, patch)
    codes = {i.code for i in issues if i.severity is ValidationSeverity.ERROR}
    assert "L2.UNRESOLVED_READ_SET_REF" in codes


def test_duplicate_id_is_error() -> None:
    state = _empty_state()
    payload = _empty_patch_payload(base_version=0, base_id="sr_001")
    # add a claim whose id collides with one already in state -- but state
    # is empty here, so we'll set up a collision against a freshly-added id.
    payload["add_objects"] = {
        "claims": [
            _new_claim("claim_X", evidence_id="ev_X"),
            _new_claim("claim_X", evidence_id="ev_X"),  # dup inside patch
        ]
    }
    payload["transform_record"]["write_set"] = ["claim_X"]
    patch = SemanticPatch.model_validate(payload)
    issues = validate_patch(state, patch)
    assert any(i.code == "L2.DUPLICATE_NEW_ID_IN_PATCH" for i in issues)


def test_unresolved_relation_target_is_error() -> None:
    state = _empty_state()
    payload = _empty_patch_payload(base_version=0, base_id="sr_001")
    payload["add_relations"] = [
        {
            "id": "rel_ghost",
            "object_type": "relation",
            "source": "ghost_1",
            "predicate": "questions",
            "target": "ghost_2",
            "confidence": 1.0,
            "status": "active",
        }
    ]
    payload["transform_record"]["write_set"] = ["rel_ghost"]
    patch = SemanticPatch.model_validate(payload)
    issues = validate_patch(state, patch)
    codes = {i.code for i in issues if i.severity is ValidationSeverity.ERROR}
    assert "L2.RELATION_SOURCE_UNRESOLVED" in codes
    assert "L2.RELATION_TARGET_UNRESOLVED" in codes


def test_unresolved_update_target_is_error() -> None:
    state = _empty_state()
    payload = _empty_patch_payload(base_version=0, base_id="sr_001")
    payload["update_objects"] = [
        {
            "object_id": "ghost_claim",
            "field": "confidence",
            "from": 0.5,
            "to": 0.4,
            "reason": "x",
        }
    ]
    payload["transform_record"]["write_set"] = ["ghost_claim"]
    patch = SemanticPatch.model_validate(payload)
    issues = validate_patch(state, patch)
    assert any(i.code == "L2.UNRESOLVED_UPDATE_TARGET" for i in issues)


def test_high_confidence_claim_without_provenance_is_error() -> None:
    state = _empty_state()
    payload = _empty_patch_payload(base_version=0, base_id="sr_001")
    payload["add_objects"] = {
        "claims": [
            {
                "id": "claim_naked",
                "object_type": "claim",
                "text": "Big claim, no support.",
                "claim_type": "analytical_claim",
                "epistemic_status": "inferred",
                "confidence": 0.9,
                "status": "active",
                "supporting_evidence": [],
                "assumptions": [],
                "contradicted_by": [],
                "derived_from": [],
            }
        ]
    }
    payload["transform_record"]["write_set"] = ["claim_naked"]
    patch = SemanticPatch.model_validate(payload)
    issues = validate_patch(state, patch)
    errs = [i for i in issues if i.severity is ValidationSeverity.ERROR]
    assert any(i.code == "L2.CLAIM_MISSING_PROVENANCE" for i in errs)


def test_speculative_claim_without_provenance_is_allowed() -> None:
    state = _empty_state()
    payload = _empty_patch_payload(base_version=0, base_id="sr_001")
    payload["add_objects"] = {
        "claims": [
            {
                "id": "claim_speculative",
                "object_type": "claim",
                "text": "Maybe.",
                "claim_type": "analytical_claim",
                "epistemic_status": "speculative",
                "confidence": 0.4,
                "status": "active",
                "supporting_evidence": [],
                "assumptions": [],
                "contradicted_by": [],
                "derived_from": [],
            }
        ]
    }
    payload["transform_record"]["write_set"] = ["claim_speculative"]
    patch = SemanticPatch.model_validate(payload)
    issues = validate_patch(state, patch)
    codes = {i.code for i in issues if i.severity is ValidationSeverity.ERROR}
    assert "L2.CLAIM_MISSING_PROVENANCE" not in codes


def test_undeclared_write_is_a_warning() -> None:
    state = _empty_state()
    payload = _empty_patch_payload(base_version=0, base_id="sr_001")
    payload["add_objects"] = {
        "questions": [
            {
                "id": "q_silent",
                "object_type": "question",
                "text": "?",
                "status": "open",
                "priority": "medium",
                "linked_objects": [],
            }
        ]
    }
    # Intentionally leave write_set empty.
    payload["transform_record"]["write_set"] = []
    patch = SemanticPatch.model_validate(payload)
    issues = validate_patch(state, patch)
    warns = [i for i in issues if i.severity is ValidationSeverity.WARNING]
    assert any(i.code == "L2.UNDECLARED_WRITE" for i in warns)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _empty_state() -> SemanticState:
    now = dt.datetime(2026, 6, 26, 0, 0, 0, tzinfo=UTC)
    return SemanticState(
        state_id="sr_001",
        project_id="spc_pilot_001",
        name="L2 test",
        state_version=0,
        created_at=now,
        updated_at=now,
    )


def _empty_patch_payload(*, base_version: int, base_id: str) -> dict:
    return {
        "patch_id": "patch_test",
        "patch_version": "0.1.0",
        "base_state_id": base_id,
        "base_state_version": base_version,
        "proposed_by": "test_op@0.1.0",
        "created_at": "2026-06-26T00:00:00Z",
        "read_set": [],
        "add_objects": {},
        "update_objects": [],
        "add_relations": [],
        "archive_objects": [],
        "transform_record": {
            "id": "transform_test",
            "transform_type": "extract",
            "operator": "test_op",
            "operator_version": "test_op@0.1.0",
            "input_state_version": base_version,
            "output_state_version": None,
            "read_set": [],
            "write_set": [],
            "confidence_changes": [],
        },
        "status": "proposed",
    }


def _new_claim(claim_id: str, *, evidence_id: str) -> dict:
    return {
        "id": claim_id,
        "object_type": "claim",
        "text": f"Claim {claim_id}.",
        "claim_type": "analytical_claim",
        "epistemic_status": "inferred",
        "confidence": 0.7,
        "status": "active",
        "supporting_evidence": [evidence_id],
        "assumptions": [],
        "contradicted_by": [],
        "derived_from": [],
    }
