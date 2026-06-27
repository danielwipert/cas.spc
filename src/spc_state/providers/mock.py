"""`MockProvider` and canned completions for Phase 6.

The mock returns scripted raw strings — one per `complete()` call, repeating
the last when the script runs dry. The strings are built to land on each of
the three runtime outcomes the exit gate calls for:

- `build_valid_critic_payload`   → a clean `SemanticPatch` JSON → COMMIT
- `build_invalid_critic_payload` → references a ghost object   → REJECT
- `PROSE_RESPONSE`               → not JSON at all              → RETRY

A real LLM (Phase 7) replaces the script with an API call behind the same
`LLMProvider` seam.
"""

from __future__ import annotations

import datetime as dt

from ..models import (
    ModelFingerprint,
    PatchStatus,
    Priority,
    Question,
    QuestionStatus,
    Relation,
    SemanticPatch,
    SemanticState,
    TransformRecord,
)
from ..models.patch import AddObjects, UpdateObject
from ..models.transform import ConfidenceChange
from .base import LLMProvider, ProviderRequest, ProviderResponse

# A critic that finds claim_001 weak lowers its confidence to here.
_CRITIC_NEW_CONFIDENCE = 0.62


class MockProvider(LLMProvider):
    """Returns scripted completions, one per call (the last one repeats)."""

    def __init__(
        self,
        script: list[str],
        *,
        provider: str = "mock",
        model: str = "mock-critic-v0",
    ) -> None:
        if not script:
            raise ValueError("MockProvider needs at least one scripted completion.")
        self._script = list(script)
        self._calls = 0
        self.fingerprint = ModelFingerprint(provider=provider, model=model)

    def complete(self, request: ProviderRequest) -> ProviderResponse:
        text = self._script[min(self._calls, len(self._script) - 1)]
        self._calls += 1
        return ProviderResponse(text=text, fingerprint=self.fingerprint)

    @property
    def call_count(self) -> int:
        return self._calls


# ---------------------------------------------------------------------------
# Canned completions
# ---------------------------------------------------------------------------

PROSE_RESPONSE = (
    "The productivity claim looks weak to me: it leans on a single "
    "medium-reliability benchmark and an unproven transfer assumption. I would "
    "lower its confidence and open a question about architecture work."
)
"""A prose completion — no JSON, so L1 reports JSON_DECODE and the router RETRYs."""


def _critic_patch(
    state: SemanticState,
    *,
    now: dt.datetime,
    update_target: str,
    patch_id: str,
) -> SemanticPatch:
    """Build a critic patch lowering `update_target`'s confidence.

    With `update_target="claim_001"` the patch is valid; with a ghost id it
    fails L2 referential validation. The rest of the shape is identical.
    """
    current = state.claims.get("claim_001")
    from_conf = current.confidence if current is not None else 0.74
    reason = "Benchmark evidence is thin and the transfer assumption is unproven."

    update = UpdateObject.model_validate(
        {
            "object_id": update_target,
            "field": "confidence",
            "from": from_conf,
            "to": _CRITIC_NEW_CONFIDENCE,
            "reason": reason,
        }
    )
    question = Question(
        id="q_llm_001",
        text="Does the productivity evidence transfer to complex architecture work?",
        status=QuestionStatus.OPEN,
        priority=Priority.HIGH,
        linked_objects=["claim_001"],
        asked_by="transform_llm_critic_001",
    )
    relation = Relation(
        id="rel_llm_001",
        source="q_llm_001",
        predicate="questions",
        target="claim_001",
        confidence=1.0,
        created_by="transform_llm_critic_001",
    )
    transform_record = TransformRecord(
        id="transform_llm_critic_001",
        transform_type="critique",
        operator="llm_critic_transform",
        operator_version="llm_critic_transform@0.1.0",
        input_state_version=state.state_version,
        output_state_version=None,
        read_set=["claim_001"],
        write_set=[update_target, "q_llm_001", "rel_llm_001"],
        confidence_changes=[
            ConfidenceChange.model_validate(
                {
                    "object_id": update_target,
                    "from": from_conf,
                    "to": _CRITIC_NEW_CONFIDENCE,
                    "reason": reason,
                }
            )
        ],
        started_at=now,
        finished_at=now,
    )
    return SemanticPatch(
        patch_id=patch_id,
        base_state_id=state.state_id,
        base_state_version=state.state_version,
        proposed_by="llm_critic_transform@0.1.0",
        created_at=now,
        read_set=["claim_001"],
        add_objects=AddObjects(questions=[question]),
        update_objects=[update],
        add_relations=[relation],
        transform_record=transform_record,
        status=PatchStatus.PROPOSED,
    )


def build_valid_critic_payload(state: SemanticState, *, now: dt.datetime) -> str:
    """A clean critic patch (raw JSON) that validates and commits."""
    patch = _critic_patch(
        state, now=now, update_target="claim_001", patch_id="patch_llm_critic"
    )
    return patch.model_dump_json(by_alias=True)


def build_invalid_critic_payload(state: SemanticState, *, now: dt.datetime) -> str:
    """A critic patch that updates a ghost object — fails L2, so the router REJECTs."""
    patch = _critic_patch(
        state, now=now, update_target="claim_ghost", patch_id="patch_llm_critic_bad"
    )
    return patch.model_dump_json(by_alias=True)


__all__ = [
    "PROSE_RESPONSE",
    "MockProvider",
    "build_invalid_critic_payload",
    "build_valid_critic_payload",
]
