"""T7 — end-to-end test for the `analyze` pipeline (TASKS.md).

`cli.analyze` used to inline the five-stage operator list and the runtime run,
with no test exercising them together — every LLM operator was tested alone.
`run_analysis` (src/spc_state/analyze.py) is the callable the CLI and this
test now share, driven here by an injected `MockProvider` (no network, no
key), so a wiring regression (operator order, ordinal/patch_id allocation,
memo/receipt projected from the final state) fails a test instead of shipping
silently.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

from spc_state.analyze import run_analysis
from spc_state.providers.mock import MockProvider
from spc_state.runtime import FixedClock
from spc_state.store import RunPaths

DOCUMENT = (
    "A six-month four-day-week pilot cut burnout 20% with flat revenue, though "
    "the pilot ran during a slow quarter."
)

EXTRACTION = {
    "claims": [
        {
            "text": "The four-day week reduced burnout.",
            "epistemic_status": "observed",
            "confidence": 0.85,
            "evidence_quote": "burnout 20%",
            "assumption": None,
        },
        {
            "text": "Revenue neutrality may not generalize.",
            "epistemic_status": "inferred",
            "confidence": 0.6,
            "evidence_quote": "the pilot ran during a slow quarter",
            "assumption": "seasonality drives revenue",
            "assumption_impact": "high",
        },
    ]
}

PLAN = {
    "hypothesis": {
        "text": "Adopt the four-day week permanently with revenue monitoring.",
        "confidence": 0.7,
        "supporting_claims": ["claim_001"],
    },
    "questions": [
        {
            "text": "Will revenue hold in a busy quarter?",
            "priority": "high",
            "linked_claims": ["claim_002"],
        }
    ],
    "dependencies": [{"claim": "claim_002", "assumption": "assumption_001"}],
}

CRITIQUE = {
    "confidence_updates": [
        {"claim": "claim_002", "new_confidence": 0.45, "reason": "slow-quarter sample"},
    ],
    "questions": [
        {
            "text": "Is the burnout effect durable?",
            "priority": "medium",
            "challenges_claim": "claim_002",
        }
    ],
}

NO_CONTRADICTIONS = {"contradictions": []}


def _clock() -> FixedClock:
    start = dt.datetime(2026, 6, 26, tzinfo=dt.UTC)
    return FixedClock([start + dt.timedelta(seconds=15 * i) for i in range(80)])


def _full_script() -> MockProvider:
    """One completion per LLM stage, in call order: extract, plan, critique,
    contradiction-detect. The retriever is deterministic and never calls the
    provider, so it is not in this script."""
    return MockProvider(
        [
            json.dumps(EXTRACTION),
            json.dumps(PLAN),
            json.dumps(CRITIQUE),
            json.dumps(NO_CONTRADICTIONS),
        ],
        provider="fake",
        model="m",
    )


# ---------------------------------------------------------------------------
# The full five-stage run.
# ---------------------------------------------------------------------------


def test_five_stage_run_reaches_v5(tmp_path: Path) -> None:
    paths = RunPaths(root=tmp_path / "runs", run_id="full")
    analysis = run_analysis(_full_script(), DOCUMENT, paths, clock=_clock())

    assert analysis.run.final_state.state_version == 5
    assert len(analysis.run.steps) == 5
    operators = [s.patch.transform_record.operator for s in analysis.run.steps]
    assert operators == [
        "llm_extract_transform",
        "llm_planner_transform",
        "llm_critic_transform",
        "retriever_transform",
        "contradiction_transform",
    ]
    # Every stage committed — nothing rejected or stuck in retry.
    assert all(s.decision.value == "COMMIT" for s in analysis.run.steps)


def test_five_stage_run_writes_one_patch_and_report_per_stage(tmp_path: Path) -> None:
    paths = RunPaths(root=tmp_path / "runs", run_id="artifacts")
    run_analysis(_full_script(), DOCUMENT, paths, clock=_clock())

    assert len(list(paths.patches_dir.glob("patch_*.json"))) == 5
    assert len(list(paths.validation_dir.glob("validation_*.json"))) == 5
    # One attempt file per LLM stage (extract, plan, critique, verify) — every
    # attempt is kept, even a first-try commit. The retriever stage is
    # deterministic (`Runtime.step`, not `step_llm`), so it leaves none.
    assert len(list(paths.patches_dir.glob("attempt_*.txt"))) == 4


def test_five_stage_run_produces_receipt_and_memo(tmp_path: Path) -> None:
    paths = RunPaths(root=tmp_path / "runs", run_id="docs")
    analysis = run_analysis(_full_script(), DOCUMENT, paths, clock=_clock())

    assert analysis.artifacts is not None
    assert analysis.memo_path is not None
    assert analysis.artifacts.receipt_path.exists()
    assert analysis.memo_path.exists()
    assert analysis.memo_path == paths.run_dir / "memo.md"


def test_five_stage_run_writes_a_cost_ledger(tmp_path: Path) -> None:
    """Four of the five stages are LLM-backed (T5) — the ledger must cover
    all four, priced by whatever model each one's provider reports."""
    paths = RunPaths(root=tmp_path / "runs", run_id="ledger")
    analysis = run_analysis(_full_script(), DOCUMENT, paths, clock=_clock())

    assert analysis.cost_ledger is not None
    assert len(analysis.cost_ledger.entries) == 4  # extract, plan, critique, verify
    assert analysis.cost_ledger.total_tokens > 0
    assert analysis.cost_ledger.total_estimated_cost_usd >= 0.0
    assert paths.cost_ledger_file().exists()


def test_memo_findings_cite_evidence_present_in_final_state(tmp_path: Path) -> None:
    """Every citation `[E#]` in the memo must resolve to real evidence — the
    memo is a faithful projection, never a claim the state doesn't hold."""
    paths = RunPaths(root=tmp_path / "runs", run_id="citations")
    analysis = run_analysis(_full_script(), DOCUMENT, paths, clock=_clock())

    final = analysis.run.final_state
    assert len(final.evidence) >= 1
    labels = {f"E{i}" for i in range(1, len(final.evidence) + 1)}

    memo_text = analysis.memo_path.read_text(encoding="utf-8")
    findings_section = memo_text.split("## Key findings", 1)[1]
    findings_section = findings_section.split("## ", 1)[0]

    finding_lines = [
        line for line in findings_section.splitlines() if line.startswith("- ")
    ]
    assert finding_lines  # the fixture's claims must actually render
    for line in finding_lines:
        cited = [tag.strip("[]") for tag in line.split() if tag.startswith("[E")]
        assert cited, f"finding has no citation: {line!r}"
        for tag in cited:
            assert tag in labels, f"citation {tag!r} does not resolve to real evidence"


# ---------------------------------------------------------------------------
# `--extract-only` stops after the first stage.
# ---------------------------------------------------------------------------


def test_extract_only_stops_after_the_first_stage(tmp_path: Path) -> None:
    paths = RunPaths(root=tmp_path / "runs", run_id="extract_only")
    provider = MockProvider([json.dumps(EXTRACTION)], provider="fake", model="m")

    analysis = run_analysis(
        provider, DOCUMENT, paths, clock=_clock(), extract_only=True
    )

    assert analysis.run.final_state.state_version == 1
    assert len(analysis.run.steps) == 1
    assert provider.call_count == 1
    assert analysis.artifacts is not None  # v1 is still a committed state to project
    assert analysis.memo_path is not None


# ---------------------------------------------------------------------------
# Nothing committed — no artifacts to project.
# ---------------------------------------------------------------------------


def test_nothing_committed_skips_artifacts_and_memo(tmp_path: Path) -> None:
    """If the extractor never produces a valid patch, there is no state to
    project a receipt or memo from — both must be skipped, not built empty."""
    paths = RunPaths(root=tmp_path / "runs", run_id="nothing")
    provider = MockProvider(["not json, just prose"], provider="fake", model="m")

    analysis = run_analysis(
        provider,
        DOCUMENT,
        paths,
        clock=_clock(),
        extract_only=True,
    )

    assert analysis.run.final_state.state_version == 0
    assert analysis.artifacts is None
    assert analysis.memo_path is None
    assert not (paths.run_dir / "memo.md").exists()
