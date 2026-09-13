"""LLM-backed Extract — turn *any* document into an initial SemanticState.

The deterministic `ExtractOperator` only recognises the demo document. This
operator removes that ceiling: it asks an `LLMProvider` to read an arbitrary
document and return the claims, evidence, and assumptions it finds, then
**assembles** a well-formed extract `SemanticPatch` around that content.

Division of labour (AGENTS.md §VII): the model contributes *semantic content*
— what the claims are, which span supports each, what each depends on. The
operator owns the *bookkeeping* — canonical ids, provenance wiring, the
`TransformRecord`, read/write sets — which must be deterministic and correct,
not invented by a model. The result still flows through the runtime's
validate -> route -> commit loop (`Runtime.step_llm`); the operator never
mutates state.

Evidence *reliability* falls on the operator's side of that line, and used not
to. It is a fact about where the text came from, which the caller declares as
`source_type` and the model cannot see from inside the document — asking the
model for it let an extraction grade itself, and on a live press release it
awarded its own ten spans `high` and silenced the Retriever. It is derived from
the declaration instead (`source_types`), on both routes in.

The model is asked for a compact extraction schema rather than a full
`SemanticPatch`, because the patch envelope is exactly the error-prone part a
model should not be hand-writing. If the model returns prose, malformed JSON,
or already-formed patch JSON, the cases are handled: prose/garbage falls
through to the validator (JSON_DECODE -> RETRY with feedback); a full patch is
passed through, with its citations checked and its weighting corrected the same
way the assembled ones are.
"""

from __future__ import annotations

import json

from ..models import (
    Assumption,
    Claim,
    ClaimType,
    EpistemicStatus,
    Evidence,
    Impact,
    PatchStatus,
    Perspective,
    Projection,
    SemanticPatch,
    SemanticState,
    TransformRecord,
)
from ..models.patch import AddObjects
from ..projection import ProjectionView, resolve_view
from ..provenance import locate_span
from ..providers import LLMProvider, ProviderRequest
from ..runtime.clock import Clock, WallClock
from ..source_types import (
    DEFAULT_SOURCE_TYPE,
    LEGACY_INPUT_DOCUMENT,
    SourceType,
    coerce_source_type,
    reliability_for,
)
from ._assembly import LLMAssemblyError, clamp_confidence, coerce_enum, load_json
from .llm import LLMOperator, OperatorCompletion

#: Back-compat alias — this operator originally defined its own error type.
ExtractionError = LLMAssemblyError

_SCHEMA_HINT = """Return ONLY a single JSON object of this exact shape:

{
  "claims": [
    {
      "text": "one claim stated in the document, in your own words",
      "claim_type": "factual_claim | analytical_claim | predictive_claim | normative_claim",
      "epistemic_status": "reported | inferred | assumed | speculative",
      "confidence": 0.0 to 1.0,
      "evidence_quote": "the exact span from the document that supports this claim",
      "assumption": "an assumption this claim depends on, or null if none",
      "assumption_impact": "low | medium | high"
    }
  ]
}

Rules:
- Extract every substantive claim, including caveats and concerns.
- `evidence_quote` must be copied verbatim from the document. It is
  checked against the document text; a quote that cannot be found there
  is rejected, so never paraphrase, shorten mid-span, or invent one.
- `epistemic_status` is `reported` when the document states the claim, and
  `inferred` when you worked it out from what the document states. There is no
  `observed`: reading a document shows that the document says something, not
  that it is so.
- Use `assumption` only for something the document does not establish but the
  claim relies on; otherwise null.
- No prose, no markdown fences — only the JSON object."""


_CLAIM_TYPES = {
    "factual_claim": ClaimType.FACTUAL,
    "factual": ClaimType.FACTUAL,
    "analytical_claim": ClaimType.ANALYTICAL,
    "analytical": ClaimType.ANALYTICAL,
    "predictive_claim": ClaimType.PREDICTIVE,
    "predictive": ClaimType.PREDICTIVE,
    "normative_claim": ClaimType.NORMATIVE,
    "normative": ClaimType.NORMATIVE,
}
_EPISTEMIC = {s.value: s for s in EpistemicStatus}

#: Statuses no operator reading a document can honestly claim, and what each
#: becomes (T17). `observed` because the extractor saw the document, not the
#: thing. Applied after the model's answer, so a model that ignores the prompt
#: is corrected rather than believed — the same two-routes-in rule T11
#: established for provenance.
#:
#: `verified` used to be mapped here too. T20 retired it from the axis
#: altogether — support is derived from what a claim cites, not asserted on it —
#: so a model answering `verified` now falls through `coerce_enum` to the
#: `reported` default on the assembled path, and is migrated by `Claim` itself on
#: the passthrough path. Both routes still land on `reported`; neither needs a
#: line here.
_UNAVAILABLE_TO_A_READER = {
    EpistemicStatus.OBSERVED: EpistemicStatus.REPORTED,
}


def ground_status(status: EpistemicStatus) -> EpistemicStatus:
    """The strongest status a claim read out of a document may carry."""
    return _UNAVAILABLE_TO_A_READER.get(status, status)
_IMPACT = {i.value: i for i in Impact}


def _shorten(quote: str, limit: int = 80) -> str:
    """A quote short enough to echo back in a repair hint."""
    collapsed = " ".join(quote.split())
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[: limit - 3] + "..."


def _parses_as_patch(text: str) -> bool:
    """Would the runtime read this completion as a committable patch?"""
    try:
        SemanticPatch.model_validate_json(text)
    except ValueError:
        return False
    return True


def _rejected_completion(raw: str, reason: str) -> str:
    """The text an operator hands back for output it refuses.

    Usually the model's raw output, unchanged — it cannot be committed because
    it does not parse as a patch, and keeping it verbatim keeps the attempt
    record honest. Output that *would* parse is wrapped instead, so the
    runtime cannot commit what the operator rejected; the original is carried
    inside, still verbatim.
    """
    if not _parses_as_patch(raw):
        return raw
    return json.dumps(
        {"rejected_by_operator": reason, "model_output": raw}, ensure_ascii=False
    )


def _unlocatable_message(quotes: list[str]) -> str:
    """The repair hint for quotes that are not in the document (T8)."""
    shown = "; ".join(f'"{_shorten(q)}"' for q in quotes[:3])
    if len(quotes) > 3:
        shown += f"; and {len(quotes) - 3} more"
    return (
        f"{len(quotes)} evidence_quote value(s) do not appear in the document: "
        f"{shown}. Copy each quote character-for-character from the DOCUMENT "
        "text above — do not paraphrase, summarise, translate, or invent a "
        "span. If no verbatim span supports a claim, drop that claim."
    )


class LLMExtractOperator(LLMOperator):
    """Extract claims/evidence/assumptions from any document via an LLM."""

    name = "llm_extract_transform"
    version = "0.1.0"
    perspective = Perspective.EXTRACT
    goal = (
        "Extract claims, supporting evidence, and assumptions from the input "
        "document as a structured initial semantic state."
    )

    def __init__(
        self,
        provider: LLMProvider,
        *,
        input_text: str,
        clock: Clock | None = None,
        max_attempts: int = 3,
        patch_id: str = "patch_001",
        transform_id: str = "transform_extract_001",
        source_id: str = "doc_001",
        source_type: SourceType | str = DEFAULT_SOURCE_TYPE,
        derives_from: str | None = None,
        id_prefix: str = "",
    ) -> None:
        super().__init__(provider, max_attempts=max_attempts)
        self.input_text = input_text
        self.clock = clock or WallClock()
        self.patch_id = patch_id
        self.transform_id = transform_id
        self.source_id = source_id
        #: Which source this document is downstream of, declared by the caller
        #: (T20) for the same reason `source_type` is: whether this text was
        #: written off another document is a fact about the world outside it,
        #: which the model cannot see and does not get a vote on.
        self.derives_from = derives_from
        #: What kind of document this is, declared by the caller — and the
        #: reliability every span drawn from it therefore carries. Derived once
        #: here, never taken from the model (see `source_types`).
        self.source_type = coerce_source_type(source_type)
        self.reliability = reliability_for(self.source_type)
        #: Prepended to every id this operator mints. Empty for the first
        #: document in a run; a second extraction into the same state needs its
        #: own namespace, because `claim_001` is already taken and L2 rejects
        #: the collision by design (`L2.DUPLICATE_OBJECT_ID`).
        self.id_prefix = id_prefix

    def build_request(
        self, view: ProjectionView, feedback: list[str]
    ) -> ProviderRequest:
        user = (
            "Read the document below and extract its claims as structured "
            "semantic state.\n\n"
            f"DOCUMENT:\n{self.input_text}\n\n"
            f"{_SCHEMA_HINT}"
        )
        return ProviderRequest(
            system=(
                "You build shared semantic state for an auditable reasoning "
                "engine. Emit only the JSON object requested — every claim must "
                "carry a verbatim supporting quote."
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
        """Ask the model for an extraction, then assemble a full extract patch.

        On output this operator cannot assemble we return the model's raw text
        plus a repair hint, so the runtime's retry loop asks for the shape this
        operator actually wants rather than the one the validator inferred.

        One case needs care. The runtime decides by validating the text it gets
        back, so raw output that *is* a well-formed patch would be committed
        however the operator judged it — silently undoing a provenance
        rejection on the passthrough path. Such output is therefore returned
        wrapped: still verbatim, still the record of what the model proposed,
        but no longer mistakable for a proposal the operator accepted.
        """
        view = resolve_view(projection, state)
        response = self.provider.complete(self.build_request(view, feedback))
        try:
            patch = self._assemble(state, response.text)
        except ExtractionError as exc:
            return OperatorCompletion(
                text=_rejected_completion(response.text, str(exc)),
                fingerprint=response.fingerprint,
                usage=response.usage,
                repair_hint=str(exc),
            )
        return OperatorCompletion(
            text=patch.model_dump_json(by_alias=True),
            fingerprint=response.fingerprint,
            usage=response.usage,
        )

    # -- assembly ---------------------------------------------------------

    def _is_this_document(self, item: Evidence) -> bool:
        """Does this `Evidence` claim to come from the document we were given?

        Either it names the source type the caller declared, or it uses the
        vocabulary the pipeline wrote before source types existed. Anything
        else names a source we were not handed and cannot speak for.
        """
        return item.source_type in (self.source_type.value, LEGACY_INPUT_DOCUMENT)

    def _ground_patch_claims(self, patch: SemanticPatch) -> None:
        """Hold a model-authored patch to the reading rule too (T17).

        The assembled path grounds every status it builds; a patch that arrives
        fully formed would otherwise commit `observed` on the strength of
        having read a press release. Correcting it here closes the same second
        way in that T8 and T14 had to close.
        """
        for claim in patch.add_objects.claims:
            claim.epistemic_status = ground_status(claim.epistemic_status)

    def _verify_patch_evidence(self, patch: SemanticPatch) -> None:
        """Hold a model-authored patch to the same rules (T8, T14).

        A patch that arrives fully formed skips the assembly loop, so its
        `Evidence` would otherwise reach committed state as a citation without
        anyone checking it against the document. Locatable spans are stamped
        with their offsets, exactly as the assembled path does; unlocatable ones
        raise, so the runtime retries with the same repair hint.

        Reliability and declared lineage are overwritten for the same reason
        they are derived on the assembled path: both are facts about the source,
        which the caller declared and the model does not get a vote on. A patch
        that arrives asserting `high` for its own extraction must not keep it —
        that is precisely the self-promotion this route would otherwise leave
        open, and an unasked-for `derives_from: null` would buy independence the
        same way.
        """
        unlocatable: list[str] = []
        for item in patch.add_objects.evidence:
            # Only spans claiming to come from *this* document are ours.
            if not self._is_this_document(item):
                continue
            item.source_type = self.source_type.value
            item.reliability = self.reliability
            # Declared lineage is overwritten for exactly the reason reliability
            # is: it is the caller's fact about this document, and a patch that
            # arrives asserting its own independence must not keep it.
            item.derives_from = self.derives_from
            quote = (item.quote_or_span or "").strip()
            if not quote:
                continue
            span = locate_span(quote, self.input_text)
            if span is None:
                unlocatable.append(quote)
            else:
                item.location = {"start": span.start, "end": span.end}

        if unlocatable:
            raise ExtractionError(_unlocatable_message(unlocatable))

    def _assemble(self, state: SemanticState, raw: str) -> SemanticPatch:
        data = load_json(raw)
        # If the model already emitted a full patch, trust the validator with the
        # patch *shape* — but not with its citations. The validator never sees
        # the source document, so provenance is checked here on both paths.
        if isinstance(data, dict) and ("add_objects" in data or "patch_id" in data):
            patch = SemanticPatch.model_validate(data)
            self._verify_patch_evidence(patch)
            self._ground_patch_claims(patch)
            return patch

        if not isinstance(data, dict) or not isinstance(data.get("claims"), list):
            raise ExtractionError(
                'Your output must be a JSON object with a "claims" array.'
            )
        raw_claims = [c for c in data["claims"] if isinstance(c, dict)]
        if not raw_claims:
            raise ExtractionError(
                'Your "claims" array was empty — extract at least one claim '
                "from the document."
            )

        now = self.clock.now()
        claims: list[Claim] = []
        evidence: list[Evidence] = []
        unlocatable: list[str] = []
        assumptions: list[Assumption] = []
        assumption_ids: dict[str, str] = {}
        write_set: list[str] = []

        for i, rc in enumerate(raw_claims, start=1):
            cid = f"{self.id_prefix}claim_{i:03d}"
            supporting: list[str] = []
            quote = (rc.get("evidence_quote") or "").strip()
            if quote:
                # A citation the document does not contain is the one failure
                # this operator must never commit: the memo renders it as
                # provenance. Collect every offender so one retry can fix them
                # all, rather than surfacing them one attempt at a time.
                span = locate_span(quote, self.input_text)
                if span is None:
                    unlocatable.append(quote)
                else:
                    eid = f"{self.id_prefix}ev_{i:03d}"
                    evidence.append(
                        Evidence(
                            id=eid,
                            source_type=self.source_type.value,
                            source_id=self.source_id,
                            quote_or_span=quote,
                            location={"start": span.start, "end": span.end},
                            reliability=self.reliability,
                            derives_from=self.derives_from,
                            extracted_by=self.transform_id,
                        )
                    )
                    supporting.append(eid)
                    write_set.append(eid)

            claim_assumptions: list[str] = []
            atext = (rc.get("assumption") or "").strip() if rc.get("assumption") else ""
            if atext:
                aid = assumption_ids.get(atext)
                if aid is None:
                    aid = f"{self.id_prefix}assumption_{len(assumption_ids) + 1:03d}"
                    assumption_ids[atext] = aid
                    assumptions.append(
                        Assumption(
                            id=aid,
                            text=atext,
                            confidence=0.5,
                            impact=coerce_enum(
                                rc.get("assumption_impact"), _IMPACT, Impact.MEDIUM
                            ),
                            extracted_by=self.transform_id,
                        )
                    )
                    write_set.append(aid)
                claim_assumptions.append(aid)

            text = (rc.get("text") or "").strip()
            if not text:
                raise ExtractionError(
                    f'Claim {i} has no "text" field — every claim needs one.'
                )
            claims.append(
                Claim(
                    id=cid,
                    text=text,
                    claim_type=coerce_enum(
                        rc.get("claim_type"), _CLAIM_TYPES, ClaimType.ANALYTICAL
                    ),
                    epistemic_status=ground_status(
                        coerce_enum(
                            rc.get("epistemic_status"),
                            _EPISTEMIC,
                            EpistemicStatus.REPORTED,
                        )
                    ),
                    confidence=clamp_confidence(rc.get("confidence")),
                    supporting_evidence=supporting,
                    assumptions=claim_assumptions,
                    extracted_by=self.transform_id,
                )
            )
            write_set.append(cid)

        if unlocatable:
            raise ExtractionError(_unlocatable_message(unlocatable))

        transform_record = TransformRecord(
            id=self.transform_id,
            transform_type="extract",
            operator=self.name,
            operator_version=self.fully_qualified(),
            input_state_version=state.state_version,
            output_state_version=None,
            read_set=[],
            write_set=write_set,
            confidence_changes=[],
            started_at=now,
            finished_at=now,
            notes="LLM extraction assembled into a canonical extract patch.",
        )
        return SemanticPatch(
            patch_id=self.patch_id,
            base_state_id=state.state_id,
            base_state_version=state.state_version,
            proposed_by=self.fully_qualified(),
            created_at=now,
            read_set=[],
            add_objects=AddObjects(
                claims=claims, evidence=evidence, assumptions=assumptions
            ),
            transform_record=transform_record,
            status=PatchStatus.PROPOSED,
        )


__all__ = ["ExtractionError", "LLMExtractOperator"]
