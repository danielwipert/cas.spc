"""`ReasoningReceipt` — human-readable projection of state history.

See PILOT_SPEC.md §18. The receipt is the pilot's primary output artifact.
It is **projected from actual state history**, not generated after the fact
(§18.3). Phase 2 ships the model; Phase 4 ships the projector and a
markdown renderer.
"""

from __future__ import annotations

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field


class ReceiptSummary(BaseModel):
    question: str
    answer: str

    model_config = ConfigDict(extra="forbid")


class ConfidenceMap(BaseModel):
    strongest_claims: list[str] = Field(default_factory=list)
    weakest_claims: list[str] = Field(default_factory=list)
    assumption_sensitive_claims: list[str] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")


class ReceiptAudit(BaseModel):
    committed_patches: list[str] = Field(default_factory=list)
    reviewed_patches: list[str] = Field(default_factory=list)
    rejected_patches: list[str] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")


class ReasoningReceipt(BaseModel):
    receipt_id: str
    state_id: str
    state_version: int = Field(ge=0)
    generated_at: AwareDatetime

    summary: ReceiptSummary

    claims_produced: list[str] = Field(default_factory=list)
    evidence_used: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    contradictions: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)

    transform_history: list[str] = Field(default_factory=list)
    confidence_map: ConfidenceMap = Field(default_factory=ConfidenceMap)
    audit: ReceiptAudit = Field(default_factory=ReceiptAudit)

    model_config = ConfigDict(extra="forbid")


__all__ = [
    "ConfidenceMap",
    "ReasoningReceipt",
    "ReceiptAudit",
    "ReceiptSummary",
]
