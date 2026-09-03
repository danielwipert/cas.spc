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


class TokenUsage(BaseModel):
    """Tokens spent producing a patch (T5). Real API usage when a provider
    reports it (OpenRouter); a deterministic estimate (`tokens.py`) otherwise
    — either way this is what a `CostLedger` sums, never re-measured itself.
    """

    prompt_tokens: int = Field(ge=0)
    completion_tokens: int = Field(ge=0)

    model_config = ConfigDict(extra="forbid")

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


def sum_token_usage(a: TokenUsage | None, b: TokenUsage | None) -> TokenUsage | None:
    """Combine two calls' usage — e.g. two retry attempts, or a two-pass
    operator's detection + verification calls — into one total. Each is a
    real, separately billed API call, so the sum (not the last one) is what
    a `TransformRecord` should carry.
    """
    if a is None:
        return b
    if b is None:
        return a
    return TokenUsage(
        prompt_tokens=a.prompt_tokens + b.prompt_tokens,
        completion_tokens=a.completion_tokens + b.completion_tokens,
    )


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
    token_usage: TokenUsage | None = None
    started_at: AwareDatetime | None = None
    finished_at: AwareDatetime | None = None
    notes: str | None = None

    model_config = ConfigDict(extra="forbid")


__all__ = [
    "ConfidenceChange",
    "ModelFingerprint",
    "TokenUsage",
    "TransformRecord",
    "sum_token_usage",
]
