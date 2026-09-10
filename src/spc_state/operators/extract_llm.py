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

The model is asked for a compact extraction schema rather than a full
`SemanticPatch`, because the patch envelope is exactly the error-prone part a
model should not be hand-writing. If the model returns prose, malformed JSON,
or already-formed patch JSON, the cases are handled: prose/garbage falls
through to the validator (JSON_DECODE -> RETRY with feedback); a full patch is
passed through untouched.
"""

from __future__ import annotations

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
    Reliability,
    SemanticPatch,
    SemanticState,
    TransformRecord,
)
from ..models.patch import AddObjects
from ..projection import ProjectionView, resolve_view
from ..provenance import locate_span
from ..providers import LLMProvider, ProviderRequest
from ..runtime.clock import Clock, WallClock
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
      "epistemic_status": "observed | inferred | assumed | speculative",
      "confidence": 0.0 to 1.0,
      "evidence_quote": "the exact span from the document that supports this claim",
      "evidence_reliability": "low | medium | high",
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
_RELIABILITY = {r.value: r for r in Reliability}
_IMPACT = {i.value: i for i in Impact}


def _shorten(quote: str, limit: int = 80) -> str:
    """A quote short enough to echo back in a repair hint."""
    collapsed = " ".join(quote.split())
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[: limit - 3] + "..."


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
    ) -> None:
        super().__init__(provider, max_attempts=max_attempts)
        self.input_text = input_text
        self.clock = clock or WallClock()
        self.patch_id = patch_id
        self.transform_id = transform_id
        self.source_id = source_id

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
        """
        view = resolve_view(projection, state)
        response = self.provider.complete(self.build_request(view, feedback))
        try:
            patch = self._assemble(state, response.text)
        except ExtractionError as exc:
            return OperatorCompletion(
                text=response.text,
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

    def _assemble(self, state: SemanticState, raw: str) -> SemanticPatch:
        data = load_json(raw)
        # If the model already emitted a full patch, trust the validator with it.
        if isinstance(data, dict) and ("add_objects" in data or "patch_id" in data):
            return SemanticPatch.model_validate(data)

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
            cid = f"claim_{i:03d}"
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
                    eid = f"ev_{i:03d}"
                    evidence.append(
                        Evidence(
                            id=eid,
                            source_type="input_document",
                            source_id=self.source_id,
                            quote_or_span=quote,
                            location={"start": span.start, "end": span.end},
                            reliability=coerce_enum(
                                rc.get("evidence_reliability"),
                                _RELIABILITY,
                                Reliability.MEDIUM,
                            ),
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
                    aid = f"assumption_{len(assumption_ids) + 1:03d}"
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
                    epistemic_status=coerce_enum(
                        rc.get("epistemic_status"), _EPISTEMIC, EpistemicStatus.INFERRED
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
