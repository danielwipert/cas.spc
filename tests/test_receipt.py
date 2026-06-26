"""Phase 4 — Reasoning Receipt projection + Markdown snapshot.

The receipt is a projection from state history (spec §18.3): these tests
assert it reads the right ids out of the final state, and lock the rendered
Markdown with a byte-exact snapshot fixture.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

from spc_state.models import ReasoningReceipt, SemanticState
from spc_state.receipt import (
    NO_RECOMMENDATION,
    derive_summary,
    project_receipt,
    render_markdown,
    write_run_artifacts,
)
from spc_state.receipt.artifacts import build_diffs
from spc_state.store import RunPaths

UTC = dt.UTC
GEN_AT = dt.datetime(2026, 6, 26, 0, 30, 0, tzinfo=UTC)
FIXTURE = Path(__file__).resolve().parent / "fixtures" / "reasoning_receipt_demo.md"


def _project(final: SemanticState) -> ReasoningReceipt:
    return project_receipt(
        final_state=final,
        receipt_id="rr_001",
        generated_at=GEN_AT,
        question="Should the company adopt an AI coding assistant?",
    )


def test_receipt_projects_objects_from_final_state(
    demo_history: list[SemanticState],
) -> None:
    receipt = _project(demo_history[-1])

    assert receipt.state_version == 3
    assert receipt.claims_produced == ["claim_001", "claim_002", "claim_003"]
    assert receipt.evidence_used == ["ev_001", "ev_002", "ev_003"]
    assert receipt.assumptions == ["assumption_001"]
    assert receipt.contradictions == []
    assert receipt.open_questions == ["q_001", "q_002"]
    assert receipt.transform_history == [
        "transform_extract_001",
        "transform_planner_001",
        "transform_critic_001",
    ]
    assert receipt.audit.committed_patches == ["patch_001", "patch_002", "patch_003"]
    assert receipt.audit.rejected_patches == []


def test_confidence_map_splits_strong_weak_and_sensitive(
    demo_history: list[SemanticState],
) -> None:
    cmap = _project(demo_history[-1]).confidence_map
    assert cmap.strongest_claims == ["claim_002", "claim_003"]
    assert cmap.weakest_claims == ["claim_001"]
    # claim_001 depends on the (high-impact) benchmark-transfer assumption.
    assert cmap.assumption_sensitive_claims == ["claim_001"]


def test_summary_answer_is_the_leading_hypothesis(
    demo_history: list[SemanticState],
) -> None:
    summary = derive_summary(demo_history[-1])
    assert "pilot" in summary.answer.lower()
    assert summary.answer != NO_RECOMMENDATION


def test_summary_falls_back_when_no_hypothesis(
    demo_history: list[SemanticState],
) -> None:
    # v1 (post-extract) has no hypothesis yet.
    summary = derive_summary(demo_history[1])
    assert summary.answer == NO_RECOMMENDATION


def test_rendered_markdown_matches_snapshot(
    demo_history: list[SemanticState],
) -> None:
    final = demo_history[-1]
    receipt = _project(final)
    md = render_markdown(receipt, final, diffs=build_diffs(demo_history))
    expected = FIXTURE.read_text(encoding="utf-8")
    assert md + "\n" == expected


def test_write_run_artifacts_persists_receipt_and_diffs(
    demo_run: tuple[RunPaths, list[SemanticState]],
) -> None:
    paths, states = demo_run
    artifacts = write_run_artifacts(
        paths, states, generated_at=GEN_AT, question="x?"
    )

    assert artifacts.receipt_path.exists()
    assert artifacts.receipt_path == paths.receipt_file(3)
    # One diff per version transition: v0->v1, v1->v2, v2->v3.
    assert len(artifacts.diffs) == 3
    assert all(p.exists() for p in artifacts.diff_paths)
    assert paths.diff_file(2, 3).exists()


def test_artifacts_are_byte_reproducible(tmp_path: Path) -> None:
    from tests._demo_helpers import run_demo

    pa, sa = run_demo(tmp_path / "a", "run_a")
    pb, sb = run_demo(tmp_path / "b", "run_b")
    a = write_run_artifacts(pa, sa, generated_at=GEN_AT)
    b = write_run_artifacts(pb, sb, generated_at=GEN_AT)
    assert a.receipt_path.read_bytes() == b.receipt_path.read_bytes()
    for da, db in zip(a.diff_paths, b.diff_paths, strict=True):
        assert da.read_bytes() == db.read_bytes()
