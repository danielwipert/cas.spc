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

**The rule is weakest-link**, because a recommendation is only as good as the
shakiest thing it depends on. Averaging would let four restatements of a press
release outvote the one claim that was actually questioned, which is backwards:

    ceiling(h) = min over c in h.supporting_claims of
                     c.confidence * reliability_factor(c)

where `reliability_factor` is taken from the *best* evidence the claim cites —
one solid source is enough to ground a claim, so the strongest span wins,
where across claims the weakest wins.

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

from ..models import (
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


def claim_support(claim_id: str, view: ProjectionView) -> float:
    """What one supporting claim contributes to a hypothesis's ceiling.

    The claim's own confidence, discounted by the best evidence it cites. A
    claim the operator cannot resolve in its projection contributes 0.0: a
    recommendation citing something that is not in committed state is, on that
    limb, grounded in nothing.
    """
    claim = view.claims.get(claim_id)
    if claim is None:
        return 0.0

    factors = [
        RELIABILITY_FACTOR[e.reliability]
        for eid in claim.supporting_evidence
        if (e := view.evidence.get(eid)) is not None
    ]
    # One solid source is enough to ground a claim, so the *best* span wins
    # here — where across claims the *weakest* wins.
    return claim.confidence * (max(factors) if factors else _UNSOURCED_FACTOR)


def ceiling_for(hypothesis: Hypothesis, view: ProjectionView) -> float:
    """The most confidence `hypothesis` can carry, given what it rests on.

    A hypothesis citing no claims at all gets 0.0 — a recommendation grounded
    in nothing should not read as a finding.
    """
    if not hypothesis.supporting_claims:
        return 0.0
    return _floor2(
        min(claim_support(cid, view) for cid in hypothesis.supporting_claims)
    )


def _reason(hypothesis: Hypothesis, view: ProjectionView, ceiling: float) -> str:
    """Why this hypothesis was capped, naming the claim that bound it."""
    if not hypothesis.supporting_claims:
        return (
            f"Capped at {ceiling:.2f}: this recommendation cites no supporting "
            "claims, so nothing in committed state grounds it."
        )

    binding = min(hypothesis.supporting_claims, key=lambda cid: claim_support(cid, view))
    claim = view.claims.get(binding)
    if claim is None:
        return (
            f"Capped at {ceiling:.2f}: it rests on {binding}, which is not in "
            "committed state."
        )

    # The same span that set the factor — the best one the claim cites.
    reliabilities = [
        e.reliability
        for eid in claim.supporting_evidence
        if (e := view.evidence.get(eid)) is not None
    ]
    if reliabilities:
        best = max(reliabilities, key=lambda r: RELIABILITY_FACTOR[r])
        support = f"{best.value}-reliability evidence"
    else:
        support = "no evidence on record"
    return (
        f"Capped at {ceiling:.2f}: it rests on {binding} "
        f"(confidence {claim.confidence:.2f}, {support}), and a recommendation "
        "is no stronger than the weakest claim it cites."
    )


class CalibrationOperator(Operator):
    """Lower any hypothesis that claims more confidence than its support."""

    name = "calibration_transform"
    version = "0.1.0"
    # "Claim/evidence alignment, provenance, **confidence sanity**" — the
    # projection's own description of the verifier slice (PILOT_SPEC §14.2).
    perspective = Perspective.VERIFIER
    goal = (
        "Hold each recommendation to the confidence its supporting claims and "
        "their evidence can carry."
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
        view = resolve_view(projection, state)
        started = self.clock.now()

        updates: list[UpdateObject] = []
        changes: list[ConfidenceChange] = []
        write_set: list[str] = []
        read_set: set[str] = set(view.hypotheses)

        for hid in sorted(view.hypotheses):
            hypothesis = view.hypotheses[hid]
            read_set.update(hypothesis.supporting_claims)
            for cid in hypothesis.supporting_claims:
                claim = view.claims.get(cid)
                if claim is not None:
                    read_set.update(claim.supporting_evidence)

            ceiling = ceiling_for(hypothesis, view)
            if hypothesis.confidence <= ceiling:
                continue  # already within what its support can carry

            payload = {
                "object_id": hid,
                "from": hypothesis.confidence,
                "to": ceiling,
                "reason": _reason(hypothesis, view, ceiling),
            }
            updates.append(
                UpdateObject.model_validate({"field": "confidence", **payload})
            )
            changes.append(ConfidenceChange.model_validate(payload))
            write_set.append(hid)

        finished = self.clock.now()
        # Only ids actually in the slice: a dangling `supporting_claims` entry
        # must not smuggle an unresolvable id into the read set.
        resolved_reads = sorted(
            read_set & (set(view.hypotheses) | set(view.claims) | set(view.evidence))
        )
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
            notes=f"Capped {len(updates)} recommendation(s) to their support.",
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


__all__ = ["RELIABILITY_FACTOR", "CalibrationOperator", "ceiling_for", "claim_support"]
