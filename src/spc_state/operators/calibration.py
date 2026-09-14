"""Calibration — hold a recommendation to what it rests on (T15).

The Planner commits a `Hypothesis` — the recommendation the Decision Memo
opens with — at a confidence the model chose. Nothing then checked it. The
Critic runs next and adjusts *claims*, but the `CRITIC` projection carries no
hypotheses at all, so the recommendation was the one object in committed state
no operator ever scrutinised. Two consequences, both structural:

- **Its confidence went stale precisely when the Critic did its job.** On the
  recorded Paramount/WBD run the Critic lowered `claim_006` from 0.80 to 0.65,
  noting "$6 billion in synergies is a high estimate" — and the recommendation
  citing that claim stayed at 90%.
- **Nothing ever related it to its support.** The same memo flagged all ten of
  its findings *Weakly supported* (T14, every span a low-reliability press
  release) and still opened at 90%.

So this operator re-derives a ceiling from the committed support and proposes
lowering any hypothesis that sits above it. It is deterministic — no model, no
cost, identical on replay — in the mould of `RetrieverOperator`, and like every
operator it proposes a `SemanticPatch` rather than touching state.

Since T16 it does the same for **claims**, one layer down and for the same
reason. The extractor set `Claim.confidence` itself, and across five real runs
32 of 48 claims committed at exactly **1.00**; in every cassette the claims
marked `observed` and the claims at 1.00 were the *same set*. The model was
reading "I can quote this" as "this is certain" — but a verbatim span
establishes that the **document says so**, which is a fact about the document.
So a claim is damped by the source under it before anything reads it.

**The rule is weakest-link**, because a recommendation is only as good as the
shakiest thing it depends on. Averaging would let four restatements of a press
release outvote the one claim that was actually questioned, which is backwards:

    ceiling(c) = c.confidence * min(reliability_factor(c), grounding_factor(c))
    ceiling(h) = min over c in h.supporting_claims of ceiling(c)

where `reliability_factor` is taken from the *best* evidence the claim cites —
one solid source is enough to ground a claim, so the strongest span wins,
where across claims the weakest wins.

`grounding_factor` is T21, and it closes the hole the other one leaves open at
the top. `RELIABILITY_FACTOR[HIGH]` is 1.0, so a claim citing an accountable
source was discounted by nothing at all: a live run over two SEC filings
committed **17 of 17 claims at 1.00** and recommended proceeding with a
contested merger at **100%** — a higher number than the press release that
started this whole arc ever produced. A filing is accountable for *"we signed
this contract"*; it is not a warrant for certainty about what happens next. So
a `REPORTED` claim carries at most 0.9 however good its source, which is T17's
rule — reading is not observing — finally reaching the number rather than only
the label. The two factors combine by **min**, not by product: see
`claim_factor`.

**It is a discount, not a ceiling**, and that is deliberate. The factor scales
a claim's confidence rather than clipping it at a maximum, so a claim stated at
0.40 on a press release carries 0.24 — not 0.40 on the grounds that it was
already below 0.60. The two numbers measure independent things: the model's
confidence is about the *content* ("will these synergies materialise?"), and
the factor is about the *source* ("who is telling us, and do they benefit?").
A company's own estimate of an uncertain outcome deserves less weight than a
disinterested party's identical estimate, so the discounts compose. The cost is
that every claim from a non-`HIGH` source moves, not only the overconfident
ones; the benefit is that the factor keeps the single meaning it is documented
with, at both layers.

**The damping happens once**, at the claim. Before T16 the hypothesis ceiling
multiplied by the reliability factor itself; now the claims it reads have
already been damped, so it takes their minimum and stops. Applying the factor
in both places would discount a press-release recommendation twice
(0.6 x 0.6 = 0.36) — not a considered position, just two rules meeting by
accident. Composed this way the committed recommendation is **arithmetically
identical** to what T15 alone produced; what is new is that the claims'
own numbers are corrected, and recorded, too.

Two rules hold whatever the constants become:

- **It only ever lowers.** Raising a confidence because the support looks
  strong would be inventing certainty, which is the failure mode this exists to
  fix. A hypothesis at or below its ceiling is left alone.
- **Every change is recorded** as an `UpdateObject` plus a matching
  `ConfidenceChange`, with a reason naming the claim that bound it — the same
  mechanism the Critic uses. A number that moves without a reason in the
  receipt is the thing this repo exists not to do.

The factors below are a documented starting point, not a result. They are
pinned in `tests/test_calibration.py`, so changing one is a deliberate edit
rather than a drift.
"""

from __future__ import annotations

import math
from collections.abc import Mapping

from ..models import (
    Claim,
    EpistemicStatus,
    Hypothesis,
    PatchStatus,
    Perspective,
    Projection,
    Reliability,
    SemanticPatch,
    SemanticState,
    TransformRecord,
)
from ..models.patch import UpdateObject
from ..models.transform import ConfidenceChange
from ..projection import resolve_view
from ..projection.view import ProjectionView
from ..runtime.clock import Clock, WallClock
from .base import Operator

#: How much of a claim's confidence survives the evidence under it. A claim is
#: no more believable than where it came from: `HIGH` carries it intact, and
#: the lower tiers discount it. Deliberately gentle — this damps a
#: recommendation, it does not veto one.
RELIABILITY_FACTOR: dict[Reliability, float] = {
    Reliability.HIGH: 1.0,
    Reliability.MEDIUM: 0.8,
    Reliability.LOW: 0.6,
}

#: How much of a claim's confidence survives **how it entered state** (T21).
#:
#: T17 established that reading a document establishes *that the document says
#: so*, never that the thing is so, and made every extracted claim `REPORTED`.
#: That rule never reached the number: because `RELIABILITY_FACTOR[HIGH]` is
#: 1.0, a claim citing an accountable source was discounted by nothing, and a
#: run over two SEC filings committed **17 of 17 claims at 1.00** and
#: recommended "Proceed with the merger" at **100%** — on a transaction then
#: facing a hostile counter-bid, a proxy contest, regulatory clearance and a
#: shareholder vote. A filing is an excellent source for *"we signed this
#: contract"*. It is not a licence to be certain about the future.
#:
#: So a reported claim cannot reach certainty however accountable its source.
#: `0.9` is a pinned constant with no principled derivation, exactly as the
#: `RELIABILITY_FACTOR` values are: it removes certainty without pretending to
#: model the risk of the thing not happening, and leaves a filing meaningfully
#: stronger than the `MEDIUM` 0.8 it would otherwise collapse toward. Changing
#: it should be a deliberate edit, so it is pinned by a test.
#:
#: Every other status is 1.0, and that is a decision rather than an oversight.
#: `OBSERVED` is first-hand, so nothing about *reading* discounts it.
#: `INFERRED` draws its warrant from its premises, which carry their own caps.
#: `ASSUMED` and `SPECULATIVE` already say out loud that nothing supports them.
#: The table is exhaustive on purpose: adding a member to `EpistemicStatus`
#: should force a decision here rather than silently default.
GROUNDING_FACTOR: dict[EpistemicStatus, float] = {
    EpistemicStatus.OBSERVED: 1.0,
    EpistemicStatus.REPORTED: 0.9,
    EpistemicStatus.INFERRED: 1.0,
    EpistemicStatus.ASSUMED: 1.0,
    EpistemicStatus.SPECULATIVE: 1.0,
}

#: A claim citing no evidence at all is treated as the lowest tier rather than
#: as zero. "Unsourced" is not more misleading than "sourced to an interested
#: party", which is the most three buckets can honestly express — and the
#: Retriever already opens a *high* priority gap for exactly these claims, so
#: they are not going unremarked.
_UNSOURCED_FACTOR = RELIABILITY_FACTOR[Reliability.LOW]

#: Confidences are rounded to two places, always **down**. A ceiling carried to
#: seventeen significant digits claims a precision nobody has, and flooring
#: means the rounding never resolves in the recommendation's favour. The
#: epsilon absorbs binary representation error (0.7 * 0.8 is 0.5599999…, which
#: is 0.56 and not 0.55) without letting a genuine value round up.
_PLACES = 100
_EPSILON = 1e-9


def _floor2(value: float) -> float:
    """`value` rounded down to two decimal places."""
    return math.floor(value * _PLACES + _EPSILON) / _PLACES


def best_reliability(claim: Claim, view: ProjectionView) -> Reliability | None:
    """The strongest source `claim` cites, or `None` if it cites none.

    One solid source is enough to ground a claim, so the *best* span wins here
    — where across claims the *weakest* wins.
    """
    reliabilities = [
        e.reliability
        for eid in claim.supporting_evidence
        if (e := view.evidence.get(eid)) is not None
    ]
    if not reliabilities:
        return None
    return max(reliabilities, key=lambda r: RELIABILITY_FACTOR[r])


def claim_factor(claim: Claim, view: ProjectionView) -> tuple[float, str]:
    """The one factor that damps this claim, and which rule supplied it.

    Two things can limit a claim: the source it rests on (T14/T16) and the way
    it entered state (T17/T21). The **smaller** wins — deliberately `min` and
    not a product. T16 settled that a claim is damped *once*; multiplying two
    factors that never agreed to meet is the double discount it ruled out, and
    would drop a press-release claim from 0.60 to 0.54 for no considered reason.

    Under `min` nothing about T14–T16 moves: a `LOW` press release still caps at
    0.60, because 0.6 is already below the 0.9 a reported claim allows. Only the
    `HIGH` tier changes, which is the tier that was wrong.
    """
    best = best_reliability(claim, view)
    reliability = _UNSOURCED_FACTOR if best is None else RELIABILITY_FACTOR[best]
    grounding = GROUNDING_FACTOR[claim.epistemic_status]
    if grounding < reliability:
        return grounding, "grounding"
    return reliability, "source"


def claim_ceiling(claim: Claim, view: ProjectionView) -> float:
    """The most confidence `claim` can carry, given what it rests on.

    Its own confidence, discounted by whichever binds harder: the best evidence
    it cites, or the fact that it was only ever *read* rather than seen.
    """
    factor, _bound_by = claim_factor(claim, view)
    return _floor2(claim.confidence * factor)


def ceiling_for(hypothesis: Hypothesis, capped: Mapping[str, float]) -> float:
    """The most confidence `hypothesis` can carry, given what it rests on.

    `capped` holds each claim's confidence **after** its own cap, so the
    reliability discount is not applied a second time here. A claim missing
    from it is one the operator could not resolve, and contributes 0.0: a
    recommendation citing something that is not in committed state is, on that
    limb, grounded in nothing. A hypothesis citing no claims at all gets 0.0 —
    a recommendation grounded in nothing should not read as a finding.
    """
    if not hypothesis.supporting_claims:
        return 0.0
    return min(capped.get(cid, 0.0) for cid in hypothesis.supporting_claims)


def _source_phrase(claim: Claim, view: ProjectionView) -> str:
    """How to describe what a claim rests on, in a reason a human will read."""
    best = best_reliability(claim, view)
    return "no evidence on record" if best is None else f"{best.value}-reliability evidence"


def _claim_reason(claim: Claim, view: ProjectionView, ceiling: float) -> str:
    """Why this claim was discounted, naming the rule that bound it."""
    factor, bound_by = claim_factor(claim, view)
    if bound_by == "grounding":
        return (
            f"Discounted to {ceiling:.2f} from {claim.confidence:.2f}: a "
            f"{claim.epistemic_status.value} claim carries {factor:.0%} of its "
            "stated confidence however accountable its source. Reading a "
            "document establishes that the document says so, which is not the "
            "same as the thing being so — so no claim read out of one is "
            "certain."
        )
    return (
        f"Discounted to {ceiling:.2f} from {claim.confidence:.2f}: "
        f"{_source_phrase(claim, view)} carries {factor:.0%} of a claim's "
        "stated confidence. A claim is no more certain than the source it "
        "rests on — a document saying so establishes that the document says so."
    )


def _hypothesis_reason(
    hypothesis: Hypothesis,
    view: ProjectionView,
    capped: Mapping[str, float],
    ceiling: float,
) -> str:
    """Why this hypothesis was capped, naming the claim that bound it."""
    if not hypothesis.supporting_claims:
        return (
            f"Capped at {ceiling:.2f}: this recommendation cites no supporting "
            "claims, so nothing in committed state grounds it."
        )

    binding = min(hypothesis.supporting_claims, key=lambda cid: capped.get(cid, 0.0))
    claim = view.claims.get(binding)
    if claim is None:
        return (
            f"Capped at {ceiling:.2f}: it rests on {binding}, which is not in "
            "committed state."
        )
    return (
        f"Capped at {ceiling:.2f}: it rests on {binding} "
        f"(confidence {capped[binding]:.2f} once calibrated, on "
        f"{_source_phrase(claim, view)}), and a recommendation is no stronger "
        "than the weakest claim it cites."
    )


class CalibrationOperator(Operator):
    """Lower any claim or recommendation that outruns what it rests on."""

    name = "calibration_transform"
    version = "0.2.0"
    # "Claim/evidence alignment, provenance, **confidence sanity**" — the
    # projection's own description of the verifier slice (PILOT_SPEC §14.2).
    perspective = Perspective.VERIFIER
    goal = (
        "Hold each claim to the confidence its source can carry, and each "
        "recommendation to the confidence its claims can carry."
    )

    def __init__(
        self,
        *,
        clock: Clock | None = None,
        patch_id: str = "patch_006",
        transform_id: str = "transform_calibration_001",
    ) -> None:
        self.clock = clock or WallClock()
        self.patch_id = patch_id
        self.transform_id = transform_id

    def propose(self, state: SemanticState, projection: Projection) -> SemanticPatch:
        """Cap claims first, then read the capped values for the hypotheses.

        Order matters and is the whole of the "damp once" decision: the
        hypothesis ceiling is the minimum of what the claims carry *after*
        their own caps, so the reliability factor is applied exactly once on
        the way up.
        """
        view = resolve_view(projection, state)
        started = self.clock.now()

        updates: list[UpdateObject] = []
        changes: list[ConfidenceChange] = []
        write_set: list[str] = []
        read_set: set[str] = set(view.hypotheses)

        def cap(object_id: str, current: float, ceiling: float, reason: str) -> None:
            payload = {
                "object_id": object_id,
                "from": current,
                "to": ceiling,
                "reason": reason,
            }
            updates.append(
                UpdateObject.model_validate({"field": "confidence", **payload})
            )
            changes.append(ConfidenceChange.model_validate(payload))
            write_set.append(object_id)

        # 1. Claims: no more certain than the source each rests on (T16).
        capped: dict[str, float] = {}
        for cid in sorted(view.claims):
            claim = view.claims[cid]
            read_set.add(cid)
            read_set.update(claim.supporting_evidence)

            ceiling = claim_ceiling(claim, view)
            if claim.confidence <= ceiling:
                capped[cid] = claim.confidence
                continue
            capped[cid] = ceiling
            cap(cid, claim.confidence, ceiling, _claim_reason(claim, view, ceiling))

        # 2. Recommendations: no stronger than the weakest claim they cite (T15),
        #    read off the values step 1 just settled.
        for hid in sorted(view.hypotheses):
            hypothesis = view.hypotheses[hid]
            read_set.update(hypothesis.supporting_claims)

            ceiling = ceiling_for(hypothesis, capped)
            if hypothesis.confidence <= ceiling:
                continue  # already within what its support can carry
            cap(
                hid,
                hypothesis.confidence,
                ceiling,
                _hypothesis_reason(hypothesis, view, capped, ceiling),
            )

        finished = self.clock.now()
        # Only ids actually in the slice: a dangling `supporting_claims` entry
        # must not smuggle an unresolvable id into the read set.
        resolved_reads = sorted(
            read_set & (set(view.hypotheses) | set(view.claims) | set(view.evidence))
        )
        claims_capped = sum(1 for u in updates if u.object_id in view.claims)
        transform_record = TransformRecord(
            id=self.transform_id,
            transform_type="calibrate",
            operator=self.name,
            operator_version=self.fully_qualified(),
            input_state_version=state.state_version,
            output_state_version=None,
            read_set=resolved_reads,
            write_set=write_set,
            confidence_changes=changes,
            started_at=started,
            finished_at=finished,
            notes=(
                f"Capped {claims_capped} claim(s) to their source and "
                f"{len(updates) - claims_capped} recommendation(s) to their claims."
            ),
        )
        return SemanticPatch(
            patch_id=self.patch_id,
            base_state_id=state.state_id,
            base_state_version=state.state_version,
            proposed_by=self.fully_qualified(),
            created_at=finished,
            read_set=resolved_reads,
            update_objects=updates,
            transform_record=transform_record,
            status=PatchStatus.PROPOSED,
        )



__all__ = [
    "GROUNDING_FACTOR",
    "RELIABILITY_FACTOR",
    "CalibrationOperator",
    "best_reliability",
    "ceiling_for",
    "claim_ceiling",
    "claim_factor",
]
