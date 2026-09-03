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
from spc_state.router import decide, decide_llm

UTC = dt.UTC


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


# ---------------------------------------------------------------------------
# `decide_llm` — routing for model-produced patches (spec §15.6).
#
# A model can repair its own output, so *any* L1 schema failure is a shape it
# can be asked to fix, not just a JSON decode error. L2 failures still reject:
# the patch is well-formed but says something untrue about the state.
# ---------------------------------------------------------------------------


def test_llm_clean_report_commits() -> None:
    assert decide_llm(_report()) is RouterDecision.COMMIT


def test_llm_json_decode_failure_retries() -> None:
    issue = ValidationIssue(
        layer=ValidationLayer.L1_SCHEMA,
        severity=ValidationSeverity.ERROR,
        code="L1.JSON_DECODE",
        message="bad json",
    )
    assert decide_llm(_report(issue)) is RouterDecision.RETRY


def test_llm_shape_invalid_output_retries_instead_of_rejecting() -> None:
    """The planner fix: valid JSON in the wrong shape is repairable."""
    issue = ValidationIssue(
        layer=ValidationLayer.L1_SCHEMA,
        severity=ValidationSeverity.ERROR,
        code="L1.MISSING",
        message="Field required",
    )
    assert decide(_report(issue)) is RouterDecision.REJECT  # deterministic path
    assert decide_llm(_report(issue)) is RouterDecision.RETRY  # LLM path


def test_llm_l2_error_still_rejects() -> None:
    """A referential error is a judgement to reject, not a shape to repair."""
    issue = ValidationIssue(
        layer=ValidationLayer.L2_REFERENTIAL,
        severity=ValidationSeverity.ERROR,
        code="L2.UNRESOLVED_UPDATE_TARGET",
        message="claim_ghost does not exist",
    )
    assert decide_llm(_report(issue)) is RouterDecision.REJECT


def test_llm_l1_error_wins_over_an_l2_error() -> None:
    """Malformed output is worth another attempt even if L2 also complained."""
    l1 = ValidationIssue(
        layer=ValidationLayer.L1_SCHEMA,
        severity=ValidationSeverity.ERROR,
        code="L1.MISSING",
        message="Field required",
    )
    l2 = ValidationIssue(
        layer=ValidationLayer.L2_REFERENTIAL,
        severity=ValidationSeverity.ERROR,
        code="L2.UNRESOLVED_UPDATE_TARGET",
        message="claim_ghost does not exist",
    )
    assert decide_llm(_report(l1, l2)) is RouterDecision.RETRY


def test_llm_warnings_still_commit() -> None:
    issue = ValidationIssue(
        layer=ValidationLayer.L2_REFERENTIAL,
        severity=ValidationSeverity.WARNING,
        code="L2.MISSING_PROVENANCE",
        message="no evidence",
    )
    assert decide_llm(_report(issue)) is RouterDecision.COMMIT
