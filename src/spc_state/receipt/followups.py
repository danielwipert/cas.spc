"""Answer the spec §8.4 demo follow-up questions from state, not by re-prompting.

This is the Phase 4 exit gate (ROADMAP §4): the SPC engine answers the demo
follow-ups directly from committed `SemanticState` versions and their
`transform_log`. A baseline LLM would have to reconstruct from conversation
history or rerun analysis; here every answer is a read over durable state.

`FollowUps` is constructed from the ordered state history (`v0 … vN`). Each
method returns a small result carrying both a human-readable `text` and the
structured ids it was derived from, so callers can render or assert on either.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..diff import StateDiff, diff_states
from ..models import EpistemicStatus, Impact, ObjectStatus, QuestionStatus, SemanticState

_IMPACT_RANK = {Impact.HIGH: 0, Impact.MEDIUM: 1, Impact.LOW: 2}


@dataclass(frozen=True)
class OperatorContribution:
    operator: str
    added_object_ids: list[str]
    confidence_changes: list[tuple[str, float, float]]  # (object_id, from, to)
    text: str


@dataclass(frozen=True)
class RankedClaims:
    claim_ids: list[str]
    text: str


@dataclass(frozen=True)
class AssumptionImpact:
    assumption_id: str
    impact: str
    dependent_claim_ids: list[str]


@dataclass(frozen=True)
class AssumptionSensitivity:
    assumptions: list[AssumptionImpact]
    text: str


@dataclass(frozen=True)
class SourceSupport:
    claim_id: str
    evidence_ids: list[str]
    text: str


@dataclass(frozen=True)
class QuestionList:
    question_ids: list[str]
    text: str


@dataclass(frozen=True)
class DiffAnswer:
    diff: StateDiff
    text: str


@dataclass(frozen=True)
class DependencyAnswer:
    assumption_id: str
    dependent_object_ids: list[str]
    text: str


class FollowUps:
    """Programmatic answers to PILOT_SPEC.md §8.4, read from state history."""

    def __init__(self, states: list[SemanticState]) -> None:
        if not states:
            raise ValueError("FollowUps needs at least one SemanticState version.")
        # Index by state_version so callers can ask about "v1" directly.
        self._by_version: dict[int, SemanticState] = {s.state_version: s for s in states}
        self.final = max(states, key=lambda s: s.state_version)

    def state(self, version: int) -> SemanticState:
        try:
            return self._by_version[version]
        except KeyError as exc:  # pragma: no cover - defensive
            raise KeyError(f"No state version {version} in history.") from exc

    # -- "What did the critic add?" ---------------------------------------

    def what_did_operator_add(self, operator: str) -> OperatorContribution:
        """Objects written and confidence changes made by a named operator.

        Reads `transform_log`: each record names its `operator`, `write_set`,
        and `confidence_changes`. No model call.
        """
        added: list[str] = []
        changes: list[tuple[str, float, float]] = []
        for rec in self.final.transform_log:
            if rec.operator != operator:
                continue
            added.extend(rec.write_set)
            for cc in rec.confidence_changes:
                changes.append((cc.object_id, cc.from_value, cc.to_value))

        added = sorted(dict.fromkeys(added))
        if added or changes:
            parts = []
            if added:
                parts.append("added " + ", ".join(added))
            for oid, frm, to in changes:
                parts.append(f"changed {oid} confidence {frm:.2f}→{to:.2f}")
            text = f"{operator} " + "; ".join(parts) + "."
        else:
            text = f"{operator} made no recorded contributions."
        return OperatorContribution(operator, added, changes, text)

    # -- "Which claims are weakest?" --------------------------------------

    def weakest_claims(self, limit: int | None = None) -> RankedClaims:
        """Active claims ordered by ascending confidence, then evidence count."""
        active = [
            (cid, c)
            for cid, c in self.final.claims.items()
            if c.status == ObjectStatus.ACTIVE
        ]
        ranked = sorted(
            active,
            key=lambda kv: (kv[1].confidence, len(kv[1].supporting_evidence), kv[0]),
        )
        ids = [cid for cid, _ in ranked]
        if limit is not None:
            ids = ids[:limit]
        text = "Weakest claims (low confidence first): " + (
            ", ".join(
                f"{cid} ({self.final.claims[cid].confidence:.2f})" for cid in ids
            )
            or "none"
        )
        return RankedClaims(ids, text)

    # -- "Which assumptions most affect the conclusion?" ------------------

    def assumptions_affecting_conclusion(self) -> AssumptionSensitivity:
        """Assumptions ranked by impact, with the claims that depend on them."""
        dep: dict[str, set[str]] = {}
        for cid, c in self.final.claims.items():
            for aid in c.assumptions:
                dep.setdefault(aid, set()).add(cid)
        for rel in self.final.relations:
            if rel.predicate == "depends_on" and rel.target in self.final.assumptions:
                dep.setdefault(rel.target, set()).add(rel.source)

        items = sorted(
            self.final.assumptions.values(),
            key=lambda a: (_IMPACT_RANK.get(a.impact, 1), -a.confidence, a.id),
        )
        out = [
            AssumptionImpact(
                assumption_id=a.id,
                impact=a.impact.value,
                dependent_claim_ids=sorted(dep.get(a.id, set())),
            )
            for a in items
        ]
        text = "Assumptions by impact: " + (
            "; ".join(
                f"{ai.assumption_id} ({ai.impact}) → "
                + (", ".join(ai.dependent_claim_ids) or "no dependents")
                for ai in out
            )
            or "none"
        )
        return AssumptionSensitivity(out, text)

    # -- "Which source supports this claim?" ------------------------------

    def source_supporting_claim(self, claim_id: str) -> SourceSupport:
        claim = self.final.claims.get(claim_id)
        ev_ids = list(claim.supporting_evidence) if claim else []
        if claim is None:
            text = f"No claim {claim_id} in state."
        elif ev_ids:
            text = f"{claim_id} is supported by: " + ", ".join(ev_ids)
        else:
            text = f"{claim_id} cites no evidence (epistemic status: {claim.epistemic_status.value})."
        return SourceSupport(claim_id, ev_ids, text)

    # -- "What changed between state v1 and state v3?" --------------------

    def changes_between(self, from_version: int, to_version: int) -> DiffAnswer:
        diff = diff_states(self.state(from_version), self.state(to_version))
        text = (
            f"v{from_version}→v{to_version}: "
            f"+{diff.total_added} added, "
            f"~{diff.total_changed} changed, "
            f"-{diff.total_removed} removed."
        )
        return DiffAnswer(diff, text)

    # -- "Which unresolved questions remain?" -----------------------------

    def unresolved_questions(self) -> QuestionList:
        open_states = {QuestionStatus.OPEN, QuestionStatus.IN_PROGRESS}
        ids = sorted(
            qid for qid, q in self.final.questions.items() if q.status in open_states
        )
        text = "Unresolved questions: " + (", ".join(ids) or "none")
        return QuestionList(ids, text)

    # -- "Which recommendation depends on the <X> assumption?" ------------

    def recommendation_dependencies(self, assumption_id: str) -> DependencyAnswer:
        """Hypotheses/claims that depend on a given assumption.

        Traces both `claim.assumptions` and `depends_on` relations, then maps
        forward to any hypothesis whose supporting_claims include a dependent
        claim.
        """
        dependents: set[str] = set()
        for cid, c in self.final.claims.items():
            if assumption_id in c.assumptions:
                dependents.add(cid)
        for rel in self.final.relations:
            if rel.predicate == "depends_on" and rel.target == assumption_id:
                dependents.add(rel.source)

        for hid, h in self.final.hypotheses.items():
            if dependents & set(h.supporting_claims):
                dependents.add(hid)

        ids = sorted(dependents)
        text = (
            f"Objects depending on {assumption_id}: " + (", ".join(ids) or "none")
        )
        return DependencyAnswer(assumption_id, ids, text)

    # -- "Which claims were inferred rather than observed?" ---------------

    def claims_by_status(self, status: EpistemicStatus) -> RankedClaims:
        ids = sorted(
            cid
            for cid, c in self.final.claims.items()
            if c.epistemic_status == status and c.status == ObjectStatus.ACTIVE
        )
        text = f"Claims with epistemic status '{status.value}': " + (
            ", ".join(ids) or "none"
        )
        return RankedClaims(ids, text)


__all__ = [
    "AssumptionImpact",
    "AssumptionSensitivity",
    "DependencyAnswer",
    "DiffAnswer",
    "FollowUps",
    "OperatorContribution",
    "QuestionList",
    "RankedClaims",
    "SourceSupport",
]
