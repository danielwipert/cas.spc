"""The baseline: a competent JSON-handoff chain (PILOT_SPEC.md §8.2).

```text
Document → LLM summary → LLM critique → LLM final memo
```

This is the control the SPC engine is measured against in Phase 8. It is
deliberately *competent*, not a strawman: the prose mentions the cost and
security concerns, surfaces the architecture-work caveat in the critique, and
produces a defensible recommendation. The pilot's claim (spec §5) is **not**
that SPC writes a better paragraph — it is that the baseline cannot carry
durable, queryable semantic state across the handoffs:

- every stage receives the previous stage's JSON plus the full document again
  (no projection — the only way to avoid losing fidelity is to re-read),
- there are no stable object ids, so the same claim is silently reworded
  between stages with no evidence anchor and no recorded reason,
- there is no provenance, no assumption object, no contradiction object, and
  no transform history — so the §8.4 follow-ups cannot be answered without
  re-running the chain.

Like the Phase 3 deterministic operators, this is keyed to the
AI-coding-assistant demo document by a marker phrase so the headline pilot
report is byte-for-byte reproducible. Swapping in a live model would change
the prose but not the structural conclusion.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from itertools import pairwise
from typing import Any

from ..tokens import estimate_tokens

MARKER = "AI coding assistant"

# The §8.4 demo follow-ups, tagged by *why* the baseline cannot answer them
# from its own artifacts. "impossible" = there is no durable object to read at
# all (no ids, no versions, no provenance); "rerun" = the information exists in
# the prose transcript but only an external re-reading / re-prompt can extract
# it — the chain itself holds no queryable answer.
FOLLOWUPS: list[tuple[str, str]] = [
    ("What did the critic add?", "rerun"),
    ("Which claims are weakest?", "rerun"),
    ("Which assumptions most affect the conclusion?", "impossible"),
    ("Which source supports this claim?", "impossible"),
    ("What changed between state v1 and state v3?", "impossible"),
    ("Which unresolved questions remain?", "rerun"),
    ("Which final recommendation depends on the security assumption?", "impossible"),
    ("Which claims were inferred rather than observed?", "impossible"),
]


@dataclass(frozen=True)
class BaselineStage:
    """One LLM hop in the chain, with what it had to ingest to run."""

    name: str
    ingested_tokens: int
    full_document_reingested: bool
    output: dict[str, Any]


@dataclass(frozen=True)
class ClaimLineage:
    """How one underlying claim is phrased as it passes down the chain.

    Because there are no object ids, the chain cannot itself know these are
    "the same claim" — alignment requires a human or a fresh model read. Each
    rewording without an evidence anchor is drift the system cannot detect
    (spec §20.3).
    """

    label: str
    phrasings: list[str]
    carried_evidence: bool = False

    @property
    def mutations(self) -> int:
        """Number of times the phrasing changed between consecutive stages."""
        return sum(1 for a, b in pairwise(self.phrasings) if a != b)


@dataclass(frozen=True)
class BaselineResult:
    document: str
    model: str
    stages: list[BaselineStage]
    claim_lineages: list[ClaimLineage] = field(default_factory=list)

    def stage(self, name: str) -> BaselineStage:
        for s in self.stages:
            if s.name == name:
                return s
        raise KeyError(f"No baseline stage named {name!r}.")

    @property
    def summary(self) -> dict[str, Any]:
        return self.stage("summary").output

    @property
    def critique(self) -> dict[str, Any]:
        return self.stage("critique").output

    @property
    def memo(self) -> dict[str, Any]:
        return self.stage("memo").output

    @property
    def document_tokens(self) -> int:
        return estimate_tokens(self.document)

    @property
    def transcript_tokens(self) -> int:
        """Tokens of the JSON passed between stages (the whole conversation)."""
        return sum(estimate_tokens(s.output) for s in self.stages)

    @property
    def total_ingested_tokens(self) -> int:
        return sum(s.ingested_tokens for s in self.stages)

    @property
    def full_document_reingestions(self) -> int:
        return sum(1 for s in self.stages if s.full_document_reingested)

    def transcript_markdown(self) -> str:
        """Render the handoff as a human-readable transcript artifact."""
        import json

        lines = [f"# Baseline JSON-handoff transcript ({self.model})", ""]
        lines.append("> Document → summary → critique → final memo. No durable")
        lines.append("> semantic state is produced; each stage re-reads the document.")
        lines.append("")
        for s in self.stages:
            lines.append(f"## Stage: {s.name}")
            reread = "yes" if s.full_document_reingested else "no"
            lines.append(
                f"_ingested ≈ {s.ingested_tokens} tokens "
                f"(full document re-read: {reread})_"
            )
            lines.append("")
            lines.append("```json")
            lines.append(json.dumps(s.output, indent=2, ensure_ascii=False))
            lines.append("```")
            lines.append("")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Deterministic content keyed to the demo document
# ---------------------------------------------------------------------------

_SUMMARY = {
    "summary": (
        "A company is evaluating an AI coding assistant. Engineering expects "
        "productivity gains, finance is concerned about usage-based costs, and "
        "security is concerned about source-code exposure. Benchmarks suggest "
        "gains on routine tasks, with weaker evidence for complex architecture "
        "work."
    ),
    "key_points": [
        "AI coding assistants can speed up routine engineering tasks.",
        "Usage-based costs are a concern raised by finance.",
        "Source-code exposure is a concern raised by security.",
        "Evidence is weaker for complex architecture work.",
    ],
}

_CRITIQUE = {
    "strengths": [
        "Captures the engineering, finance, and security perspectives.",
    ],
    "concerns": [
        "The productivity benefit rests on an unstated assumption that "
        "benchmark gains transfer to this team's workflow.",
        "The headline productivity gain is not weighed against the weak "
        "evidence for complex architecture work.",
    ],
    "revised_points": [
        "AI coding assistants likely improve routine task speed, though the "
        "gain is uncertain for complex architecture work.",
        "Costs and source-code exposure are material risks that need controls.",
    ],
}

_MEMO = {
    "recommendation": (
        "Pilot the AI coding assistant on routine engineering tasks, with cost "
        "monitoring and source-code controls, before any broad rollout."
    ),
    "rationale": (
        "Benchmarks and team expectations point to meaningful productivity "
        "gains on routine work, while costs and security exposure are "
        "manageable with guardrails."
    ),
    "caveats": [
        "Benefits for complex architecture work are unproven.",
    ],
}

# The productivity claim, tracked as it is silently reworded down the chain.
# It strengthens ("can speed up" → "likely improve" → "meaningful gains") and
# folds the unstated assumption in ("team expectations point to") without ever
# attaching evidence or a recorded reason — undetectable drift (spec §20.3).
_PRODUCTIVITY_LINEAGE = ClaimLineage(
    label="AI assistants improve routine-task productivity",
    phrasings=[
        "AI coding assistants can speed up routine engineering tasks.",
        "AI coding assistants likely improve routine task speed, though the "
        "gain is uncertain for complex architecture work.",
        "Benchmarks and team expectations point to meaningful productivity "
        "gains on routine work.",
    ],
    carried_evidence=False,
)


def run_baseline(document: str, *, model: str = "(deterministic)") -> BaselineResult:
    """Run the JSON-handoff baseline over the demo document.

    Each stage ingests the full document again plus the prior stage's JSON —
    the competent way to avoid losing fidelity in a stateless chain, and
    exactly the reprocessing burden Phase 8 measures (spec §20.4).
    """
    if MARKER not in document:
        raise NotImplementedError(
            "The Phase 8 deterministic baseline only handles the "
            "AI-coding-assistant demo document. Wire a live model for other "
            "inputs."
        )

    doc_tokens = estimate_tokens(document)
    summary_tokens = estimate_tokens(_SUMMARY)
    critique_tokens = estimate_tokens(_CRITIQUE)

    stages = [
        # Summary reads the raw document.
        BaselineStage(
            name="summary",
            ingested_tokens=doc_tokens,
            full_document_reingested=True,
            output=_SUMMARY,
        ),
        # Critique re-reads the document so it can fact-check the summary.
        BaselineStage(
            name="critique",
            ingested_tokens=doc_tokens + summary_tokens,
            full_document_reingested=True,
            output=_CRITIQUE,
        ),
        # The memo re-reads the document plus both prior JSON blobs.
        BaselineStage(
            name="memo",
            ingested_tokens=doc_tokens + summary_tokens + critique_tokens,
            full_document_reingested=True,
            output=_MEMO,
        ),
    ]

    return BaselineResult(
        document=document,
        model=model,
        stages=stages,
        claim_lineages=[_PRODUCTIVITY_LINEAGE],
    )


__all__ = [
    "FOLLOWUPS",
    "MARKER",
    "BaselineResult",
    "BaselineStage",
    "ClaimLineage",
    "run_baseline",
]
