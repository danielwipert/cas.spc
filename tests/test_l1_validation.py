"""L1 — schema validation tests. See PILOT_SPEC.md §16.1."""

from __future__ import annotations

import json

from spc_state.validation.l1 import parse_patch


def _well_formed_payload() -> dict:
    return {
        "patch_id": "patch_999",
        "patch_version": "0.1.0",
        "base_state_id": "sr_001",
        "base_state_version": 0,
        "proposed_by": "test@0.1.0",
        "created_at": "2026-06-26T00:00:00Z",
        "read_set": [],
        "add_objects": {},
        "update_objects": [],
        "add_relations": [],
        "archive_objects": [],
        "transform_record": {
            "id": "transform_test_001",
            "transform_type": "extract",
            "operator": "test_op",
            "operator_version": "test_op@0.1.0",
            "input_state_version": 0,
            "output_state_version": None,
            "read_set": [],
            "write_set": [],
            "confidence_changes": [],
        },
        "status": "proposed",
    }


def test_well_formed_patch_yields_no_issues() -> None:
    patch, issues = parse_patch(_well_formed_payload())
    assert patch is not None
    assert patch.patch_id == "patch_999"
    assert issues == []


def test_unknown_field_is_l1_error() -> None:
    payload = _well_formed_payload()
    payload["smuggled_field"] = "denied"
    patch, issues = parse_patch(payload)
    assert patch is None
    assert any(i.code.startswith("L1.") for i in issues)


def test_confidence_out_of_range_is_l1_error() -> None:
    payload = _well_formed_payload()
    payload["add_objects"] = {
        "claims": [
            {
                "id": "claim_X",
                "object_type": "claim",
                "text": "x",
                "epistemic_status": "inferred",
                "confidence": 1.5,
            }
        ]
    }
    patch, issues = parse_patch(payload)
    assert patch is None
    assert issues
    # The error should point at the bad confidence field.
    assert any("confidence" in (i.field or "") for i in issues)


def test_json_decode_failure_produces_retry_signal_code() -> None:
    patch, issues = parse_patch("{ this is not json")
    assert patch is None
    assert len(issues) == 1
    assert issues[0].code == "L1.JSON_DECODE"


def test_json_string_input_round_trips() -> None:
    payload = _well_formed_payload()
    patch, issues = parse_patch(json.dumps(payload))
    assert patch is not None and not issues
