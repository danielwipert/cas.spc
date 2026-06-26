"""ReasoningReceipt projector, Markdown renderer, and §8.4 follow-ups.

See PILOT_SPEC.md §18. The receipt is a projection from actual state history
(§18.3), not an after-the-fact explanation.
"""

from .artifacts import ReceiptArtifacts, build_diffs, write_run_artifacts
from .followups import (
    AssumptionImpact,
    AssumptionSensitivity,
    DependencyAnswer,
    DiffAnswer,
    FollowUps,
    OperatorContribution,
    QuestionList,
    RankedClaims,
    SourceSupport,
)
from .project import (
    NO_RECOMMENDATION,
    STRONG_CONFIDENCE,
    WEAK_CONFIDENCE,
    derive_summary,
    project_receipt,
)
from .render import render_markdown

__all__ = [
    "NO_RECOMMENDATION",
    "STRONG_CONFIDENCE",
    "WEAK_CONFIDENCE",
    "AssumptionImpact",
    "AssumptionSensitivity",
    "DependencyAnswer",
    "DiffAnswer",
    "FollowUps",
    "OperatorContribution",
    "QuestionList",
    "RankedClaims",
    "ReceiptArtifacts",
    "SourceSupport",
    "build_diffs",
    "derive_summary",
    "project_receipt",
    "render_markdown",
    "write_run_artifacts",
]
