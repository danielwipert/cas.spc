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

import json
from typing import Any

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
from ..providers import LLMProvider, ProviderRequest, ProviderResponse
from ..runtime.clock import Clock, WallClock
from .llm import LLMOperator

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
- `evidence_quote` must be copied verbatim from the document.
- Use `assumption` only for something the document does not establish but the
  claim relies on; otherwise null.
- No prose, no markdown fences — only the JSON object."""


class ExtractionError(ValueError):
    """The model output could not be assembled into an extract patch."""


def _coerce_enum(value: Any, mapping: dict[str, Any], default: Any) -> Any:
    """Map a loose model string onto an enum, tolerating case and synonyms."""
    if not isinstance(value, str):
        return default
    key = value.strip().lower()
    return mapping.get(key, default)


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


def _confidence(value: Any) -> float:
    try:
        c = float(value)
    except (TypeError, ValueError):
        return 0.5
    return max(0.0, min(1.0, c))


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
    ) -> ProviderResponse:
        """Ask the model for an extraction, then assemble a full extract patch.

        On unparseable output we return the model's raw text so the runtime's
        validator reports `JSON_DECODE` and the retry loop kicks in.
        """
        view = resolve_view(projection, state)
        response = self.provider.complete(self.build_request(view, feedback))
        try:
            patch = self._assemble(state, response.text)
            text = patch.model_dump_json(by_alias=True)
        except ExtractionError:
            text = response.text
        return ProviderResponse(text=text, fingerprint=response.fingerprint)

    # -- assembly ---------------------------------------------------------

    def _assemble(self, state: SemanticState, raw: str) -> SemanticPatch:
        data = _load_json(raw)
        # If the model already emitted a full patch, trust the validator with it.
        if isinstance(data, dict) and ("add_objects" in data or "patch_id" in data):
            return SemanticPatch.model_validate(data)

        if not isinstance(data, dict) or not isinstance(data.get("claims"), list):
            raise ExtractionError("Expected a JSON object with a 'claims' array.")
        raw_claims = [c for c in data["claims"] if isinstance(c, dict)]
        if not raw_claims:
            raise ExtractionError("No claims found in the extraction.")

        now = self.clock.now()
        claims: list[Claim] = []
        evidence: list[Evidence] = []
        assumptions: list[Assumption] = []
        assumption_ids: dict[str, str] = {}
        write_set: list[str] = []

        for i, rc in enumerate(raw_claims, start=1):
            cid = f"claim_{i:03d}"
            supporting: list[str] = []
            quote = (rc.get("evidence_quote") or "").strip()
            if quote:
                eid = f"ev_{i:03d}"
                evidence.append(
                    Evidence(
                        id=eid,
                        source_type="input_document",
                        source_id=self.source_id,
                        quote_or_span=quote,
                        reliability=_coerce_enum(
                            rc.get("evidence_reliability"), _RELIABILITY, Reliability.MEDIUM
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
                            impact=_coerce_enum(
                                rc.get("assumption_impact"), _IMPACT, Impact.MEDIUM
                            ),
                            extracted_by=self.transform_id,
                        )
                    )
                    write_set.append(aid)
                claim_assumptions.append(aid)

            text = (rc.get("text") or "").strip()
            if not text:
                raise ExtractionError(f"Claim {i} has no text.")
            claims.append(
                Claim(
                    id=cid,
                    text=text,
                    claim_type=_coerce_enum(
                        rc.get("claim_type"), _CLAIM_TYPES, ClaimType.ANALYTICAL
                    ),
                    epistemic_status=_coerce_enum(
                        rc.get("epistemic_status"), _EPISTEMIC, EpistemicStatus.INFERRED
                    ),
                    confidence=_confidence(rc.get("confidence")),
                    supporting_evidence=supporting,
                    assumptions=claim_assumptions,
                    extracted_by=self.transform_id,
                )
            )
            write_set.append(cid)

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


def _load_json(raw: str) -> Any:
    """Parse JSON, tolerating a ```json fenced block the model may emit."""
    text = raw.strip()
    if text.startswith("```"):
        # Drop the opening fence line and any trailing fence.
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError) as exc:
        raise ExtractionError(f"Output was not valid JSON: {exc}") from exc


__all__ = ["ExtractionError", "LLMExtractOperator"]
