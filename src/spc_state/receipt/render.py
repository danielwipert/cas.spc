"""Render a `ReasoningReceipt` as Markdown. See PILOT_SPEC.md §18.

The projected receipt (`project.py`) carries object **ids**; this renderer
resolves them against the final `SemanticState` so a human reads claim text,
confidence, and provenance rather than bare identifiers. Optionally appends
the state diffs for each version transition.

Output is deterministic: given the same receipt + state + diffs, the Markdown
is byte-for-byte identical, preserving the Phase 3 reproducibility gate.
"""

from __future__ import annotations

from ..diff import StateDiff
from ..models import ReasoningReceipt, SemanticState


def _claim_line(state: SemanticState, cid: str) -> str:
    c = state.claims.get(cid)
    if c is None:
        return f"- `{cid}`"
    ev = f", {len(c.supporting_evidence)} evidence" if c.supporting_evidence else ""
    return (
        f"- `{cid}` — {c.text} "
        f"_(confidence {c.confidence:.2f}, {c.epistemic_status.value}{ev})_"
    )


def _evidence_line(state: SemanticState, eid: str) -> str:
    e = state.evidence.get(eid)
    if e is None:
        return f"- `{eid}`"
    text = e.summary or e.quote_or_span
    return f"- `{eid}` — {text} _(source {e.source_id}, {e.reliability.value})_"


def _assumption_line(state: SemanticState, aid: str) -> str:
    a = state.assumptions.get(aid)
    if a is None:
        return f"- `{aid}`"
    return (
        f"- `{aid}` — {a.text} "
        f"_(impact {a.impact.value}, confidence {a.confidence:.2f})_"
    )


def _contradiction_line(state: SemanticState, kid: str) -> str:
    k = state.contradictions.get(kid)
    if k is None:
        return f"- `{kid}`"
    return (
        f"- `{kid}` — `{k.claim_a}` vs `{k.claim_b}` "
        f"_({k.contradiction_type.value}, {k.severity.value}, {k.status.value})_"
    )


def _question_line(state: SemanticState, qid: str) -> str:
    q = state.questions.get(qid)
    if q is None:
        return f"- `{qid}`"
    return f"- `{qid}` — {q.text} _(priority {q.priority.value})_"


def _transform_line(state: SemanticState, tid: str) -> str:
    rec = next((t for t in state.transform_log if t.id == tid), None)
    if rec is None:
        return f"- `{tid}`"
    wrote = ", ".join(f"`{w}`" for w in rec.write_set) or "—"
    return (
        f"- `{tid}` — **{rec.operator}** ({rec.transform_type}), "
        f"v{rec.input_state_version}→v{rec.output_state_version}; wrote {wrote}"
    )


def _ids(state: SemanticState, ids: list[str], formatter) -> list[str]:
    return [formatter(state, i) for i in ids] or ["- _(none)_"]


def _render_diff(diff: StateDiff) -> list[str]:
    lines = [f"### v{diff.from_version} → v{diff.to_version}", ""]
    if diff.is_empty():
        lines.append("_(no changes)_")
        lines.append("")
        return lines
    for object_type, td in diff.by_type.items():
        if td.added:
            lines.append(f"- **added {object_type}:** " + ", ".join(f"`{i}`" for i in td.added))
        if td.removed:
            lines.append(f"- **removed {object_type}:** " + ", ".join(f"`{i}`" for i in td.removed))
        for ch in td.changed:
            for fc in ch.field_changes:
                lines.append(
                    f"- **changed {object_type} `{ch.object_id}`:** "
                    f"`{fc.field}` {fc.from_value!r} → {fc.to_value!r}"
                )
    lines.append("")
    return lines


def render_markdown(
    receipt: ReasoningReceipt,
    final_state: SemanticState,
    *,
    diffs: list[StateDiff] | None = None,
) -> str:
    """Render `receipt` to Markdown, resolving ids against `final_state`."""
    cmap = receipt.confidence_map
    lines: list[str] = [
        f"# Reasoning Receipt — {receipt.receipt_id}",
        "",
        f"- **State:** `{receipt.state_id}` v{receipt.state_version}",
        f"- **Generated:** {receipt.generated_at.isoformat()}",
        "",
        "## Summary",
        "",
        f"**Q.** {receipt.summary.question}",
        "",
        f"**A.** {receipt.summary.answer}",
        "",
        "## Claims Produced",
        "",
        *_ids(final_state, receipt.claims_produced, _claim_line),
        "",
        "## Evidence Used",
        "",
        *_ids(final_state, receipt.evidence_used, _evidence_line),
        "",
        "## Assumptions",
        "",
        *_ids(final_state, receipt.assumptions, _assumption_line),
        "",
        "## Contradictions",
        "",
        *_ids(final_state, receipt.contradictions, _contradiction_line),
        "",
        "## Open Questions",
        "",
        *_ids(final_state, receipt.open_questions, _question_line),
        "",
        "## Transform History",
        "",
        *_ids(final_state, receipt.transform_history, _transform_line),
        "",
        "## Confidence Map",
        "",
        "- **strongest:** "
        + (", ".join(f"`{c}`" for c in cmap.strongest_claims) or "_(none)_"),
        "- **weakest:** "
        + (", ".join(f"`{c}`" for c in cmap.weakest_claims) or "_(none)_"),
        "- **assumption-sensitive:** "
        + (", ".join(f"`{c}`" for c in cmap.assumption_sensitive_claims) or "_(none)_"),
        "",
    ]

    if diffs:
        lines += ["## State Diffs", ""]
        for diff in diffs:
            lines += _render_diff(diff)

    lines += [
        "## Audit",
        "",
        "- **committed:** "
        + (", ".join(f"`{p}`" for p in receipt.audit.committed_patches) or "_(none)_"),
        "- **reviewed:** "
        + (", ".join(f"`{p}`" for p in receipt.audit.reviewed_patches) or "_(none)_"),
        "- **rejected:** "
        + (", ".join(f"`{p}`" for p in receipt.audit.rejected_patches) or "_(none)_"),
        "",
    ]

    return "\n".join(lines)


__all__ = ["render_markdown"]
