"""Phase 2 exit gate — SemanticState and SemanticPatch validate from disk.

The fixtures under tests/fixtures/ mirror the YAML examples in PILOT_SPEC.md
§11 and §12. They must:

1. Validate cleanly against the Pydantic models.
2. Round-trip (dump → reload → dump) without drift.
"""

from __future__ import annotations

import json
from pathlib import Path

from spc_state.models import SemanticPatch, SemanticState

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_semantic_state_v001_validates() -> None:
    payload = _load("semantic_state_v001.json")
    state = SemanticState.model_validate(payload)
    assert state.state_id == "sr_001"
    assert state.state_version == 1
    assert "claim_001" in state.claims
    assert state.claims["claim_001"].confidence == 0.74
    assert state.evidence["ev_001"].quote_or_span.startswith("Prior benchmark")
    assert state.assumptions["assumption_001"].if_false_effect is not None


def test_semantic_state_round_trips() -> None:
    payload = _load("semantic_state_v001.json")
    state = SemanticState.model_validate(payload)
    dumped = json.loads(state.model_dump_json(by_alias=True))
    rebuilt = SemanticState.model_validate(dumped)
    # Compare via canonical JSON to avoid datetime instance vs ISO-string skew.
    assert rebuilt.model_dump_json() == state.model_dump_json()


def test_semantic_patch_validates() -> None:
    payload = _load("semantic_patch_critic.json")
    patch = SemanticPatch.model_validate(payload)
    assert patch.patch_id == "patch_003"
    assert patch.base_state_version == 2
    assert patch.status.value == "proposed"
    assert len(patch.add_objects.contradictions) == 1
    assert patch.add_objects.contradictions[0].id == "contradiction_001"
    assert len(patch.update_objects) == 1
    upd = patch.update_objects[0]
    assert upd.object_id == "claim_001"
    assert upd.from_value == 0.74
    assert upd.to_value == 0.62
    assert patch.transform_record.write_set == ["contradiction_001", "q_001"]


def test_semantic_patch_round_trips_with_aliases() -> None:
    """The wire shape uses `from`/`to`; round-trip must preserve those keys."""
    payload = _load("semantic_patch_critic.json")
    patch = SemanticPatch.model_validate(payload)
    dumped = json.loads(patch.model_dump_json(by_alias=True))
    rebuilt = SemanticPatch.model_validate(dumped)
    assert rebuilt.update_objects[0].from_value == 0.74
    assert rebuilt.update_objects[0].to_value == 0.62
    # The `from`/`to` aliases survive a second dump too:
    dumped_again = json.loads(rebuilt.model_dump_json(by_alias=True))
    assert dumped_again["update_objects"][0]["from"] == 0.74
    assert dumped_again["update_objects"][0]["to"] == 0.62
