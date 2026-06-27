"""Tests for the orchestrated §8 North Star demo (`spc-demo demo`)."""

from __future__ import annotations

from pathlib import Path

from spc_state.demo import render_demo_markdown, run_full_demo, write_demo_markdown
from tests._demo_helpers import read_example


def _run(root: Path):
    return run_full_demo(
        runs_dir=root / "runs",
        run_id="demo",
        document=read_example(),
    )


def test_demo_runs_three_committed_steps(tmp_path: Path) -> None:
    result = _run(tmp_path)
    assert [s.ordinal for s in result.steps] == [1, 2, 3]
    assert all(s.decision == "COMMIT" for s in result.steps)
    assert result.steps[-1].state_version == 3
    # The critic step records the confidence drop on claim_001.
    critic = result.steps[-1]
    assert any(oid == "claim_001" for oid, _, _ in critic.confidence_changes)


def test_demo_produces_full_evaluation(tmp_path: Path) -> None:
    result = _run(tmp_path)
    assert result.evaluation is not None
    assert len(result.evaluation.metrics) == 8
    assert result.evaluation.followups_spc_answered == 8
    assert not result.warnings


def test_demo_writes_artifacts(tmp_path: Path) -> None:
    result = _run(tmp_path)
    assert Path(result.report_md_path).exists()
    assert result.receipt_path.exists()
    assert result.paths.baseline_file("transcript.md").exists()


def test_demo_markdown_has_story_sections(tmp_path: Path) -> None:
    md = render_demo_markdown(_run(tmp_path))
    for needle in (
        "# SPC Demonstration",
        "## 2. SPC builds semantic state",
        "JSON handoff",
        "follow-ups answered from state",
        "demo moment",
        "Scorecard",
        "spc-demo demo",
    ):
        assert needle in md


def test_demo_write_markdown_creates_file(tmp_path: Path) -> None:
    result = _run(tmp_path)
    path = write_demo_markdown(result)
    assert path.exists()
    assert path.name == "DEMO.md"
    assert "SPC Demonstration" in path.read_text(encoding="utf-8")


def test_demo_is_deterministic(tmp_path: Path) -> None:
    # Same root + run_id re-run must reproduce byte-identical output — the
    # project's core reproducibility invariant. (Paths embed the root, so this
    # is asserted for a stable location, as a real re-run would use.)
    a = render_demo_markdown(_run(tmp_path))
    b = render_demo_markdown(_run(tmp_path))
    assert a == b
