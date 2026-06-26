"""Build and persist Phase 4 run artifacts: state diffs + Reasoning Receipt.

Given the committed state history of a run, this:
- diffs each version transition (`vN → vN+1`) and writes each to `diffs/`,
- projects a `ReasoningReceipt` from the final state,
- renders it to Markdown (with the diffs inlined) and writes it to `receipts/`.

Kept separate from the Phase 3 runtime so the deterministic patch-loop and its
byte-reproducibility tests are untouched. Output here is itself deterministic:
a `FixedClock` `generated_at` plus sorted diffs yield identical bytes per run.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from pathlib import Path

from ..diff import StateDiff, diff_states
from ..models import ReasoningReceipt, SemanticState
from ..store import DiffStore, ReceiptStore, RunPaths
from .project import project_receipt
from .render import render_markdown


@dataclass
class ReceiptArtifacts:
    receipt: ReasoningReceipt
    markdown: str
    diffs: list[StateDiff]
    receipt_path: Path
    diff_paths: list[Path]


def build_diffs(states: list[SemanticState]) -> list[StateDiff]:
    """Diff each consecutive version transition, in version order."""
    ordered = sorted(states, key=lambda s: s.state_version)
    return [
        diff_states(ordered[i], ordered[i + 1]) for i in range(len(ordered) - 1)
    ]


def write_run_artifacts(
    paths: RunPaths,
    states: list[SemanticState],
    *,
    generated_at: dt.datetime,
    receipt_id: str = "rr_001",
    question: str | None = None,
) -> ReceiptArtifacts:
    """Project + render + persist diffs and the Reasoning Receipt for a run."""
    if not states:
        raise ValueError("write_run_artifacts needs at least one state version.")

    paths.ensure_dirs()
    final_state = max(states, key=lambda s: s.state_version)

    diffs = build_diffs(states)
    diff_store = DiffStore(paths)
    diff_paths = [diff_store.write(d) for d in diffs]

    receipt = project_receipt(
        final_state=final_state,
        receipt_id=receipt_id,
        generated_at=generated_at,
        question=question,
    )
    markdown = render_markdown(receipt, final_state, diffs=diffs)
    receipt_path = ReceiptStore(paths).write(final_state.state_version, markdown)

    return ReceiptArtifacts(
        receipt=receipt,
        markdown=markdown,
        diffs=diffs,
        receipt_path=receipt_path,
        diff_paths=diff_paths,
    )


__all__ = ["ReceiptArtifacts", "build_diffs", "write_run_artifacts"]
