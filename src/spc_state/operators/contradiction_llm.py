"""LLM-backed contradiction detection (spec §11.5, §20.5).

Whether two committed claims genuinely *conflict* is a semantic judgement, not
a structural read — so unlike the Retriever this operator is LLM-backed. It
reads the verifier projection (all active claims), asks a model for conflicting
pairs, and assembles first-class `Contradiction` objects committed with status
`unresolved`. That is what "preserve conflicts as objects, routed for review"
means here: the conflict becomes a queryable object whose unresolved status is
the standing review flag (the §20.5 metric counts these).

Like every assembling LLM operator, the model supplies content (which pairs
conflict and why) and the operator owns the bookkeeping (ids, dedup, validity).
It references only existing claim ids, skips self-pairs, and never re-adds a
contradiction already in state. It never mutates state.
"""

from __future__ import annotations

from typing import Any

from ..models import (
    Contradiction,
    ContradictionStatus,
    ContradictionType,
    PatchStatus,
    Perspective,
    Projection,
    SemanticPatch,
    SemanticState,
    Severity,
    TransformRecord,
)
from ..models.patch import AddObjects
from ..projection import ProjectionView, resolve_view
from ..providers import LLMProvider, ProviderRequest, ProviderResponse
from ..runtime.clock import Clock, WallClock
from ._assembly import LLMAssemblyError, coerce_enum, load_json
from .llm import LLMOperator

_TYPES = {t.value: t for t in ContradictionType} | {
    "factual": ContradictionType.FACTUAL_CONFLICT,
    "conflict": ContradictionType.FACTUAL_CONFLICT,
    "scope": ContradictionType.SCOPE_MISMATCH,
    "temporal": ContradictionType.TEMPORAL_CONFLICT,
}
_SEVERITIES = {s.value: s for s in Severity}

_SCHEMA_HINT = """Return ONLY a single JSON object of this exact shape:

{
  "contradictions": [
    {
      "claim_a": "claim_001",
      "claim_b": "claim_004",
      "type": "factual_conflict | tension | scope_mismatch | temporal_conflict",
      "severity": "low | medium | high",
      "resolution_options": ["one way to resolve it", "another"]
    }
  ]
}

Rules:
- Reference only the claim_* ids listed above; never the same id twice.
- Report a pair only if the claims genuinely cannot both hold as stated.
- If there are no real contradictions, return {"contradictions": []}.
- No prose, no markdown fences — only the JSON object."""


def _pair_key(a: str, b: str) -> tuple[str, str]:
    return (a, b) if a <= b else (b, a)


class LLMContradictionOperator(LLMOperator):
    """Detect conflicting claim pairs and commit them as Contradiction objects."""

    name = "contradiction_transform"
    version = "0.1.0"
    perspective = Perspective.VERIFIER
    goal = "Detect claims that cannot both hold and record them as contradictions."

    def __init__(
        self,
        provider: LLMProvider,
        *,
        clock: Clock | None = None,
        max_attempts: int = 3,
        patch_id: str = "patch_005",
        transform_id: str = "transform_contradiction_001",
    ) -> None:
        super().__init__(provider, max_attempts=max_attempts)
        self.clock = clock or WallClock()
        self.patch_id = patch_id
        self.transform_id = transform_id

    def build_request(
        self, view: ProjectionView, feedback: list[str]
    ) -> ProviderRequest:
        claims = "\n".join(
            f"- {cid}: {c.text}" for cid, c in sorted(view.claims.items())
        ) or "(none)"
        user = (
            "Find pairs of claims that cannot both be true as stated.\n\n"
            f"CLAIMS:\n{claims}\n\n{_SCHEMA_HINT}"
        )
        return ProviderRequest(
            system=(
                "You verify a shared semantic state for internal conflicts. "
                "Emit only the requested JSON, referencing existing claim ids."
            ),
            user=user,
            feedback=feedback,
        )

    def generate(
        self,
        state: SemanticState,
        projection: Projection,
        feedback: list[str],
    ) -> ProviderResponse:
        view = resolve_view(projection, state)
        response = self.provider.complete(self.build_request(view, feedback))
        try:
            patch = self._assemble(state, view, response.text)
            text = patch.model_dump_json(by_alias=True)
        except LLMAssemblyError:
            text = response.text
        return ProviderResponse(text=text, fingerprint=response.fingerprint)

    def _assemble(
        self, state: SemanticState, view: ProjectionView, raw: str
    ) -> SemanticPatch:
        data = load_json(raw)
        if isinstance(data, dict) and ("add_objects" in data or "patch_id" in data):
            return SemanticPatch.model_validate(data)
        if not isinstance(data, dict):
            raise LLMAssemblyError("Expected a JSON object.")

        # Pairs already recorded, so we never duplicate an existing conflict.
        seen: set[tuple[str, str]] = {
            _pair_key(k.claim_a, k.claim_b) for k in state.contradictions.values()
        }
        now = self.clock.now()
        contradictions: list[Contradiction] = []
        write_set: list[str] = []

        for item in _as_dict_list(data.get("contradictions")):
            a = item.get("claim_a")
            b = item.get("claim_b")
            if not (isinstance(a, str) and isinstance(b, str)) or a == b:
                continue
            if a not in view.claims or b not in view.claims:
                continue
            key = _pair_key(a, b)
            if key in seen:
                continue
            seen.add(key)
            options = [o for o in item.get("resolution_options", []) if isinstance(o, str)]
            cid = f"contradiction_{len(contradictions) + 1:03d}"
            contradictions.append(
                Contradiction(
                    id=cid,
                    claim_a=a,
                    claim_b=b,
                    contradiction_type=coerce_enum(
                        item.get("type"), _TYPES, ContradictionType.TENSION
                    ),
                    severity=coerce_enum(item.get("severity"), _SEVERITIES, Severity.MEDIUM),
                    status=ContradictionStatus.UNRESOLVED,
                    resolution_options=options,
                    detected_by=self.transform_id,
                )
            )
            write_set.append(cid)

        read_set = sorted(view.claims)
        transform_record = TransformRecord(
            id=self.transform_id,
            transform_type="verify",
            operator=self.name,
            operator_version=self.fully_qualified(),
            input_state_version=state.state_version,
            output_state_version=None,
            read_set=read_set,
            write_set=write_set,
            confidence_changes=[],
            started_at=now,
            finished_at=now,
            notes=f"Detected {len(contradictions)} contradiction(s).",
        )
        return SemanticPatch(
            patch_id=self.patch_id,
            base_state_id=state.state_id,
            base_state_version=state.state_version,
            proposed_by=self.fully_qualified(),
            created_at=now,
            read_set=read_set,
            add_objects=AddObjects(contradictions=contradictions),
            transform_record=transform_record,
            status=PatchStatus.PROPOSED,
        )


def _as_dict_list(value: Any) -> list[dict[str, Any]]:
    return [v for v in value if isinstance(v, dict)] if isinstance(value, list) else []


__all__ = ["LLMContradictionOperator"]
