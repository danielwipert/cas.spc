"""Phase 8 evaluation: §20 metrics, pilot report, and the §8.5 demo moment."""

from __future__ import annotations

from ..tokens import estimate_tokens
from .metrics import DemoMoment, EvaluationReport, MetricResult, evaluate
from .report import render_markdown, write_report

__all__ = [
    "DemoMoment",
    "EvaluationReport",
    "MetricResult",
    "estimate_tokens",
    "evaluate",
    "render_markdown",
    "write_report",
]
