"""Phase 8 evaluation tests — §20 metrics, pilot report, §8.5 demo moment.

Every metric is asserted against the canonical deterministic demo run, so the
report cannot silently drift from the engine.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest

from spc_state.baseline import run_baseline
from spc_state.evaluation import estimate_tokens, evaluate, render_markdown, write_report
from spc_state.models import SemanticState
from spc_state.receipt import write_run_artifacts
from spc_state.store import RunPaths
from tests._demo_helpers import read_example, run_demo

GENERATED_AT = dt.datetime(2026, 6, 26, 0, 0, 0, tzinfo=dt.UTC)


def _full_run(root: Path) -> tuple[RunPaths, list[SemanticState]]:
    """Run the demo *and* write the Phase 4 artifacts (diffs + receipt)."""
    paths, states = run_demo(root)
    write_run_artifacts(paths, states, generated_at=GENERATED_AT)
    return paths, states


@pytest.fixture
def report(tmp_path: Path):
    paths, states = _full_run(tmp_path / "runs")
    baseline = run_baseline(read_example())
    return evaluate(
        run_id="demo_001",
        history=states,
        paths=paths,
        baseline=baseline,
        generated_at=GENERATED_AT,
    )


def _metric(report, key: str):
    return next(m for m in report.metrics if m.key == key)


def test_all_eight_metrics_present(report) -> None:
    keys = [m.key for m in report.metrics]
    assert keys == ["20.1", "20.2", "20.3", "20.4", "20.5", "20.6", "20.7", "20.8"]


def test_semantic_continuity(report) -> None:
    m = _metric(report, "20.1")
    assert m.spc["preserved_as_queryable_objects"] == 5
    assert m.baseline["preserved_as_queryable_objects"] == 0
    assert m.baseline["dropped_caveats"] >= 1


def test_provenance_completeness(report) -> None:
    m = _metric(report, "20.2")
    assert m.spc["ratio"] == 1.0
    assert m.baseline["ratio"] == 0.0


def test_drift_rate(report) -> None:
    m = _metric(report, "20.3")
    # SPC's one mutation (claim_001 confidence) is recorded and diff-visible.
    assert m.spc["unexplained"] == 0
    assert m.spc["detectable_by_system"] is True
    # The baseline's reworded claim is unexplained and undetectable.
    assert m.baseline["unexplained"] == 2
    assert m.baseline["detectable_by_system"] is False


def test_reprocessing_burden(report) -> None:
    m = _metric(report, "20.4")
    assert m.spc["full_document_reingestions"] == 1
    assert m.baseline["full_document_reingestions"] == 3
    assert m.baseline["source_tokens_reprocessed"] > m.spc["source_tokens_reprocessed"]


def test_contradiction_detection(report) -> None:
    m = _metric(report, "20.5")
    assert m.spc["tensions_preserved_as_objects"] >= 1
    assert m.baseline["tensions_preserved_as_objects"] == 0


def test_assumption_sensitivity(report) -> None:
    m = _metric(report, "20.6")
    assert m.spc["with_traceable_impact"] == 1
    assert m.spc["ranking_available"] is True
    assert m.baseline["assumptions"] == 0


def test_state_reuse_efficiency(report) -> None:
    m = _metric(report, "20.7")
    assert m.spc["answered_from_state"] == 8
    assert m.spc["new_source_tokens"] == 0
    assert m.baseline["answerable_from_artifacts"] == 0
    assert m.baseline["reprocessing_tokens_to_answer"] > 0


def test_audit_clarity(report) -> None:
    m = _metric(report, "20.8")
    # Full run: transform log, audit events, versions, diffs, patches,
    # validation reports, and the reasoning receipt — all seven present.
    assert m.spc["affordances_present"] == 7
    assert m.baseline["affordances_present"] == 0


def test_demo_moment_quotes_spec_phrasing(report) -> None:
    dm = report.demo_moment
    assert "reason through that again" in dm.baseline_response
    assert "exact object" in dm.spc_response
    # The SPC side names the actual objects the critic touched.
    assert "q_002" in dm.spc_response
    assert "claim_001" in dm.spc_response


def test_evaluate_requires_full_history(tmp_path: Path) -> None:
    paths, states = _full_run(tmp_path / "runs")
    baseline = run_baseline(read_example())
    with pytest.raises(ValueError):
        evaluate(
            run_id="x",
            history=states[:2],  # only v0, v1
            paths=paths,
            baseline=baseline,
            generated_at=GENERATED_AT,
        )


def test_report_render_is_deterministic(report) -> None:
    assert render_markdown(report) == render_markdown(report)


def test_write_report_emits_both_artifacts(tmp_path: Path, report) -> None:
    paths = RunPaths(root=tmp_path / "out", run_id="demo_001")
    md_path, json_path = write_report(paths, report)
    assert Path(md_path).exists()
    assert Path(json_path).exists()
    text = Path(md_path).read_text(encoding="utf-8")
    assert "Pilot Report" in text
    assert "Hypothesis verdicts" in text
    assert "The demo moment" in text


def test_estimate_tokens_monotonic() -> None:
    assert estimate_tokens("a") >= 1
    assert estimate_tokens("a" * 40) > estimate_tokens("a" * 4)
    assert estimate_tokens({"k": "v"}) >= 1
