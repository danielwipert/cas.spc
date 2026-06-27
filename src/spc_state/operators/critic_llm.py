"""LLM-backed Critic — scrutinise weak claims and open tensions.

Reads the critic projection (weak claims + assumptions) and asks a model which
claims are over-confident and what tensions deserve a question. The operator
assembles a canonical patch: versioned `update_objects` with `from`/`to`/`reason`
(the `from` is read from the committed state, never trusted to the model),
matching `ConfidenceChange` records, plus questions linked to the claims they
challenge. Only claims actually in the slice may be touched, keeping the
operator honest to its projection.

A critic that finds nothing to change commits an empty (no-op) patch — the
audit log still records that the critique ran. Unparseable output falls through
to the validator (-> RETRY). The operator never mutates state.
"""

from __future__ import annotations

from typing import Any

from ..models import (
    PatchStatus,
    Perspective,
    Priority,
    Projection,
    Question,
    QuestionStatus,
    Relation,
    SemanticPatch,
    SemanticState,
    TransformRecord,
)
from ..models.patch import AddObjects, UpdateObject
from ..models.transform import ConfidenceChange
from ..projection import ProjectionView, resolve_view
from ..providers import LLMProvider, ProviderRequest, ProviderResponse
from ..runtime.clock import Clock, WallClock
from ._assembly import LLMAssemblyError, clamp_confidence, coerce_enum, load_json
from .llm import LLMOperator

_PRIORITIES = {p.value: p for p in Priority}

_SCHEMA_HINT = """Return ONLY a single JSON object of this exact shape:

{
  "confidence_updates": [
    {
      "claim": "claim_001",
      "new_confidence": 0.0 to 1.0,
      "reason": "why this claim is over- or under-confident"
    }
  ],
  "questions": [
    {
      "text": "a tension or unresolved issue worth tracking",
      "priority": "low | medium | high",
      "challenges_claim": "claim_001"
    }
  ]
}

Rules:
- Reference only the claim_* ids listed above; invent none.
- Lower confidence you cannot justify from the evidence; raise it only with cause.
- Omit a claim from `confidence_updates` if its confidence is already right.
- No prose, no markdown fences — only the JSON object."""


class LLMReviewCriticOperator(LLMOperator):
    """Critique weak claims via confidence updates and questions."""

    name = "llm_critic_transform"
    version = "0.1.0"
    perspective = Perspective.CRITIC
    goal = "Identify weak claims, missing assumptions, and unresolved tensions."

    def __init__(
        self,
        provider: LLMProvider,
        *,
        clock: Clock | None = None,
        max_attempts: int = 3,
        patch_id: str = "patch_003",
        transform_id: str = "transform_critic_001",
    ) -> None:
        super().__init__(provider, max_attempts=max_attempts)
        self.clock = clock or WallClock()
        self.patch_id = patch_id
        self.transform_id = transform_id

    def build_request(
        self, view: ProjectionView, feedback: list[str]
    ) -> ProviderRequest:
        claims = "\n".join(
            f"- {cid}: {c.text} (confidence {c.confidence:.2f}, "
            f"{c.epistemic_status.value}, {len(c.supporting_evidence)} evidence)"
            for cid, c in sorted(view.claims.items())
        ) or "(no weak claims)"
        user = (
            "You are critiquing the weak claims in a shared semantic state.\n\n"
            f"WEAK CLAIMS:\n{claims}\n\n{_SCHEMA_HINT}"
        )
        return ProviderRequest(
            system=(
                "You are a rigorous critic. Emit only the requested JSON, "
                "referencing existing claim ids."
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

        now = self.clock.now()
        updates: list[UpdateObject] = []
        changes: list[ConfidenceChange] = []
        questions: list[Question] = []
        relations: list[Relation] = []
        read_set = sorted(view.claims)
        write_set: list[str] = []

        for upd in _as_dict_list(data.get("confidence_updates")):
            cid = upd.get("claim")
            if not isinstance(cid, str):
                continue
            claim = view.claims.get(cid)
            if claim is None:
                continue
            new_conf = clamp_confidence(upd.get("new_confidence"), default=claim.confidence)
            if abs(new_conf - claim.confidence) < 1e-9:
                continue  # no real change
            reason = (upd.get("reason") or "Confidence adjusted on review.").strip()
            payload = {
                "object_id": cid,
                "from": claim.confidence,
                "to": new_conf,
                "reason": reason,
            }
            updates.append(UpdateObject.model_validate({"field": "confidence", **payload}))
            changes.append(ConfidenceChange.model_validate(payload))
            if cid not in write_set:
                write_set.append(cid)

        for i, rq in enumerate(_as_dict_list(data.get("questions")), start=1):
            text = (rq.get("text") or "").strip()
            if not text:
                continue
            qid = f"q_crit_{i:03d}"
            challenged = rq.get("challenges_claim")
            linked: list[str] = (
                [challenged]
                if isinstance(challenged, str) and challenged in view.claims
                else []
            )
            questions.append(
                Question(
                    id=qid,
                    text=text,
                    status=QuestionStatus.OPEN,
                    priority=coerce_enum(rq.get("priority"), _PRIORITIES, Priority.MEDIUM),
                    linked_objects=linked,
                    asked_by=self.transform_id,
                )
            )
            write_set.append(qid)
            if linked:
                rid = f"rel_crit_{i:03d}"
                relations.append(
                    Relation(
                        id=rid,
                        source=qid,
                        predicate="questions",
                        target=linked[0],
                        confidence=1.0,
                        created_by=self.transform_id,
                    )
                )
                write_set.append(rid)

        transform_record = TransformRecord(
            id=self.transform_id,
            transform_type="critique",
            operator=self.name,
            operator_version=self.fully_qualified(),
            input_state_version=state.state_version,
            output_state_version=None,
            read_set=read_set,
            write_set=write_set,
            confidence_changes=changes,
            started_at=now,
            finished_at=now,
            notes="LLM critique assembled into a canonical critique patch.",
        )
        return SemanticPatch(
            patch_id=self.patch_id,
            base_state_id=state.state_id,
            base_state_version=state.state_version,
            proposed_by=self.fully_qualified(),
            created_at=now,
            read_set=read_set,
            add_objects=AddObjects(questions=questions),
            update_objects=updates,
            add_relations=relations,
            transform_record=transform_record,
            status=PatchStatus.PROPOSED,
        )


def _as_dict_list(value: Any) -> list[dict[str, Any]]:
    return [v for v in value if isinstance(v, dict)] if isinstance(value, list) else []


__all__ = ["LLMReviewCriticOperator"]
