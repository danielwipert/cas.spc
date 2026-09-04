"""State-graph Mermaid export (TASKS.md T4). See PILOT_SPEC.md §20.8.

The Reasoning Receipt is text — this renders the same committed
`SemanticState` as a Mermaid flowchart instead: one node per active object,
one edge per active relation, so the shape of the state (what depends on
what, what questions what) reads at a glance rather than being reconstructed
from prose.

Edges come only from `state.relations` — the explicit, predicate-labeled
graph the operators already build (`depends_on`, `questions`, …). This stays
a faithful projection: it renders what the state asserts as a relation, not
every field that happens to hold another object's id.

Read-only projection of `SemanticState`; deterministic (spec §12.5) — object
types render in a fixed order and each type's objects are sorted by id, so
the same state always produces the same Mermaid text.
"""

from __future__ import annotations

from collections.abc import Callable

from ..models import (
    Assumption,
    Claim,
    Contradiction,
    Entity,
    Evidence,
    Hypothesis,
    Inference,
    ObjectStatus,
    Question,
    Relation,
    SemanticState,
)

_MAX_LABEL_LEN = 60


def _entity_text(o: Entity) -> str:
    return o.name


def _claim_text(o: Claim) -> str:
    return o.text


def _evidence_text(o: Evidence) -> str:
    return o.summary or o.quote_or_span


def _assumption_text(o: Assumption) -> str:
    return o.text


def _inference_text(o: Inference) -> str:
    # `conclusion` is required but sometimes just an object id (a shorthand
    # some operators use); `notes`, when present, is the narrative version.
    return o.notes or o.conclusion


def _hypothesis_text(o: Hypothesis) -> str:
    return o.text


def _question_text(o: Question) -> str:
    return o.text


def _contradiction_text(o: Contradiction) -> str:
    return f"{o.claim_a} vs {o.claim_b} ({o.contradiction_type.value})"


# (state attribute, node label prefix, text extractor, Mermaid style class),
# in the fixed order every graph renders its object types.
_NODE_TYPES: tuple[tuple[str, str, Callable[..., str], str], ...] = (
    ("entities", "Entity", _entity_text, "entity"),
    ("claims", "Claim", _claim_text, "claim"),
    ("evidence", "Evidence", _evidence_text, "evidence"),
    ("assumptions", "Assumption", _assumption_text, "assumption"),
    ("inferences", "Inference", _inference_text, "inference"),
    ("hypotheses", "Hypothesis", _hypothesis_text, "hypothesis"),
    ("questions", "Question", _question_text, "question"),
    ("contradictions", "Contradiction", _contradiction_text, "contradiction"),
)

_CLASS_STYLES: dict[str, str] = {
    "entity": "fill:#eef0fa,stroke:#44467a,color:#20213f",
    "claim": "fill:#e6f2ff,stroke:#2b6cb0,color:#1a365d",
    "evidence": "fill:#e9f9ee,stroke:#2f855a,color:#1c4532",
    "assumption": "fill:#fff7e0,stroke:#b7791f,color:#5f3c07",
    "inference": "fill:#f2f0ff,stroke:#6b46c1,color:#3f2872",
    "hypothesis": "fill:#ffe8f2,stroke:#b83280,color:#5b1a41",
    "question": "fill:#fffbe0,stroke:#975a16,color:#4a2e08",
    "contradiction": "fill:#ffe0e0,stroke:#c53030,color:#5c1414",
}


def _is_active(obj: object) -> bool:
    """An object counts unless explicitly archived — memo.py's convention.

    Only `Entity`/`Claim`/`Evidence`/`Assumption`/`Inference` carry
    `ObjectStatus`, which has an `ARCHIVED` value; `Hypothesis`, `Question`,
    and `Contradiction` use their own status enums with no such value, so
    every one of those renders regardless of resolution — a hypothesis that
    was rejected, or a question that was answered, is still part of how the
    state got here, which is exactly what a state graph is for.
    """
    return getattr(obj, "status", ObjectStatus.ACTIVE) != ObjectStatus.ARCHIVED


def _sanitize_id(object_id: str) -> str:
    """Mermaid node ids must be identifier-safe. Real ids are always already
    safe (operator-generated, e.g. `claim_001`); this stays defensive rather
    than trusting free-form input into diagram syntax."""
    safe = "".join(c if c.isalnum() or c == "_" else "_" for c in object_id)
    return safe or "_"


def _label(node_id: str, prefix: str, text: str) -> str:
    flat = " ".join(text.split())  # collapse newlines/repeated whitespace
    if len(flat) > _MAX_LABEL_LEN:
        flat = flat[: _MAX_LABEL_LEN - 1].rstrip() + "…"
    flat = flat.replace('"', "'")
    return f'{node_id}["{prefix}: {flat}"]'


def render_mermaid_graph(state: SemanticState) -> str:
    """Render `state`'s active objects and relations as Mermaid flowchart text.

    One node per active object across every typed container, one edge per
    active `Relation` whose endpoints are both active nodes — an edge is
    never drawn to an object the graph itself omitted. Returns the raw
    Mermaid source (no ```` ```mermaid ```` fence); the caller embeds it.
    """
    lines: list[str] = ["flowchart TD"]
    active_ids: set[str] = set()

    for attr, prefix, text_of, _cls in _NODE_TYPES:
        container: dict[str, object] = getattr(state, attr)
        for oid in sorted(container):
            obj = container[oid]
            if not _is_active(obj):
                continue
            active_ids.add(oid)
            lines.append(f"    {_label(_sanitize_id(oid), prefix, text_of(obj))}")

    edges: list[Relation] = sorted(
        (r for r in state.relations if _is_active(r)),
        key=lambda r: (r.source, r.predicate, r.target, r.id),
    )
    for r in edges:
        if r.source not in active_ids or r.target not in active_ids:
            continue  # a faithful projection never draws an edge it can't ground
        label = r.predicate.strip().replace("|", "/") or "relates_to"
        lines.append(f"    {_sanitize_id(r.source)} -->|{label}| {_sanitize_id(r.target)}")

    for attr, _prefix, _text_of, cls in _NODE_TYPES:
        container = getattr(state, attr)
        styled = sorted(oid for oid, obj in container.items() if _is_active(obj))
        if not styled:
            continue
        lines.append(f"    classDef {cls} {_CLASS_STYLES[cls]}")
        lines.append(f"    class {','.join(_sanitize_id(i) for i in styled)} {cls}")

    return "\n".join(lines)


__all__ = ["render_mermaid_graph"]
