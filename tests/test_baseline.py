"""Phase 8 baseline (JSON-handoff control) tests — PILOT_SPEC.md §8.2."""

from __future__ import annotations

import pytest

from spc_state.baseline import run_baseline
from tests._demo_helpers import read_example


def test_baseline_produces_three_stages() -> None:
    result = run_baseline(read_example())
    assert [s.name for s in result.stages] == ["summary", "critique", "memo"]
    assert "summary" in result.summary
    assert "concerns" in result.critique
    assert "recommendation" in result.memo


def test_baseline_rereads_full_document_each_stage() -> None:
    result = run_baseline(read_example())
    # The competent stateless chain re-reads the document at every hop.
    assert result.full_document_reingestions == 3
    assert all(s.full_document_reingested for s in result.stages)
    # Each later stage ingests strictly more (document + accumulated JSON).
    ingested = [s.ingested_tokens for s in result.stages]
    assert ingested == sorted(ingested)
    assert ingested[0] < ingested[-1]


def test_baseline_claim_drift_is_unanchored() -> None:
    result = run_baseline(read_example())
    assert len(result.claim_lineages) == 1
    lineage = result.claim_lineages[0]
    # The productivity claim is reworded twice with no evidence anchor.
    assert lineage.mutations == 2
    assert lineage.carried_evidence is False


def test_baseline_token_accounting_positive() -> None:
    result = run_baseline(read_example())
    assert result.document_tokens > 0
    assert result.transcript_tokens > 0
    assert result.total_ingested_tokens >= result.document_tokens * 3


def test_baseline_transcript_markdown_lists_stages() -> None:
    md = run_baseline(read_example()).transcript_markdown()
    for stage in ("summary", "critique", "memo"):
        assert f"## Stage: {stage}" in md


def test_baseline_rejects_unknown_document() -> None:
    with pytest.raises(NotImplementedError):
        run_baseline("An unrelated paragraph about gardening.")
