"""Patch router. See PILOT_SPEC.md §15.2.

The router is intentionally thin: it takes a `ValidationReport` and returns
a final `RouterDecision`. The validator already attaches a
`suggested_decision`; the router exists as a separate step because in later
phases (L3 model review, L4 heuristics) the recommendation may be downgraded
to `REVIEW` even when L1/L2 pass.
"""

from __future__ import annotations

from ..models import (
    RouterDecision,
    ValidationLayer,
    ValidationReport,
    ValidationSeverity,
)


def decide(report: ValidationReport) -> RouterDecision:
    """Choose COMMIT / REVIEW / REJECT / RETRY for a validated patch.

    Phase 3 rules:
    - L1 JSON-decode failure → RETRY (operator may be able to repair).
    - Any other L1 error → REJECT.
    - Any L2 error → REJECT.
    - L2 warnings only → COMMIT (Phase 4+ may flip some to REVIEW).
    - No issues → COMMIT.
    """
    has_json_decode = any(i.code == "L1.JSON_DECODE" for i in report.issues)
    if has_json_decode:
        return RouterDecision.RETRY

    has_l1_error = any(
        i.layer == ValidationLayer.L1_SCHEMA and i.severity == ValidationSeverity.ERROR
        for i in report.issues
    )
    has_l2_error = any(
        i.layer == ValidationLayer.L2_REFERENTIAL and i.severity == ValidationSeverity.ERROR
        for i in report.issues
    )
    if has_l1_error or has_l2_error:
        return RouterDecision.REJECT

    return RouterDecision.COMMIT


__all__ = ["decide"]
