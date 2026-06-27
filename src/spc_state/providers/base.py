"""Provider-agnostic LLM interface. See PILOT_SPEC.md §13.4 and Phases 6-7.

An `LLMProvider` is a thin seam between an operator and a model. The operator
turns its projection into a `ProviderRequest`; the provider returns a
`ProviderResponse` carrying the model's **raw** completion text plus a
`ModelFingerprint`. The provider does not parse, validate, or commit — the
runtime does. A completion may therefore be a well-formed `SemanticPatch`
JSON, an invalid one, or prose. That is the point: Phase 6 exercises the path
where a model returns something the runtime must reject or retry.

`MockProvider` (Phase 6) returns scripted completions. `AnthropicProvider`
and `OpenAIProvider` (Phase 7) wrap real APIs behind the same seam.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from pydantic import BaseModel, ConfigDict, Field

from ..models import ModelFingerprint


class ProviderRequest(BaseModel):
    """What an operator hands a provider: a prompt plus optional retry feedback.

    `feedback` carries the validation issues from a prior attempt so the
    provider (a real LLM, in Phase 7) can repair its output — the
    validation-feedback retry path of spec §15.6.
    """

    system: str = ""
    user: str
    feedback: list[str] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")


class ProviderResponse(BaseModel):
    """A provider's raw output. `text` is unparsed — it may not be a patch."""

    text: str
    fingerprint: ModelFingerprint

    model_config = ConfigDict(extra="forbid")


class LLMProvider(ABC):
    """The seam every model provider implements."""

    @abstractmethod
    def complete(self, request: ProviderRequest) -> ProviderResponse:
        """Return the model's raw completion for `request`."""


__all__ = ["LLMProvider", "ProviderRequest", "ProviderResponse"]
