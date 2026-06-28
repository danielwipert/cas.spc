"""LLM-backed contradiction detection (spec §11.5, §20.5).

Whether two committed claims genuinely *conflict* is a semantic judgement, not
a structural read — so unlike the Retriever this operator is LLM-backed. It
reads the verifier projection (all active claims), asks a model for conflicting
pairs, and assembles first-class `Contradiction` objects committed with status
`unresolved`. That is what "preserve conflicts as objects, routed for review"
means here: the conflict becomes a queryable object whose unresolved status is
the standing review flag (the §20.5 metric counts these).

Detection runs in **two passes** to control precision. A single detection pass
is too eager — it flags claims that merely sit in tension or that both support
the same conclusion. So a first call proposes candidate pairs (each with a
one-sentence justification, which is gated), and a second *adversarial* call
plays skeptic: its default is that two claims can coexist, and it keeps only
pairs that are genuinely impossible together. This kills false positives (e.g.
two separate pro-X rulings are not a contradiction) without losing real ones
(e.g. "revenue rose" vs "revenue fell").

Like every assembling LLM operator, the model supplies content and the operator
owns the bookkeeping (ids, dedup, validity). It references only existing claim
ids, skips self-pairs, and never re-adds a contradiction already in state. It
never mutates state.
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

_MIN_CONFLICT_LEN = 12

_SCHEMA_HINT = """A contradiction is two claims that CANNOT BOTH BE TRUE at the
same time, in the same sense — one asserts something the other denies, or they
give opposite or incompatible facts about the SAME thing (e.g. "revenue rose"
vs "revenue fell" in the same quarter).

Do NOT report a pair when:
- the claims are about different subjects or topics;
- both claims can comfortably be true together (even if they feel opposed or
  sit in tension);
- both claims support the same overall conclusion — two separate examples of
  the same point are NOT a contradiction;
- one claim is merely an example, a cause, or an elaboration of the other.

Return ONLY a single JSON object of this exact shape:

{
  "contradictions": [
    {
      "claim_a": "claim_001",
      "claim_b": "claim_004",
      "conflict": "one sentence: precisely why these two cannot both be true",
      "type": "factual_conflict | tension | scope_mismatch | temporal_conflict",
      "severity": "low | medium | high",
      "resolution_options": ["one way to resolve it", "another"]
    }
  ]
}

Rules:
- Reference only the claim_* ids listed above; never the same id twice.
- Fill `conflict` with the specific incompatibility. If you cannot state a real
  incompatibility in one sentence, the pair is NOT a contradiction — omit it.
- When in doubt, omit. A false contradiction is worse than a missed one.
- If there are no genuine contradictions, return {"contradictions": []}.
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
                "You verify a shared semantic state for genuine internal "
                "conflicts. A contradiction means two claims cannot both be "
                "true; statements that merely feel opposed, or that both "
                "support the same conclusion, are NOT contradictions. Prefer "
                "reporting none over reporting a weak one. Emit only the "
                "requested JSON, referencing existing claim ids."
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
            data = load_json(response.text)
        except LLMAssemblyError:
            return ProviderResponse(text=response.text, fingerprint=response.fingerprint)
        # If the model already emitted a full patch, let the runtime judge it.
        if isinstance(data, dict) and ("add_objects" in data or "patch_id" in data):
            return ProviderResponse(text=response.text, fingerprint=response.fingerprint)
        if not isinstance(data, dict):
            return ProviderResponse(text=response.text, fingerprint=response.fingerprint)

        candidates = self._candidates(state, view, data)
        # Adversarial second pass: a skeptic that defaults to "they can coexist"
        # keeps only pairs that are genuinely impossible together. This is the
        # precision gate that a single detection pass cannot enforce on its own.
        if candidates:
            candidates = self._verify(view, candidates)
        patch = self._build_patch(state, view, candidates)
        return ProviderResponse(
            text=patch.model_dump_json(by_alias=True), fingerprint=response.fingerprint
        )

    def _candidates(
        self, state: SemanticState, view: ProjectionView, data: dict[str, Any]
    ) -> list[dict[str, Any]]:
        """Filter the model's proposed pairs: valid ids, distinct, justified, new."""
        seen: set[tuple[str, str]] = {
            _pair_key(k.claim_a, k.claim_b) for k in state.contradictions.values()
        }
        out: list[dict[str, Any]] = []
        for item in _as_dict_list(data.get("contradictions")):
            a, b = item.get("claim_a"), item.get("claim_b")
            if not (isinstance(a, str) and isinstance(b, str)) or a == b:
                continue
            if a not in view.claims or b not in view.claims:
                continue
            key = _pair_key(a, b)
            if key in seen:
                continue
            conflict = item.get("conflict")
            if not isinstance(conflict, str) or len(conflict.strip()) < _MIN_CONFLICT_LEN:
                continue
            seen.add(key)
            out.append(
                {
                    "a": a,
                    "b": b,
                    "conflict": conflict.strip(),
                    "type": item.get("type"),
                    "severity": item.get("severity"),
                    "options": [
                        o for o in item.get("resolution_options", []) if isinstance(o, str)
                    ],
                }
            )
        return out

    def _verify(
        self, view: ProjectionView, candidates: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        lines = []
        for i, c in enumerate(candidates, start=1):
            lines.append(
                f'{i}. "{view.claims[c["a"]].text}" VS "{view.claims[c["b"]].text}" '
                f'(proposed conflict: {c["conflict"]})'
            )
        request = ProviderRequest(
            system=(
                "You are a skeptical fact-checker. Your default assumption is "
                "that two claims CAN both be true at once. Confirm a "
                "contradiction ONLY when it is logically impossible for both to "
                "hold — one asserts something the other denies about the same "
                "thing. Two claims that both support the same conclusion, or "
                "describe different things, can coexist and are NOT "
                "contradictions."
            ),
            user=(
                "For each numbered pair, decide whether both claims can be true "
                "at the same time.\n\n" + "\n".join(lines) + "\n\n"
                'Return ONLY {"keep": [numbers]} listing the pairs that are '
                "GENUINE contradictions (cannot both be true). Omit any pair "
                'that can coexist. If none are genuine, return {"keep": []}.'
            ),
        )
        try:
            verdict = load_json(self.provider.complete(request).text)
        except LLMAssemblyError:
            return candidates  # graceful: fall back to the gate-passed set
        keep = verdict.get("keep") if isinstance(verdict, dict) else None
        if not isinstance(keep, list):
            return candidates
        kept_idx = {
            int(n)
            for n in keep
            if isinstance(n, int) or (isinstance(n, str) and n.strip().isdigit())
        }
        return [c for i, c in enumerate(candidates, start=1) if i in kept_idx]

    def _build_patch(
        self,
        state: SemanticState,
        view: ProjectionView,
        candidates: list[dict[str, Any]],
    ) -> SemanticPatch:
        now = self.clock.now()
        contradictions: list[Contradiction] = []
        write_set: list[str] = []
        for c in candidates:
            cid = f"contradiction_{len(contradictions) + 1:03d}"
            contradictions.append(
                Contradiction(
                    id=cid,
                    claim_a=c["a"],
                    claim_b=c["b"],
                    contradiction_type=coerce_enum(
                        c["type"], _TYPES, ContradictionType.TENSION
                    ),
                    severity=coerce_enum(c["severity"], _SEVERITIES, Severity.MEDIUM),
                    status=ContradictionStatus.UNRESOLVED,
                    resolution_options=c["options"],
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
            notes=f"Confirmed {len(contradictions)} contradiction(s) after review.",
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
