"""Phase 7 — the OpenRouter provider and a live-shaped critic run.

No network or API key: a fake OpenAI-compatible client is injected, so these
tests exercise request mapping, response parsing, model resolution, and the
full runtime retry loop with an `OpenRouterProvider` standing in for a live
model.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from types import SimpleNamespace

import pytest

from spc_state.models import RouterDecision, SemanticState
from spc_state.operators import LLMCriticOperator
from spc_state.providers import (
    PROSE_RESPONSE,
    OpenRouterConfigError,
    OpenRouterProvider,
    ProviderRequest,
    build_valid_critic_payload,
)
from spc_state.providers.openrouter import DEFAULT_MODEL
from spc_state.runtime import FixedClock, Runtime
from spc_state.store import RunPaths

NOW = dt.datetime(2026, 6, 26, tzinfo=dt.UTC)
FIXTURE = Path(__file__).parent / "fixtures" / "semantic_state_v001.json"


def _state() -> SemanticState:
    return SemanticState.model_validate_json(FIXTURE.read_text(encoding="utf-8"))


class _FakeClient:
    """An OpenAI-compatible client whose completions are scripted."""

    def __init__(self, script: list[str]) -> None:
        self.calls: list[dict] = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))
        self._script = script

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        content = self._script[min(len(self.calls) - 1, len(self._script) - 1)]
        return SimpleNamespace(
            model="resolved/model-v1",
            choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
        )


# ---------------------------------------------------------------------------
# Config + model resolution
# ---------------------------------------------------------------------------


def test_missing_api_key_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    with pytest.raises(OpenRouterConfigError):
        OpenRouterProvider()


def test_model_resolution_prefers_explicit_then_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SPC_OPENROUTER_MODEL", raising=False)
    client = _FakeClient(["{}"])
    assert OpenRouterProvider(client=client, model="x/y").model == "x/y"

    monkeypatch.setenv("SPC_OPENROUTER_MODEL", "env/model")
    assert OpenRouterProvider(client=client).model == "env/model"

    monkeypatch.delenv("SPC_OPENROUTER_MODEL", raising=False)
    assert OpenRouterProvider(client=client).model == DEFAULT_MODEL


def test_default_model_is_value_based_not_frontier() -> None:
    # The default must be a cheap/value slug — never hardcode a flagship.
    assert DEFAULT_MODEL == "deepseek/deepseek-chat"


# ---------------------------------------------------------------------------
# Request mapping + response parsing
# ---------------------------------------------------------------------------


def test_complete_maps_request_and_parses_response() -> None:
    client = _FakeClient(['{"ok": true}'])
    provider = OpenRouterProvider(client=client, model="prov/model")
    resp = provider.complete(
        ProviderRequest(system="sys", user="hi", feedback=["L1.JSON_DECODE: bad"])
    )

    assert resp.text == '{"ok": true}'
    assert resp.fingerprint.provider == "openrouter"
    assert resp.fingerprint.model == "prov/model"
    assert resp.fingerprint.model_version == "resolved/model-v1"

    sent = client.calls[0]
    assert sent["model"] == "prov/model"
    assert sent["response_format"] == {"type": "json_object"}
    roles = [m["role"] for m in sent["messages"]]
    assert roles == ["system", "user", "user"]  # system + user + feedback turn
    assert "bad" in sent["messages"][-1]["content"]


def test_json_object_can_be_disabled() -> None:
    client = _FakeClient(["{}"])
    OpenRouterProvider(client=client, json_object=False).complete(ProviderRequest(user="x"))
    assert "response_format" not in client.calls[0]


# ---------------------------------------------------------------------------
# Full runtime run with the provider standing in for a live model
# ---------------------------------------------------------------------------


def _runtime(tmp_path: Path, run_id: str) -> Runtime:
    return Runtime(paths=RunPaths(root=tmp_path / "runs", run_id=run_id), clock=FixedClock(NOW))


def test_live_shaped_run_commits_a_valid_patch(tmp_path: Path) -> None:
    state = _state()
    client = _FakeClient([build_valid_critic_payload(state, now=NOW)])
    provider = OpenRouterProvider(client=client, model="prov/model")

    result = _runtime(tmp_path, "or_commit").run(
        initial_state=state, operators=[LLMCriticOperator(provider)]
    )
    step = result.steps[0]

    assert step.decision is RouterDecision.COMMIT
    assert result.final_state.state_version == 2
    assert "q_llm_001" in result.final_state.questions
    fp = step.patch.transform_record.model_fingerprint
    assert fp is not None and fp.provider == "openrouter"


def test_live_shaped_run_retries_on_prose_then_commits(tmp_path: Path) -> None:
    state = _state()
    client = _FakeClient([PROSE_RESPONSE, build_valid_critic_payload(state, now=NOW)])
    provider = OpenRouterProvider(client=client, model="prov/model")

    result = _runtime(tmp_path, "or_retry").run(
        initial_state=state, operators=[LLMCriticOperator(provider)]
    )
    step = result.steps[0]

    assert step.attempts == 2
    assert step.decision is RouterDecision.COMMIT
    assert result.final_state.state_version == 2
    # The validator feedback reached the model on the second call.
    second_call_messages = client.calls[1]["messages"]
    assert any("L1.JSON_DECODE" in m["content"] for m in second_call_messages)
