"""LLM-backed Extract: turn an arbitrary document into a committed v1 state.

Uses an injected `MockProvider` (no network, no key) so the path is fully
exercised in CI: model output -> assembled patch -> validate -> route -> commit.
The document is deliberately *not* the demo scenario, proving the operator is
no longer keyed to a single input.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

from spc_state.operators import LLMExtractOperator
from spc_state.providers.mock import MockProvider
from spc_state.runtime import FixedClock, Runtime, bootstrap_state
from spc_state.store import RunPaths

# A document that has nothing to do with the AI-coding-assistant demo.
DOCUMENT = (
    "A company is weighing a permanent remote-work policy. Studies show a 13% "
    "productivity gain for routine tasks, but managers reported weaker ad-hoc "
    "collaboration when teams are fully remote."
)

EXTRACTION = {
    "claims": [
        {
            "text": "Remote work raises measured productivity for routine tasks.",
            "claim_type": "analytical_claim",
            "epistemic_status": "inferred",
            "confidence": 0.7,
            "evidence_quote": "Studies show a 13% productivity gain for routine tasks",
            "evidence_reliability": "medium",
            "assumption": "the studied population resembles our workforce",
            "assumption_impact": "high",
        },
        {
            "text": "Full remote work weakens ad-hoc collaboration.",
            "claim_type": "analytical_claim",
            "epistemic_status": "observed",
            "confidence": 0.6,
            "evidence_quote": "managers reported weaker ad-hoc collaboration",
            "evidence_reliability": "low",
            "assumption": None,
        },
    ]
}


def _clock() -> FixedClock:
    start = dt.datetime(2026, 6, 26, tzinfo=dt.UTC)
    return FixedClock([start + dt.timedelta(seconds=30 * i) for i in range(12)])


def _run(root: Path, script: list[str]):
    paths = RunPaths(root=root, run_id="extract_llm")
    clock = _clock()
    provider = MockProvider(script, provider="fake", model="fake-extract-v0")
    op = LLMExtractOperator(provider, input_text=DOCUMENT, clock=clock)
    runtime = Runtime(paths=paths, clock=clock)
    result = runtime.run(
        initial_state=bootstrap_state(
            state_id="sr_x", project_id="p", name="Remote work", now=clock.now()
        ),
        operators=[op],
        input_text=DOCUMENT,
    )
    return result


def test_extract_commits_claims_with_provenance(tmp_path: Path) -> None:
    result = _run(tmp_path, [json.dumps(EXTRACTION)])
    final = result.final_state
    assert final.state_version == 1
    assert set(final.claims) == {"claim_001", "claim_002"}
    # Every claim traces to an evidence span — receipt-grade provenance.
    assert final.claims["claim_001"].supporting_evidence == ["ev_001"]
    assert final.claims["claim_002"].supporting_evidence == ["ev_002"]
    assert "Studies show a 13%" in final.evidence["ev_001"].quote_or_span
    # The assumption is captured and linked to the claim that depends on it.
    assert final.claims["claim_001"].assumptions == ["assumption_001"]
    assert final.claims["claim_002"].assumptions == []


def test_extract_records_model_fingerprint(tmp_path: Path) -> None:
    result = _run(tmp_path, [json.dumps(EXTRACTION)])
    record = result.final_state.transform_log[0]
    assert record.model_fingerprint is not None
    assert record.model_fingerprint.provider == "fake"
    assert record.model_fingerprint.model == "fake-extract-v0"


def test_extract_dedupes_shared_assumptions(tmp_path: Path) -> None:
    shared = "the labor market stays stable"
    payload = {
        "claims": [
            {
                "text": "Hiring will accelerate next year.",
                "epistemic_status": "speculative",
                "confidence": 0.5,
                "evidence_quote": "leadership plans to grow headcount",
                "assumption": shared,
            },
            {
                "text": "Attrition will stay flat.",
                "epistemic_status": "speculative",
                "confidence": 0.4,
                "evidence_quote": "retention has been steady",
                "assumption": shared,
            },
        ]
    }
    final = _run(tmp_path, [json.dumps(payload)]).final_state
    assert set(final.assumptions) == {"assumption_001"}
    assert final.claims["claim_001"].assumptions == ["assumption_001"]
    assert final.claims["claim_002"].assumptions == ["assumption_001"]


def test_extract_strips_json_code_fence(tmp_path: Path) -> None:
    fenced = "```json\n" + json.dumps(EXTRACTION) + "\n```"
    final = _run(tmp_path, [fenced]).final_state
    assert final.state_version == 1
    assert len(final.claims) == 2


def test_prose_output_retries_then_fails_without_commit(tmp_path: Path) -> None:
    # Prose is never a patch: every attempt is JSON_DECODE -> RETRY, and with
    # the script repeating prose the run exhausts attempts and commits nothing.
    result = _run(tmp_path, ["I read the document and here are my thoughts..."])
    assert result.final_state.state_version == 0
    assert result.steps[0].decision.value == "RETRY"
    assert result.steps[0].attempts == 3


def test_prose_then_valid_json_commits_on_retry(tmp_path: Path) -> None:
    result = _run(tmp_path, ["not json at all", json.dumps(EXTRACTION)])
    assert result.final_state.state_version == 1
    assert result.steps[0].attempts == 2
