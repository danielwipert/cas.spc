"""L1 — deterministic schema validation. See PILOT_SPEC.md §16.1.

L1 takes a raw dict (or JSON string) and tries to parse it into a
`SemanticPatch`. Any Pydantic `ValidationError` becomes a list of
`ValidationIssue`s. If the dict already parsed cleanly, L1 returns an empty
issue list — the patch passed schema-level checks.
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import ValidationError

from ..models import (
    SemanticPatch,
    ValidationIssue,
    ValidationLayer,
    ValidationSeverity,
)


def parse_patch(payload: dict[str, Any] | str) -> tuple[SemanticPatch | None, list[ValidationIssue]]:
    """Parse a raw patch payload into a `SemanticPatch` or L1 issues."""
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError as e:
            return None, [
                ValidationIssue(
                    layer=ValidationLayer.L1_SCHEMA,
                    severity=ValidationSeverity.ERROR,
                    code="L1.JSON_DECODE",
                    message=f"Could not parse patch JSON: {e}",
                )
            ]
    try:
        patch = SemanticPatch.model_validate(payload)
    except ValidationError as e:
        return None, [_issue_from_pydantic_error(err) for err in e.errors()]
    return patch, []


def _issue_from_pydantic_error(err: dict[str, Any]) -> ValidationIssue:
    loc = ".".join(str(x) for x in err.get("loc", ()))
    return ValidationIssue(
        layer=ValidationLayer.L1_SCHEMA,
        severity=ValidationSeverity.ERROR,
        code=f"L1.{err.get('type', 'UNKNOWN').upper()}",
        message=err.get("msg", ""),
        field=loc or None,
    )


__all__ = ["parse_patch"]
