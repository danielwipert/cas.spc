"""`ValidationReport` — the runtime's verdict on a single patch.

See PILOT_SPEC.md §16. The report records every issue across the four
validation layers and the suggested router decision. The router (§15.2)
consumes the report; the patch is never committed without one.
"""

from __future__ import annotations

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from .enums import RouterDecision, ValidationLayer, ValidationSeverity


class ValidationIssue(BaseModel):
    layer: ValidationLayer
    severity: ValidationSeverity
    code: str
    message: str
    object_id: str | None = None
    field: str | None = None

    model_config = ConfigDict(extra="forbid")


class ValidationReport(BaseModel):
    report_id: str
    patch_id: str
    base_state_id: str
    base_state_version: int = Field(ge=0)
    generated_at: AwareDatetime

    layers_run: list[ValidationLayer] = Field(default_factory=list)
    issues: list[ValidationIssue] = Field(default_factory=list)
    suggested_decision: RouterDecision

    model_config = ConfigDict(extra="forbid")

    def has_errors(self) -> bool:
        return any(i.severity == ValidationSeverity.ERROR for i in self.issues)

    def has_warnings(self) -> bool:
        return any(i.severity == ValidationSeverity.WARNING for i in self.issues)


__all__ = ["ValidationIssue", "ValidationReport"]
