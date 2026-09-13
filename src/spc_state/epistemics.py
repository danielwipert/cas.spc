"""The two epistemic axes that are **derived from state, never stored** (T20).

`EpistemicStatus` answers one question — how a claim entered state — and T20
narrowed it to exactly that. The two questions it used to also answer are
answered here instead, by reading committed state:

| axis | question | derived from |
|---|---|---|
| corroboration | how well is it supported? | the spans the claim cites, and the sources behind them |
| conflict | does anything contradict it? | the `Contradiction` objects naming it |

**Why derived and not stored.** A stored label is a summary of the warrant
graph sitting in the middle of the state, and this pilot exists to argue that
compound systems should not pass summaries around. It can go stale, it can be
asserted by an operator that should not be asserting it, and it has to be
overwritten when the graph beneath it changes — which is precisely how T19's
promotion destroyed the `REPORTED` it wrote over. Computed on read, the answer
is correct by construction and cannot be claimed, only earned.

**Corroboration needs independence, and that is the whole point of the bar.**
Two sources agreeing means nothing if the second got it from the first. Reuters
reporting a merger *because it read the press release* is not a second source,
it is the same source relayed; ten outlets carrying one wire story are one
source wearing ten hats. Before T20 `Evidence` separated sources only by
`source_id`, so every one of those counted.

A model cannot settle this. Whether an article was written off a press release
is a fact about the world *outside* both documents — the class T14 ruled on:
*an operator does not take a model's word for a fact about the world outside the
document.* So lineage is **declared by the caller** (`Evidence.derives_from`),
exactly as `source_type` is, and derived from here.

Undeclared lineage counts as independent. That is deliberate and it is the
*generous* default, unlike `MEDIUM` for an undeclared source type: "we do not
know where this came from" is not "we know it is derivative", and smearing every
unlabelled pair as dependent would make corroboration unreachable for anyone who
has not mapped their whole corpus. It does mean a `VERIFIED` claim is only as
honest as the lineage the caller declared, which is why `spc-demo analyze` says
so and the memo repeats it.
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import Enum
from itertools import combinations

from .models import Claim, Contradiction, ContradictionStatus, Evidence, Reliability

__all__ = [
    "Corroboration",
    "corroboration_of",
    "is_contested",
    "source_lineage",
    "sources_are_independent",
]


class Corroboration(str, Enum):
    """How well a claim is supported *across independent sources*.

    Derived by `corroboration_of`; never stored on a `Claim`. The ladder is
    deliberately short, and each rung names a thing a reader can check.
    """

    #: One source, or several that trace to each other.
    UNCORROBORATED = "uncorroborated"
    #: Two or more genuinely independent sources assert it.
    CORROBORATED = "corroborated"
    #: As above, and at least one of them is accountable (`HIGH`).
    VERIFIED = "verified"


def source_lineage(evidence: Mapping[str, Evidence]) -> dict[str, str | None]:
    """Map every `source_id` to the source it was declared downstream of.

    Several spans share one `source_id`; the first declared `derives_from` wins,
    so a single unlabelled span cannot erase a lineage its neighbours declared.
    """
    lineage: dict[str, str | None] = {}
    for _eid, item in sorted(evidence.items()):
        current = lineage.get(item.source_id)
        if current is None:
            lineage[item.source_id] = item.derives_from
    return lineage


def _ancestors(source_id: str, lineage: Mapping[str, str | None]) -> set[str]:
    """Every source `source_id` is downstream of. Cycle-safe by construction."""
    seen: set[str] = set()
    current = lineage.get(source_id)
    while current is not None and current not in seen:
        seen.add(current)
        current = lineage.get(current)
    return seen


def sources_are_independent(
    a: str, b: str, lineage: Mapping[str, str | None]
) -> bool:
    """Is neither source downstream of the other?

    The same document is never independent of itself, which is the degenerate
    case `LLMCorroborationOperator` used to check on its own.
    """
    if a == b:
        return False
    return b not in _ancestors(a, lineage) and a not in _ancestors(b, lineage)


def _sources_with_reliability(
    claim: Claim, evidence: Mapping[str, Evidence]
) -> dict[str, Reliability]:
    """The sources this claim cites, each at the best reliability it offers."""
    best: dict[str, Reliability] = {}
    order = {Reliability.LOW: 0, Reliability.MEDIUM: 1, Reliability.HIGH: 2}
    for eid in claim.supporting_evidence:
        item = evidence.get(eid)
        if item is None:
            continue
        current = best.get(item.source_id)
        if current is None or order[item.reliability] > order[current]:
            best[item.source_id] = item.reliability
    return best


def corroboration_of(claim: Claim, evidence: Mapping[str, Evidence]) -> Corroboration:
    """What the claim's own citations establish about its support.

    `VERIFIED` requires two independent sources **and** an accountable one among
    them. Two interested parties telling the same story is corroboration, not
    verification, and the ladder keeps them apart (T17's reason for holding the
    word back in the first place).
    """
    sources = _sources_with_reliability(claim, evidence)
    if len(sources) < 2:
        return Corroboration.UNCORROBORATED

    lineage = source_lineage(evidence)
    level = Corroboration.UNCORROBORATED
    for a, b in combinations(sorted(sources), 2):
        if not sources_are_independent(a, b, lineage):
            continue
        if Reliability.HIGH in (sources[a], sources[b]):
            return Corroboration.VERIFIED
        level = Corroboration.CORROBORATED
    return level


def is_contested(
    claim_id: str, contradictions: Mapping[str, Contradiction]
) -> bool:
    """Does an **unresolved** contradiction name this claim?

    Resolved and dismissed conflicts are history, not a live caveat — they stay
    in state as the record that someone looked, which is the point of T3 keeping
    them as objects rather than flattening them into a consensus claim.
    """
    return any(
        c.status is ContradictionStatus.UNRESOLVED
        and claim_id in (c.claim_a, c.claim_b)
        for c in contradictions.values()
    )
