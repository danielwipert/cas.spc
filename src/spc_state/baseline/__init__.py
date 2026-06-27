"""Phase 8 baseline: the competent JSON-handoff control (PILOT_SPEC.md §8.2)."""

from __future__ import annotations

from .pipeline import (
    FOLLOWUPS,
    MARKER,
    BaselineResult,
    BaselineStage,
    ClaimLineage,
    run_baseline,
)

__all__ = [
    "FOLLOWUPS",
    "MARKER",
    "BaselineResult",
    "BaselineStage",
    "ClaimLineage",
    "run_baseline",
]
