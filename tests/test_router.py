"""Router decision-table tests. See PILOT_SPEC.md §15.2."""

from __future__ import annotations

import datetime as dt

from spc_state.models import (
    RouterDecision,
    ValidationIssue,
    ValidationLayer,
    ValidationReport,
    ValidationSeverity,
)
from spc_state.router import decide

UTC = dt.timezone.utc


def _report(*issues: ValidationIssue) -> ValidationReport:
    return ValidationReport(
        report_id="report_test",
        patch_id="patch_test",
        base_state_id="sr_001",
        base_state_version=0,
        generated_at=dt.datetime(2026, 6, 26, tzinfo=UTC),
        layers_run=[ValidationLayer.L1_SCHEMA, ValidationLayer.L2_REFERENTIAL],
        issues=list(issues),
        suggested_decision=RouterDecision.COMMIT,
    )


def test_clean_report_commits() -> None:
    assert decide(_report()) is RouterDecision.COMMIT


def test_json_decode_failure_retries() -> None:
    issue = ValidationIssue(
        layer=ValidationLayer.L1_SCHEMA,
        severity=ValidationSeverity.ERROR,
        code="L1.JSON_DECODE",
        message="bad json",
    )
    assert decide(_report(issue)) is RouterDecision.RETRY


def test_other_l1_error_rejects() -> None:
    issue = ValidationIssue(
        layer=ValidationLayer.L1_SCHEMA,
        severity=ValidationSeverity.ERROR,
        code="L1.EXTRA_FORBIDDEN",
        message="extra field",
    )
    assert decide(_report(issue)) is RouterDecision.REJECT


def test_l2_error_rejects() -> None:
    issue = ValidationIssue(
        layer=ValidationLayer.L2_REFERENTIAL,
        severity=ValidationSeverity.ERROR,
        code="L2.UNRESOLVED_READ_SET_REF",
        message="missing ref",
    )
    assert decide(_report(issue)) is RouterDecision.REJECT


def test_only_warnings_still_commits() -> None:
    issue = ValidationIssue(
        layer=ValidationLayer.L2_REFERENTIAL,
        severity=ValidationSeverity.WARNING,
        code="L2.UNDECLARED_WRITE",
        message="undeclared write",
    )
    assert decide(_report(issue)) is RouterDecision.COMMIT
