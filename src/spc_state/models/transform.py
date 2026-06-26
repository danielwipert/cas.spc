"""TransformRecord and ModelFingerprint.

See PILOT_SPEC.md §10.6. A `TransformRecord` is the durable receipt of what
an operator did: which projection it read, what objects it wrote, which
state version it acted on, and (for live LLM operators) which model produced
the patch.
"""

from __future__ import annotations

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field


class ModelFingerprint(BaseModel):
    """Identifies the LLM that produced a patch (Phase 7+)."""

    provider: str
    model: str
    model_version: str | None = None
    sampling: dict[str, float | int | str | bool] = Field(default_factory=dict)

    model_config = ConfigDict(extra="forbid")


class ConfidenceChange(BaseModel):
    """A logged confidence delta on a single object."""

    object_id: str
    from_value: float = Field(alias="from", ge=0.0, le=1.0)
    to_value: float = Field(alias="to", ge=0.0, le=1.0)
    reason: str | None = None

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class TransformRecord(BaseModel):
    """A durable record of an operator invocation. See spec §10.6."""

    id: str
    transform_type: str
    operator: str
    operator_version: str
    input_state_version: int = Field(ge=0)
    output_state_version: int | None = Field(default=None, ge=0)
    read_set: list[str] = Field(default_factory=list)
    write_set: list[str] = Field(default_factory=list)
    confidence_changes: list[ConfidenceChange] = Field(default_factory=list)
    model_fingerprint: ModelFingerprint | None = None
    started_at: AwareDatetime | None = None
    finished_at: AwareDatetime | None = None
    notes: str | None = None

    model_config = ConfigDict(extra="forbid")


__all__ = ["ConfidenceChange", "ModelFingerprint", "TransformRecord"]
