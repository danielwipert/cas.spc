"""Compose L1 + L2 into a single `ValidationReport`. See PILOT_SPEC.md §16."""

from __future__ import annotations

import datetime as dt
from typing import Any

from ..models import (
    RouterDecision,
    SemanticState,
    ValidationLayer,
    ValidationReport,
    ValidationSeverity,
)
from . import l1, l2


def validate(
    *,
    state: SemanticState,
    patch_payload: dict[str, Any] | str,
    report_id: str,
    now: dt.datetime,
) -> ValidationReport:
    """Run L1 and (if L1 passes) L2 against `(state, patch_payload)`.

    `patch_payload` may be a parsed dict or the raw string an LLM returned;
    L1 handles JSON decoding (and reports `L1.JSON_DECODE` on prose).

    The `suggested_decision` field is a first-cut recommendation:
    - any L1 error → REJECT
    - any L2 base-state mismatch or unresolved ref → REJECT
    - any L2 warning only → COMMIT (Phase 4+ may flip to REVIEW)
    - clean → COMMIT
    """
    patch, l1_issues = l1.parse_patch(patch_payload)
    issues = list(l1_issues)
    layers_run: list[ValidationLayer] = [ValidationLayer.L1_SCHEMA]

    if patch is not None:
        l2_issues = l2.validate_patch(state, patch)
        issues.extend(l2_issues)
        layers_run.append(ValidationLayer.L2_REFERENTIAL)

    suggested = _decide(issues)

    if patch is not None:
        patch_id = patch.patch_id
    elif isinstance(patch_payload, dict):
        patch_id = patch_payload.get("patch_id", "unknown_patch")
    else:
        # Raw, unparseable text (e.g. an LLM returned prose).
        patch_id = "unparsed_patch"

    return ValidationReport(
        report_id=report_id,
        patch_id=patch_id,
        base_state_id=state.state_id,
        base_state_version=state.state_version,
        generated_at=now,
        layers_run=layers_run,
        issues=issues,
        suggested_decision=suggested,
    )


def _decide(issues: list) -> RouterDecision:  # noqa: ARG001 — keep signature open
    has_error = any(i.severity == ValidationSeverity.ERROR for i in issues)
    if has_error:
        return RouterDecision.REJECT
    return RouterDecision.COMMIT


__all__ = ["validate"]
