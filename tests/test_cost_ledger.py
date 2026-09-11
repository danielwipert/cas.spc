"""T5 — per-operator model routing + cost ledger (TASKS.md).

Per-operator model routing needs no new mechanism: every operator already
takes its own `LLMProvider` instance, and a provider carries its own model —
two operators handed two differently-configured `MockProvider`s already run
two different models. What's new here is the accounting: `Runtime.step_llm`
now sums each step's token usage across every attempt (a retry is a real,
billed call) and stamps it on the committed `TransformRecord`
(`token_usage`, alongside `model_fingerprint`); `build_cost_ledger` reads
those back and prices them by model. All injected providers — no network,
no key.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

from spc_state.cost_ledger import build_cost_ledger, write_cost_ledger
from spc_state.models import SemanticState
from spc_state.models.transform import TokenUsage
from spc_state.operators import LLMCriticOperator, LLMExtractOperator, LLMPlannerOperator
from spc_state.projection import build_projection, resolve_view
from spc_state.providers import (
    PROSE_RESPONSE,
    MockProvider,
    build_valid_critic_payload,
)
from spc_state.providers.openrouter import (
    MODEL_PRICING_PER_MILLION_USD,
    estimate_cost_usd,
)
from spc_state.runtime import FixedClock, Runtime, bootstrap_state
from spc_state.store import RunPaths

NOW = dt.datetime(2026, 6, 26, tzinfo=dt.UTC)
FIXTURE = Path(__file__).parent / "fixtures" / "semantic_state_v001.json"

DOCUMENT = "A six-month pilot cut burnout 20% with flat revenue."
EXTRACTION = {
    "claims": [
        {
            "text": "Burnout fell during the pilot.",
            "epistemic_status": "observed",
            "confidence": 0.8,
            "evidence_quote": "burnout 20%",
            "assumption": None,
        }
    ]
}
PLAN = {
    "hypothesis": {
        "text": "Adopt the four-day week.",
        "confidence": 0.7,
        "supporting_claims": ["claim_001"],
    },
    "questions": [],
    "dependencies": [],
}


def _state() -> SemanticState:
    return SemanticState.model_validate_json(FIXTURE.read_text(encoding="utf-8"))


def _clock() -> FixedClock:
    return FixedClock([NOW + dt.timedelta(seconds=i) for i in range(80)])


def _runtime(tmp_path: Path, run_id: str) -> Runtime:
    return Runtime(paths=RunPaths(root=tmp_path / "runs", run_id=run_id), clock=_clock())


# ---------------------------------------------------------------------------
# Two operators, two models — the acceptance scenario.
# ---------------------------------------------------------------------------


def test_two_operators_with_different_models_get_different_fingerprints_and_costs(
    tmp_path: Path,
) -> None:
    clock = _clock()
    provider_a = MockProvider([json.dumps(EXTRACTION)], provider="fake", model="model-a")
    provider_b = MockProvider([json.dumps(PLAN)], provider="fake", model="model-b")

    runtime = Runtime(paths=RunPaths(root=tmp_path / "runs", run_id="two_models"), clock=clock)
    result = runtime.run(
        initial_state=bootstrap_state(state_id="s", project_id="p", name="n", now=clock.now()),
        operators=[
            LLMExtractOperator(provider_a, input_text=DOCUMENT, clock=clock),
            LLMPlannerOperator(provider_b, clock=clock),
        ],
        input_text=DOCUMENT,
    )

    fingerprints = [
        s.patch.transform_record.model_fingerprint.model for s in result.steps
    ]
    assert fingerprints == ["model-a", "model-b"]  # per-operator model routing

    ledger = build_cost_ledger("two_models", result.steps)
    assert len(ledger.entries) == 2
    assert {e.model for e in ledger.entries} == {"model-a", "model-b"}
    for entry in ledger.entries:
        assert entry.total_tokens > 0  # a real per-step token count
        assert entry.estimated_cost_usd >= 0.0  # non-negative estimated cost
    assert ledger.total_tokens == sum(e.total_tokens for e in ledger.entries)
    assert ledger.total_estimated_cost_usd >= 0.0


def test_ledger_writes_valid_json(tmp_path: Path) -> None:
    provider = MockProvider([build_valid_critic_payload(_state(), now=NOW)])
    runtime = _runtime(tmp_path, "written")
    result = runtime.run(initial_state=_state(), operators=[LLMCriticOperator(provider)])

    ledger = build_cost_ledger("written", result.steps)
    path = write_cost_ledger(runtime.paths, ledger)

    assert path == runtime.paths.cost_ledger_file()
    on_disk = json.loads(path.read_text(encoding="utf-8"))
    assert on_disk["run_id"] == "written"
    assert len(on_disk["entries"]) == 1
    assert on_disk["total_tokens"] == on_disk["entries"][0]["total_tokens"]


# ---------------------------------------------------------------------------
# Retries: every attempt is a real, billed call.
# ---------------------------------------------------------------------------


def test_retried_step_sums_usage_across_every_attempt(tmp_path: Path) -> None:
    """Two attempts (prose, then a valid patch) must both be counted — the
    prose attempt cost tokens too, even though it never became the patch."""
    state = _state()
    provider = MockProvider([PROSE_RESPONSE, build_valid_critic_payload(state, now=NOW)])
    runtime = _runtime(tmp_path, "retry_sum")
    result = runtime.run(initial_state=state, operators=[LLMCriticOperator(provider)])

    step = result.steps[0]
    assert step.attempts == 2
    usage = step.patch.transform_record.token_usage
    assert usage is not None

    # What the prose-only first attempt alone spent, recomputed independently
    # from the same operator/state — the stamped total must exceed this,
    # proving it is the SUM of both attempts, not just the winning one's.
    critic = LLMCriticOperator(MockProvider([PROSE_RESPONSE]))
    view = resolve_view(
        build_projection(state, perspective=critic.perspective, goal=critic.goal), state
    )
    prose_usage = critic.provider.complete(critic.build_request(view, [])).usage
    assert prose_usage is not None
    assert usage.prompt_tokens > prose_usage.prompt_tokens


def test_rejected_step_still_has_a_ledger_entry(tmp_path: Path) -> None:
    """A REJECTed (not committed) step still cost tokens — the ledger reads
    from `step.patch`, which the audit-trail fix keeps even when rejected."""
    from spc_state.providers import build_invalid_critic_payload

    state = _state()
    provider = MockProvider([build_invalid_critic_payload(state, now=NOW)])
    runtime = _runtime(tmp_path, "rejected")
    result = runtime.run(initial_state=state, operators=[LLMCriticOperator(provider)])

    assert result.steps[0].decision.value == "REJECT"
    ledger = build_cost_ledger("rejected", result.steps)
    assert len(ledger.entries) == 1
    assert ledger.entries[0].total_tokens > 0


# ---------------------------------------------------------------------------
# Deterministic steps and unparseable steps contribute nothing.
# ---------------------------------------------------------------------------


def test_deterministic_step_has_no_ledger_entry(tmp_path: Path) -> None:
    from spc_state.operators import CriticOperator

    clock = _clock()
    runtime = _runtime(tmp_path, "deterministic")
    state = _state()
    result = runtime.run(
        initial_state=state,
        operators=[CriticOperator(clock=clock)],
    )
    ledger = build_cost_ledger("deterministic", result.steps)
    assert ledger.entries == []
    assert ledger.total_tokens == 0
    assert ledger.total_estimated_cost_usd == 0.0


def test_a_step_that_committed_nothing_still_appears_in_the_ledger(
    tmp_path: Path,
) -> None:
    """T13: every attempt was prose, so no patch and no `TransformRecord` — but
    both calls were billed, and a ledger that omits them understates the run."""
    state = _state()
    provider = MockProvider([PROSE_RESPONSE])
    runtime = _runtime(tmp_path, "exhausted")
    result = runtime.run(
        initial_state=state, operators=[LLMCriticOperator(provider, max_attempts=2)]
    )

    assert result.steps[0].patch is None
    ledger = build_cost_ledger("exhausted", result.steps)

    assert len(ledger.entries) == 1
    entry = ledger.entries[0]
    assert entry.committed is False
    assert entry.transform_id is None, "nothing committed, so nothing to name"
    assert entry.operator == "llm_critic_transform"
    assert entry.attempts == 2, "both billed calls are covered by this row"
    assert entry.total_tokens > 0
    assert entry.estimated_cost_usd > 0.0

    # The run's spend and the spend that bought nothing are both visible, and
    # here they are the same thing: this run committed no state at all.
    assert ledger.uncommitted_tokens == ledger.total_tokens
    assert ledger.uncommitted_estimated_cost_usd == ledger.total_estimated_cost_usd


def test_a_committed_step_is_named_and_marked_committed(tmp_path: Path) -> None:
    """The other side of the same row: attribution still works as before."""
    state = _state()
    provider = MockProvider([build_valid_critic_payload(state, now=NOW)])
    runtime = _runtime(tmp_path, "committed")
    result = runtime.run(
        initial_state=state, operators=[LLMCriticOperator(provider, max_attempts=2)]
    )

    ledger = build_cost_ledger("committed", result.steps)
    assert len(ledger.entries) == 1
    entry = ledger.entries[0]
    assert entry.committed is True
    assert entry.transform_id is not None
    assert entry.attempts == 1
    assert ledger.uncommitted_tokens == 0


# ---------------------------------------------------------------------------
# Pricing.
# ---------------------------------------------------------------------------


def test_unlisted_model_gets_a_conservative_default_price() -> None:
    usage = TokenUsage(prompt_tokens=1_000_000, completion_tokens=1_000_000)
    cost = estimate_cost_usd("some/unlisted-model", usage)
    assert cost > 0.0  # never silently $0 for an unrecognized slug


def test_listed_models_price_differently() -> None:
    usage = TokenUsage(prompt_tokens=1_000_000, completion_tokens=1_000_000)
    prices = {
        model: estimate_cost_usd(model, usage) for model in MODEL_PRICING_PER_MILLION_USD
    }
    assert len(set(prices.values())) > 1  # not one flat rate for every model
