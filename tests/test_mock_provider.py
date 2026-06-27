"""Phase 6 — the mock provider returns scripted completions."""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

from spc_state.models import SemanticState
from spc_state.providers import (
    PROSE_RESPONSE,
    MockProvider,
    ProviderRequest,
    build_invalid_critic_payload,
    build_valid_critic_payload,
)

NOW = dt.datetime(2026, 6, 26, tzinfo=dt.UTC)
FIXTURE = Path(__file__).parent / "fixtures" / "semantic_state_v001.json"


def _state() -> SemanticState:
    return SemanticState.model_validate_json(FIXTURE.read_text(encoding="utf-8"))


def _req() -> ProviderRequest:
    return ProviderRequest(user="critique the state")


def test_mock_yields_scripted_responses_in_order() -> None:
    provider = MockProvider(["one", "two"])
    assert provider.complete(_req()).text == "one"
    assert provider.complete(_req()).text == "two"
    assert provider.call_count == 2


def test_mock_repeats_last_response_when_script_runs_dry() -> None:
    provider = MockProvider(["only"])
    assert provider.complete(_req()).text == "only"
    assert provider.complete(_req()).text == "only"
    assert provider.call_count == 2


def test_mock_attaches_a_fingerprint() -> None:
    provider = MockProvider(["x"], model="mock-critic-v0")
    resp = provider.complete(_req())
    assert resp.fingerprint.provider == "mock"
    assert resp.fingerprint.model == "mock-critic-v0"


def test_valid_payload_is_well_formed_patch_json() -> None:
    payload = build_valid_critic_payload(_state(), now=NOW)
    data = json.loads(payload)  # parses as JSON
    assert data["patch_id"] == "patch_llm_critic"
    assert data["base_state_version"] == 1
    assert data["update_objects"][0]["object_id"] == "claim_001"


def test_invalid_payload_targets_a_ghost_object() -> None:
    payload = build_invalid_critic_payload(_state(), now=NOW)
    data = json.loads(payload)
    assert data["update_objects"][0]["object_id"] == "claim_ghost"


def test_prose_response_is_not_json() -> None:
    import pytest

    with pytest.raises(json.JSONDecodeError):
        json.loads(PROSE_RESPONSE)
