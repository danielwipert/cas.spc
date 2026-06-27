"""Decision Memo: render committed semantic state into a stakeholder document.

The Writer (spec §8.3, §14.2) is a **terminal projector**, not an operator: it
reads committed `SemanticState` and emits a document — it proposes no patch and
mutates nothing. Like the Reasoning Receipt it is a *faithful projection*: it
can only say what the state already holds, and every finding carries an inline
citation back to the evidence span that supports it.

This is deliberately deterministic and template-driven rather than re-prompted
prose. The whole point of SPC is that conclusions don't drift between stages;
re-LLM'ing the memo would reintroduce exactly that drift. So the memo is a
projection of state, and its claims are anchored to sources by construction.

`render_memo(state, question=...)` returns Markdown; `write_memo(...)` persists
it to `runs/<id>/memo.md`.
"""

from __future__ import annotations

from pathlib import Path

from .models import ObjectStatus, Priority, QuestionStatus, SemanticState
from .projection.builder import is_weak_claim
from .store import RunPaths

_PRIORITY_RANK = {Priority.HIGH: 0, Priority.MEDIUM: 1, Priority.LOW: 2}


def _active(container: dict) -> dict:
    return {
        k: v
        for k, v in container.items()
        if getattr(v, "status", ObjectStatus.ACTIVE) != ObjectStatus.ARCHIVED
    }


def _evidence_labels(state: SemanticState) -> dict[str, str]:
    """Stable [E1], [E2], … labels for each evidence object, by id order."""
    return {eid: f"E{i}" for i, eid in enumerate(sorted(state.evidence), start=1)}


def _cite(evidence_ids: list[str], labels: dict[str, str]) -> str:
    tags = [f"[{labels[e]}]" for e in evidence_ids if e in labels]
    return (" " + "".join(tags)) if tags else ""


def _assumption_dependents(state: SemanticState) -> dict[str, set[str]]:
    """Map each assumption to the claims that depend on it (refs + relations)."""
    dep: dict[str, set[str]] = {}
    for cid, c in state.claims.items():
        for aid in c.assumptions:
            dep.setdefault(aid, set()).add(cid)
    for rel in state.relations:
        if rel.predicate == "depends_on" and rel.target in state.assumptions:
            dep.setdefault(rel.target, set()).add(rel.source)
    return dep


def render_memo(state: SemanticState, *, question: str = "Decision analysis") -> str:
    claims = _active(state.claims)
    evidence = _active(state.evidence)
    assumptions = _active(state.assumptions)
    questions = _active(state.questions)
    labels = _evidence_labels(state)
    dependents = _assumption_dependents(state)

    lines: list[str] = [
        f"# Decision Memo: {question}",
        "",
        f"_Projected from semantic state v{state.state_version} — "
        f"{len(claims)} claims, {len(evidence)} evidence spans, "
        f"{len(assumptions)} assumptions. Every finding cites its source; this "
        f"memo asserts nothing the state does not hold._",
        "",
    ]

    # -- Recommendation -------------------------------------------------------
    lines.append("## Recommendation")
    lines.append("")
    if state.hypotheses:
        lead = max(
            state.hypotheses.values(), key=lambda h: (h.confidence, h.id)
        )
        lines.append(f"**{lead.text}**")
        lines.append("")
        lines.append(f"_Confidence: {lead.confidence:.0%}._")
        if lead.supporting_claims:
            support = ", ".join(
                f"{cid}{_cite(claims[cid].supporting_evidence, labels)}"
                for cid in lead.supporting_claims
                if cid in claims
            )
            if support:
                lines.append("")
                lines.append(f"Rests on: {support}.")
    else:
        lines.append(
            "_No recommendation was synthesized — the planner did not commit a "
            "hypothesis. The findings below still stand on their own evidence._"
        )
    lines.append("")

    # -- Key findings ---------------------------------------------------------
    lines.append("## Key findings")
    lines.append("")
    ranked = sorted(claims.items(), key=lambda kv: (-kv[1].confidence, kv[0]))
    for _cid, c in ranked:
        cite = _cite(c.supporting_evidence, labels)
        note = ""
        if c.assumptions:
            note = " — assumes " + ", ".join(c.assumptions)
        lines.append(
            f"- {c.text}{cite} "
            f"_(confidence {c.confidence:.0%}, {c.epistemic_status.value}{note})_"
        )
    if not ranked:
        lines.append("- _No claims were extracted._")
    lines.append("")

    # -- Risks and caveats ----------------------------------------------------
    weak = [(cid, c) for cid, c in ranked if is_weak_claim(c)]
    contradictions = _active(state.contradictions)
    if weak or contradictions:
        lines.append("## Risks and caveats")
        lines.append("")
        for _cid, c in weak:
            lines.append(
                f"- **Weakly supported:** {c.text}{_cite(c.supporting_evidence, labels)} "
                f"_(confidence {c.confidence:.0%})_"
            )
        for k in contradictions.values():
            lines.append(
                f"- **Conflict ({k.contradiction_type.value}):** "
                f"{k.claim_a} vs {k.claim_b} — {k.status.value}"
            )
        lines.append("")

    # -- Assumptions ----------------------------------------------------------
    if assumptions:
        lines.append("## Assumptions this rests on")
        lines.append("")
        ordered = sorted(
            assumptions.items(),
            key=lambda kv: (kv[1].impact != "high", kv[0]),
        )
        for aid, a in ordered:
            affects = ", ".join(sorted(dependents.get(aid, set())))
            tail = f" Affects: {affects}." if affects else ""
            if_false = f" If false: {a.if_false_effect}" if a.if_false_effect else ""
            lines.append(f"- {a.text} _(impact {a.impact.value})_.{if_false}{tail}")
        lines.append("")

    # -- Open questions -------------------------------------------------------
    open_qs = sorted(
        (
            q
            for q in questions.values()
            if q.status in {QuestionStatus.OPEN, QuestionStatus.IN_PROGRESS}
        ),
        key=lambda q: (_PRIORITY_RANK.get(q.priority, 1), q.id),
    )
    if open_qs:
        lines.append("## Open questions")
        lines.append("")
        for q in open_qs:
            lines.append(f"- {q.text} _({q.priority.value} priority)_")
        lines.append("")

    # -- Sources --------------------------------------------------------------
    lines.append("## Sources")
    lines.append("")
    if evidence:
        for eid in sorted(evidence):
            e = evidence[eid]
            lines.append(
                f"- **[{labels[eid]}]** \"{e.quote_or_span}\" "
                f"— {e.source_type}:{e.source_id} _({e.reliability.value} reliability)_"
            )
    else:
        lines.append("- _No evidence spans were recorded._")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append(
        "_Generated by the SPC Writer from committed semantic state. Each "
        "claim's `[E#]` citation resolves to a source span above; the full "
        "provenance, transform history, and audit log live alongside this memo "
        "in the run tree._"
    )
    lines.append("")
    return "\n".join(lines)


def write_memo(
    paths: RunPaths, state: SemanticState, *, question: str = "Decision analysis"
) -> Path:
    """Render and persist `runs/<id>/memo.md`; return its path."""
    paths.run_dir.mkdir(parents=True, exist_ok=True)
    memo_path = paths.run_dir / "memo.md"
    memo_path.write_text(render_memo(state, question=question), encoding="utf-8")
    return memo_path


__all__ = ["render_memo", "write_memo"]
