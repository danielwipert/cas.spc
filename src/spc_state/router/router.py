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


def decide_llm(report: ValidationReport) -> RouterDecision:
    """Choose an outcome for a *model-produced* patch (spec §15.6).

    Same table as `decide`, with one difference: a model can be asked to
    repair its own output, so **any** L1 schema failure is RETRY, not just a
    JSON decode error. Wrong-shape output is a shape the operator can ask for
    again; for a deterministic operator the same failure is a code bug, which
    is why `decide` still rejects it.

    L2 is untouched. A referentially invalid patch is well-formed but says
    something untrue about the state — a judgement to reject, not a shape to
    fix — so it rejects on both paths.
    """
    has_l1_error = any(
        i.layer == ValidationLayer.L1_SCHEMA and i.severity == ValidationSeverity.ERROR
        for i in report.issues
    )
    if has_l1_error:
        return RouterDecision.RETRY
    # With no L1 error left to repair, the shared table decides: L2 errors
    # reject, warnings and a clean report commit.
    return decide(report)


__all__ = ["decide", "decide_llm"]
