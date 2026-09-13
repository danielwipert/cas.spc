"""Corroboration — what two sources independently say (T19).

T18 put two documents into one semantic state and the result wrote this
operator's specification. Over the Paramount/WBD press release plus the DOJ
Antitrust Division's determination, the Retriever committed:

    "What stronger source would confirm 'The deal may face risks from
    regulatory clearances and stockholder approval'?"
    (claim_013 rests only on lower-reliability evidence.)

while a claim at 0.95, on the regulator's own finding, sat in the same state
answering it. The question and its answer were both committed and **nothing
connected them**. The recommendation, meanwhile, rested entirely on
press-release claims at 0.60 or below while six high-reliability claims went
unused: the pipeline held better evidence than it reasoned from.

Whether two differently-worded sentences assert the same thing is a semantic
judgement, so this operator is LLM-backed — the model supplies the pairings and
the operator owns every consequence (AGENTS.md §VII).

**It never touches confidence, and that is the whole design.** T15 and T16 hold
that calibration only ever lowers, because raising a number on the strength of
its own support is how a pipeline invents certainty. Corroboration does not
need an exception: it changes *what a claim rests on*, which is a fact about
provenance, and the calibrator's existing rule reprices it. A claim ceilinged
at `confidence x reliability_factor(best evidence)` and cited only to a press
release carries 0.60; once a regulator's span genuinely supports it, the best
evidence it cites is `HIGH` and the same untouched rule lets it carry more. No
new arithmetic, no exception to a stated invariant, and the reason is on the
record as a relation rather than buried in a number.

**This operator no longer labels anything.** It used to promote the corroborated
claim's `epistemic_status` from `REPORTED` to `VERIFIED`, which destroyed a fact
to record another one — a corroborated claim is *still* reported, because it was
still read out of a document. T20 retired that write: support is **derived** from
what a claim cites (`spc_state.epistemics.corroboration_of`), and this operator
already does the only thing that derivation needs, which is to attach the
corroborating span. The `VERIFIED` rung still requires an **accountable** source,
but the rule now lives where it can be recomputed instead of on a field someone
has to remember to update.

**Only across independent sources.** Two claims from the same document agreeing
corroborate nothing, and neither do two documents where one was written off the
other — a wire story republished ten times is one source wearing ten hats. The
operator drops both kinds of pair itself rather than trusting the model to,
reading the lineage the caller declared (T20). **One direction only:** the
better-sourced claim corroborates the weaker. The reverse adds a span that cannot
raise anything (the *best* evidence wins within a claim) and would only clutter
provenance.

Detection runs in **two passes**, the precision gate
`LLMContradictionOperator` established. A single pass is too eager, and a false
corroboration is worse here than a missed one: it does not merely add a note,
it lets a claim inherit warrant it never earned. So a skeptic pass defaults to
"these are different claims" and keeps only pairs asserting the same thing
about the same subject.

What the model still decides is whether two claims assert *the same thing* —
the one judgement T14-T19 left with it, and worth naming rather than letting a
derived `VERIFIED` read as more than it is. Independence and accountability are
structural; the match is not.

With a single source there is nothing to corroborate across, so `analyze` does
not add this stage at all rather than paying for a call whose answer is already
known. That keeps every single-document run — and every committed cassette —
exactly as it was. Constructed directly against one source the operator is
still correct, just wasteful: `_candidates` drops same-source pairs itself, so
the patch comes back empty.
"""

from __future__ import annotations

from typing import Any

from ..epistemics import source_lineage, sources_are_independent
from ..models import (
    PatchStatus,
    Perspective,
    Projection,
    Relation,
    SemanticPatch,
    SemanticState,
    TokenUsage,
    TransformRecord,
    sum_token_usage,
)
from ..models.patch import UpdateObject
from ..operators.calibration import RELIABILITY_FACTOR, best_reliability
from ..projection import ProjectionView, resolve_view
from ..providers import LLMProvider, ProviderRequest
from ..runtime.clock import Clock, WallClock
from ._assembly import LLMAssemblyError, load_json
from .llm import LLMOperator, OperatorCompletion

#: A justification shorter than this is not a justification.
_MIN_BASIS_LEN = 12

_SCHEMA_HINT = """Two claims CORROBORATE each other when they assert the same
thing about the same subject — the same fact, event, figure or conclusion,
stated in different words by different sources.

Do NOT report a pair when:
- the claims are about different subjects, figures, or time periods;
- one is merely related to, caused by, or an elaboration of the other;
- they are both about the transaction but say different things about it;
- they merely point the same way. Agreeing in spirit is not corroboration.

Return ONLY a single JSON object of this exact shape:

{
  "corroborations": [
    {
      "claim_a": "claim_001",
      "claim_b": "d2_claim_003",
      "basis": "one sentence: the same thing both claims assert"
    }
  ]
}

Rules:
- Reference only the claim ids listed above, and pair claims from DIFFERENT
  sources — two claims from one document corroborate nothing.
- Fill `basis` with the shared assertion. If you cannot state in one sentence
  what both claims say, it is not a corroboration — omit it.
- When in doubt, omit. A false corroboration is worse than a missed one: it
  lends one source's authority to another source's claim.
- If nothing is corroborated, return {"corroborations": []}.
- No prose, no markdown fences — only the JSON object."""


def _pair_key(a: str, b: str) -> tuple[str, str]:
    return (a, b) if a <= b else (b, a)


class LLMCorroborationOperator(LLMOperator):
    """Link claims two sources independently assert, and promote what that earns."""

    name = "corroboration_transform"
    version = "0.1.0"
    perspective = Perspective.VERIFIER
    goal = (
        "Identify claims that two different sources independently assert, and "
        "record what each claim therefore rests on."
    )

    def __init__(
        self,
        provider: LLMProvider,
        *,
        clock: Clock | None = None,
        max_attempts: int = 3,
        patch_id: str = "patch_corroboration_001",
        transform_id: str = "transform_corroboration_001",
    ) -> None:
        super().__init__(provider, max_attempts=max_attempts)
        self.clock = clock or WallClock()
        self.patch_id = patch_id
        self.transform_id = transform_id

    # -- reading the state -------------------------------------------------

    def _source_of(self, claim_id: str, view: ProjectionView) -> str | None:
        """Which document a claim came from, via the spans it cites."""
        claim = view.claims.get(claim_id)
        if claim is None:
            return None
        for eid in claim.supporting_evidence:
            evidence = view.evidence.get(eid)
            if evidence is not None:
                return evidence.source_id
        return None

    def _strength(self, claim_id: str, view: ProjectionView) -> float:
        claim = view.claims.get(claim_id)
        if claim is None:
            return 0.0
        best = best_reliability(claim, view)
        return 0.0 if best is None else RELIABILITY_FACTOR[best]

    def _sources(self, view: ProjectionView) -> dict[str, list[str]]:
        grouped: dict[str, list[str]] = {}
        for cid in sorted(view.claims):
            source = self._source_of(cid, view)
            if source is not None:
                grouped.setdefault(source, []).append(cid)
        return grouped

    # -- the model's part --------------------------------------------------

    def build_request(
        self, view: ProjectionView, feedback: list[str]
    ) -> ProviderRequest:
        blocks = []
        for source, claim_ids in sorted(self._sources(view).items()):
            lines = "\n".join(f"- {cid}: {view.claims[cid].text}" for cid in claim_ids)
            blocks.append(f"SOURCE {source}:\n{lines}")
        user = (
            "Find claims from different sources that assert the same thing.\n\n"
            + "\n\n".join(blocks or ["(no claims)"])
            + f"\n\n{_SCHEMA_HINT}"
        )
        return ProviderRequest(
            system=(
                "You compare what independent sources say. Two claims "
                "corroborate each other only when they assert the same thing "
                "about the same subject. Claims that merely point the same way "
                "are not corroboration. Prefer reporting none over reporting a "
                "weak one. Emit only the requested JSON, referencing existing "
                "claim ids."
            ),
            user=user,
            feedback=feedback,
        )

    def generate(
        self,
        state: SemanticState,
        projection: Projection,
        feedback: list[str],
    ) -> OperatorCompletion:
        view = resolve_view(projection, state)
        response = self.provider.complete(self.build_request(view, feedback))
        try:
            data = load_json(response.text)
        except LLMAssemblyError as exc:
            return OperatorCompletion(
                text=response.text,
                fingerprint=response.fingerprint,
                usage=response.usage,
                repair_hint=str(exc),
            )
        if isinstance(data, dict) and ("add_objects" in data or "patch_id" in data):
            # A full patch is the runtime's to judge, as elsewhere.
            return OperatorCompletion(
                text=response.text,
                fingerprint=response.fingerprint,
                usage=response.usage,
            )
        if not isinstance(data, dict):
            return OperatorCompletion(
                text=response.text,
                fingerprint=response.fingerprint,
                usage=response.usage,
                repair_hint=(
                    'Your output must be a single JSON object with a '
                    '"corroborations" array, not an array or a scalar.'
                ),
            )

        candidates = self._candidates(view, data)
        usage = response.usage
        if candidates:
            candidates, verify_usage = self._verify(view, candidates)
            usage = sum_token_usage(usage, verify_usage)  # a real second call
        patch = self._build_patch(state, view, candidates)
        return OperatorCompletion(
            text=patch.model_dump_json(by_alias=True),
            fingerprint=response.fingerprint,
            usage=usage,
        )

    def _candidates(
        self, view: ProjectionView, data: dict[str, Any]
    ) -> list[dict[str, Any]]:
        """Keep pairs that are valid, justified, distinct and cross-source."""
        seen: set[tuple[str, str]] = set()
        out: list[dict[str, Any]] = []
        lineage = source_lineage(view.evidence)
        for item in _as_dict_list(data.get("corroborations")):
            a, b = item.get("claim_a"), item.get("claim_b")
            if not (isinstance(a, str) and isinstance(b, str)) or a == b:
                continue
            if a not in view.claims or b not in view.claims:
                continue
            source_a, source_b = self._source_of(a, view), self._source_of(b, view)
            # The operator enforces this rather than trusting the instruction:
            # a document agreeing with itself corroborates nothing, and neither
            # does a document agreeing with the one it was written off (T20).
            if source_a is None or source_b is None:
                continue
            if not sources_are_independent(source_a, source_b, lineage):
                continue
            key = _pair_key(a, b)
            if key in seen:
                continue
            basis = item.get("basis")
            if not isinstance(basis, str) or len(basis.strip()) < _MIN_BASIS_LEN:
                continue
            seen.add(key)
            out.append({"a": a, "b": b, "basis": basis.strip()})
        return out

    def _verify(
        self, view: ProjectionView, candidates: list[dict[str, Any]]
    ) -> tuple[list[dict[str, Any]], TokenUsage | None]:
        """The skeptic pass: default to "different claims", keep the same ones."""
        lines = [
            f'{i}. "{view.claims[c["a"]].text}" VS "{view.claims[c["b"]].text}" '
            f'(proposed shared assertion: {c["basis"]})'
            for i, c in enumerate(candidates, start=1)
        ]
        request = ProviderRequest(
            system=(
                "You are a skeptical fact-checker. Your default assumption is "
                "that two claims from different documents are about DIFFERENT "
                "things. Confirm corroboration ONLY when both claims assert the "
                "same thing about the same subject — the same fact, figure, "
                "event or conclusion. Claims that are merely related, or that "
                "both support the same overall position, are NOT corroboration."
            ),
            user=(
                "For each numbered pair, decide whether both claims assert the "
                "same thing.\n\n" + "\n".join(lines) + "\n\n"
                'Return ONLY {"keep": [numbers]} listing the pairs that are '
                "GENUINE corroborations. Omit any pair that merely relates. If "
                'none are genuine, return {"keep": []}.'
            ),
        )
        verify_response = self.provider.complete(request)
        try:
            verdict = load_json(verify_response.text)
        except LLMAssemblyError:
            # Graceful, as elsewhere: fall back to the gate-passed set. The call
            # happened and cost tokens, so its usage is still counted.
            return candidates, verify_response.usage
        keep = verdict.get("keep") if isinstance(verdict, dict) else None
        if not isinstance(keep, list):
            return candidates, verify_response.usage
        kept = {
            int(n)
            for n in keep
            if isinstance(n, int) or (isinstance(n, str) and n.strip().isdigit())
        }
        return [c for i, c in enumerate(candidates, start=1) if i in kept], (
            verify_response.usage
        )

    # -- the operator's part -----------------------------------------------

    def _build_patch(
        self,
        state: SemanticState,
        view: ProjectionView,
        candidates: list[dict[str, Any]],
    ) -> SemanticPatch:
        now = self.clock.now()
        updates: list[UpdateObject] = []
        relations: list[Relation] = []
        write_set: list[str] = []
        read_set: set[str] = set()
        # One entry per corroborated claim, so two corroborations of the same
        # claim accumulate rather than the second overwriting the first.
        gained: dict[str, list[str]] = {}

        for c in candidates:
            a, b = c["a"], c["b"]
            read_set.update((a, b))
            # The better-sourced claim corroborates the weaker; ties resolve by
            # id so the patch is deterministic.
            pair = sorted((a, b), key=lambda cid: (-self._strength(cid, view), cid))
            strong, weak = pair[0], pair[1]
            strong_claim, weak_claim = view.claims[strong], view.claims[weak]

            best = best_reliability(strong_claim, view)
            if best is None:
                continue
            spans = [
                eid
                for eid in strong_claim.supporting_evidence
                if (e := view.evidence.get(eid)) is not None and e.reliability is best
            ]
            read_set.update(strong_claim.supporting_evidence)
            read_set.update(weak_claim.supporting_evidence)
            held = set(weak_claim.supporting_evidence) | set(gained.get(weak, []))
            new = [eid for eid in spans if eid not in held]
            if new:
                gained.setdefault(weak, []).extend(new)
            rid = f"rel_corrob_{len(relations) + 1:03d}"
            relations.append(
                Relation(
                    id=rid,
                    source=strong,
                    predicate="corroborates",
                    target=weak,
                    confidence=1.0,
                    created_by=self.transform_id,
                )
            )
            write_set.append(rid)

        for cid in sorted(gained):
            claim = view.claims[cid]
            updated = [*claim.supporting_evidence, *gained[cid]]
            updates.append(
                UpdateObject.model_validate(
                    {
                        "object_id": cid,
                        "field": "supporting_evidence",
                        "from": list(claim.supporting_evidence),
                        "to": updated,
                        "reason": (
                            "Corroborated by another source; the span now "
                            "supports this claim, so calibration reprices it "
                            "against what it actually rests on."
                        ),
                    }
                )
            )
            if cid not in write_set:
                write_set.append(cid)

        resolved_reads = sorted(read_set & (set(view.claims) | set(view.evidence)))
        transform_record = TransformRecord(
            id=self.transform_id,
            transform_type="corroborate",
            operator=self.name,
            operator_version=self.fully_qualified(),
            input_state_version=state.state_version,
            output_state_version=None,
            read_set=resolved_reads,
            write_set=write_set,
            confidence_changes=[],
            started_at=now,
            finished_at=now,
            notes=(
                f"Linked {len(relations)} corroboration(s) across independent "
                f"sources; {len(gained)} claim(s) gained supporting spans."
            ),
        )
        return SemanticPatch(
            patch_id=self.patch_id,
            base_state_id=state.state_id,
            base_state_version=state.state_version,
            proposed_by=self.fully_qualified(),
            created_at=now,
            read_set=resolved_reads,
            update_objects=updates,
            add_relations=relations,
            transform_record=transform_record,
            status=PatchStatus.PROPOSED,
        )


def _as_dict_list(value: Any) -> list[dict[str, Any]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


__all__ = ["LLMCorroborationOperator"]
