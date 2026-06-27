"""LLM-backed Planner — propose a recommendation, questions, and dependencies.

Reads the planner projection (claims + assumptions) of an LLM-extracted state
and asks a model for the *decision skeleton*: the leading hypothesis (the
recommended course of action, which the Reasoning Receipt reads as the answer),
the open questions worth resolving, and which claims depend on which
assumptions. The operator assembles those into a canonical patch — owning ids
and the transform record — and references only object ids that actually exist
in the slice, so it stays referentially closed. The runtime validates and
commits (`Runtime.step_llm`); the operator never mutates state.

Mirrors `LLMExtractOperator`'s division of labour (AGENTS.md §VII): the model
contributes judgement, the operator contributes bookkeeping.
"""

from __future__ import annotations

from typing import Any

from ..models import (
    Hypothesis,
    HypothesisStatus,
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
from ..models.patch import AddObjects
from ..projection import ProjectionView, resolve_view
from ..providers import LLMProvider, ProviderRequest, ProviderResponse
from ..runtime.clock import Clock, WallClock
from ._assembly import LLMAssemblyError, clamp_confidence, coerce_enum, load_json
from .llm import LLMOperator

_PRIORITIES = {p.value: p for p in Priority}

_SCHEMA_HINT = """Return ONLY a single JSON object of this exact shape:

{
  "hypothesis": {
    "text": "the single recommended course of action for the decision",
    "confidence": 0.0 to 1.0,
    "supporting_claims": ["claim_001", "claim_003"]
  },
  "questions": [
    {
      "text": "an open question that must be resolved before deciding",
      "priority": "low | medium | high",
      "linked_claims": ["claim_002"]
    }
  ],
  "dependencies": [
    { "claim": "claim_001", "assumption": "assumption_001" }
  ]
}

Rules:
- Reference only the claim_* and assumption_* ids listed above; invent none.
- `supporting_claims` are the claims that most justify the recommendation.
- `dependencies` link a claim to an assumption it relies on.
- No prose, no markdown fences — only the JSON object."""


class LLMPlannerOperator(LLMOperator):
    """Propose the decision skeleton (hypothesis + questions + dependencies)."""

    name = "llm_planner_transform"
    version = "0.1.0"
    perspective = Perspective.PLANNER
    goal = (
        "Surface the recommended course of action, the open questions, and the "
        "claim/assumption dependencies for the decision under analysis."
    )

    def __init__(
        self,
        provider: LLMProvider,
        *,
        clock: Clock | None = None,
        max_attempts: int = 3,
        patch_id: str = "patch_002",
        transform_id: str = "transform_planner_001",
    ) -> None:
        super().__init__(provider, max_attempts=max_attempts)
        self.clock = clock or WallClock()
        self.patch_id = patch_id
        self.transform_id = transform_id

    def build_request(
        self, view: ProjectionView, feedback: list[str]
    ) -> ProviderRequest:
        claims = "\n".join(
            f"- {cid}: {c.text} (confidence {c.confidence:.2f})"
            for cid, c in sorted(view.claims.items())
        ) or "(none)"
        assumptions = "\n".join(
            f"- {aid}: {a.text}" for aid, a in sorted(view.assumptions.items())
        ) or "(none)"
        user = (
            "You are planning a decision from a shared semantic state.\n\n"
            f"CLAIMS:\n{claims}\n\nASSUMPTIONS:\n{assumptions}\n\n{_SCHEMA_HINT}"
        )
        return ProviderRequest(
            system=(
                "You are a decision planner. Emit only the requested JSON, "
                "referencing existing object ids."
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

        claim_ids = set(view.claims)
        assumption_ids = set(view.assumptions)
        read_set = sorted(claim_ids | assumption_ids)
        now = self.clock.now()

        hypotheses: list[Hypothesis] = []
        questions: list[Question] = []
        relations: list[Relation] = []
        write_set: list[str] = []

        hyp = data.get("hypothesis")
        if isinstance(hyp, dict) and (hyp.get("text") or "").strip():
            supporting = [c for c in _as_id_list(hyp.get("supporting_claims")) if c in claim_ids]
            hypotheses.append(
                Hypothesis(
                    id="hyp_001",
                    text=hyp["text"].strip(),
                    status=HypothesisStatus.ACTIVE,
                    confidence=clamp_confidence(hyp.get("confidence"), default=0.6),
                    supporting_claims=supporting,
                    generated_by=self.transform_id,
                )
            )
            write_set.append("hyp_001")
        else:
            # The hypothesis is the planner's whole point — without it, retry.
            raise LLMAssemblyError("Planner produced no hypothesis.")

        for i, rq in enumerate(_as_dict_list(data.get("questions")), start=1):
            text = (rq.get("text") or "").strip()
            if not text:
                continue
            qid = f"q_plan_{i:03d}"
            linked = [c for c in _as_id_list(rq.get("linked_claims")) if c in claim_ids]
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

        for i, dep in enumerate(_as_dict_list(data.get("dependencies")), start=1):
            cid = dep.get("claim")
            aid = dep.get("assumption")
            if cid in claim_ids and aid in assumption_ids:
                rid = f"rel_plan_{i:03d}"
                relations.append(
                    Relation(
                        id=rid,
                        source=cid,
                        predicate="depends_on",
                        target=aid,
                        confidence=0.9,
                        created_by=self.transform_id,
                    )
                )
                write_set.append(rid)

        transform_record = TransformRecord(
            id=self.transform_id,
            transform_type="plan",
            operator=self.name,
            operator_version=self.fully_qualified(),
            input_state_version=state.state_version,
            output_state_version=None,
            read_set=read_set,
            write_set=write_set,
            confidence_changes=[],
            started_at=now,
            finished_at=now,
            notes="LLM planning assembled into a canonical plan patch.",
        )
        return SemanticPatch(
            patch_id=self.patch_id,
            base_state_id=state.state_id,
            base_state_version=state.state_version,
            proposed_by=self.fully_qualified(),
            created_at=now,
            read_set=read_set,
            add_objects=AddObjects(
                hypotheses=hypotheses, questions=questions
            ),
            add_relations=relations,
            transform_record=transform_record,
            status=PatchStatus.PROPOSED,
        )


def _as_dict_list(value: Any) -> list[dict[str, Any]]:
    return [v for v in value if isinstance(v, dict)] if isinstance(value, list) else []


def _as_id_list(value: Any) -> list[str]:
    return [v for v in value if isinstance(v, str)] if isinstance(value, list) else []


__all__ = ["LLMPlannerOperator"]
