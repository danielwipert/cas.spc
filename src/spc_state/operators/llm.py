"""LLM-backed operators. See PILOT_SPEC.md §13.4 and Phase 6.

A deterministic operator builds its patch in Python and the runtime commits
it in one shot. An `LLMOperator` instead delegates patch *generation* to an
`LLMProvider`, which may return prose or an invalid patch. The runtime, not
the operator, decides what happens: it drives `generate()` in a
validation-feedback retry loop (spec §15.6) and routes COMMIT / REJECT /
RETRY. The operator never mutates state — it only turns its projection (and
any prior validation feedback) into a `ProviderRequest`.

Phase 6 ships `MockLLMCriticOperator`, backed by `MockProvider`. Phase 7
swaps in a live provider behind the same interface.
"""

from __future__ import annotations

from abc import abstractmethod

from ..models import Perspective, Projection, SemanticPatch, SemanticState
from ..projection import ProjectionView, resolve_view
from ..providers import LLMProvider, ProviderRequest, ProviderResponse
from .base import Operator


class MalformedPatchError(RuntimeError):
    """Raised when an LLM operator's single-shot `propose` cannot be parsed.

    The runtime does not rely on this — it drives `generate()` and lets the
    validator surface the problem. `propose` exists only as a convenience for
    callers that want a one-shot, parse-or-raise path.
    """


class LLMOperator(Operator):
    """An operator whose patches come from an `LLMProvider`."""

    #: Hard cap on attempts the runtime makes per step (spec §15.6 retry loop).
    max_attempts: int = 3

    def __init__(self, provider: LLMProvider, *, max_attempts: int = 3) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be at least 1.")
        self.provider = provider
        self.max_attempts = max_attempts

    @abstractmethod
    def build_request(
        self, view: ProjectionView, feedback: list[str]
    ) -> ProviderRequest:
        """Turn the operator's projection slice (+ retry feedback) into a prompt."""

    def generate(
        self,
        state: SemanticState,
        projection: Projection,
        feedback: list[str],
    ) -> ProviderResponse:
        """Resolve the projection to its slice and ask the provider for a patch."""
        view = resolve_view(projection, state)
        return self.provider.complete(self.build_request(view, feedback))

    def propose(self, state: SemanticState, projection: Projection) -> SemanticPatch:
        """Single-shot, no-retry convenience. The runtime uses `generate`."""
        response = self.generate(state, projection, [])
        try:
            return SemanticPatch.model_validate_json(response.text)
        except ValueError as exc:  # pydantic ValidationError / JSON error
            raise MalformedPatchError(
                f"{self.name} produced output that is not a SemanticPatch."
            ) from exc


class LLMCriticOperator(LLMOperator):
    """A critic whose patches come from any `LLMProvider`. See spec §13.4.

    Provider-agnostic: Phase 6 drives it with `MockProvider`, Phase 7 with
    `OpenRouterProvider`. The operator only turns its critic projection slice
    (plus retry feedback) into a prompt — the runtime validates and commits.
    """

    name = "llm_critic_transform"
    version = "0.1.0"
    perspective = Perspective.CRITIC
    goal = "Identify weak claims, missing assumptions, and unresolved tensions."

    def build_request(
        self, view: ProjectionView, feedback: list[str]
    ) -> ProviderRequest:
        weak_claims = ", ".join(sorted(view.claims)) or "(none)"
        user = (
            "You are critiquing a shared semantic state. The weak claims in "
            f"your projection are: {weak_claims}. Propose a SemanticPatch (JSON) "
            "that lowers unsupported confidence and opens questions. Return only "
            "the patch as a single JSON object."
        )
        return ProviderRequest(
            system="You are a rigorous critic. Emit a SemanticPatch, never prose.",
            user=user,
            feedback=feedback,
        )


#: Back-compat alias — Phase 6 introduced this under the "Mock" name before the
#: operator was generalised to any provider in Phase 7.
MockLLMCriticOperator = LLMCriticOperator


__all__ = [
    "LLMCriticOperator",
    "LLMOperator",
    "MalformedPatchError",
    "MockLLMCriticOperator",
]
