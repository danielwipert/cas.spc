"""Modality — is the cited span about something settled, or something expected?

T21 stopped a filing buying *certainty*, and left a contested merger at 0.90. The
reason is visible in the spans themselves: ten of `verify_001`'s seventeen claims
were about the future, and the pipeline had no way to notice. The model was asked
— `claim_type` offers `predictive_claim` — and answered `factual_claim` **17
times out of 17**, which is the self-judgement the whole T14-T22 arc removed
everywhere else.

**This is a heuristic, and that is a deliberate, narrow exception.** T16 declined
to read claim *text*, and T22 established that only furnished-versus-filed is a
true structural marker: the PSLRA safe harbor declares that a filing *contains*
forward-looking statements and describes their subject matter, but never marks a
sentence. There is nothing structural left to read. So this reads language — with
four constraints that make it auditable rather than magic:

1. **It reads the source's own words, not the model's.** The check runs on the
   quoted span, which T8 verified is really in the document and T10 hardened. The
   claim text is the model's paraphrase; the span is evidence.
2. **It only ever lowers.** A miss leaves the number exactly where it was, so the
   failure mode is doing nothing, never inventing confidence.
3. **It names what it found.** Every discount records the marker and lets a
   reader check the span themselves. A heuristic a human can audit in one glance
   is a different thing from a classifier nobody can question.
4. **It is biased against firing.** A claim is unsettled only when **every** span
   it cites is — one settled span is enough to settle a claim, mirroring
   `best_reliability`, where one solid source is enough to ground one.

**Measured on the real filings.** Against the sixteen distinct spans committed in
`verify_001`, this set catches **9 of the 11** forward-looking ones with **zero**
false positives on the 5 settled ones. The two misses are the same construction
twice — *"the stockholders of WBD ... **becoming** the stockholders of Newco"* — a
gerund about a future event with no modal in it. That is the shape of what this
misses, and it fails in the safe direction.

**`can` is deliberately not a marker.** It expresses *capability*, not futurity or
contingency: "the library can parse JSON" is a settled fact about the library, and
"coding assistants can accelerate routine tasks" is a claim about what they do,
not a promise about what will happen. `may`, `might` and `could` express
possibility and stay. This also happens to leave the deterministic demo untouched,
whose one hedged span reads "can accelerate" — the two coincide, and the reason
above is the one that decides it.

**It is English-only, and that is a real limit.** `live_document_german.txt`
contains none of these markers and never will, so a German filing is never
discounted for modality. The engine is not multilingual here and should not
pretend otherwise; a non-English run simply gets today's behaviour.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

__all__ = [
    "MODAL_PATTERN",
    "ModalMarker",
    "first_marker",
    "markers_in",
    "spans_are_unsettled",
]

#: Words that mark a proposition as not yet settled, drawn from the filings
#: rather than invented: `will` and `shall` did all the work on the merger 8-Ks,
#: and the rest cover the guidance and risk language a `10-K` or an earnings
#: release carries. Matched case-insensitively on word boundaries.
MODAL_PATTERN = re.compile(
    r"\b("
    r"will|shall|would|may|might|could"
    r"|expect|expects|expected|anticipate|anticipates|anticipated"
    r"|intend|intends|intended|plans to|planned to"
    r"|subject to|contingent on|conditioned on"
    r")\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ModalMarker:
    """The word that marked a span unsettled, and where it sits in that span."""

    word: str
    offset: int


def first_marker(span: str) -> ModalMarker | None:
    """The first modal marker in `span`, or `None` if it reads as settled."""
    match = MODAL_PATTERN.search(span)
    if match is None:
        return None
    return ModalMarker(match.group(0).lower(), match.start())


def spans_are_unsettled(spans: Sequence[str]) -> ModalMarker | None:
    """Is *every* cited span about something not yet settled?

    Returns the marker from the first span, for the receipt, or `None` when any
    span reads as settled — or when there are no spans at all, which carries no
    modality signal either way and is already priced as unsourced by T16.
    """
    if not spans:
        return None
    markers = [first_marker(span) for span in spans]
    if any(marker is None for marker in markers):
        return None
    first = markers[0]
    assert first is not None  # every entry is non-None, checked above
    return first


def markers_in(quotes: Mapping[str, str]) -> dict[str, ModalMarker]:
    """Every quote that reads as unsettled, keyed as given. For inspection."""
    found = {}
    for key, quote in quotes.items():
        marker = first_marker(quote)
        if marker is not None:
            found[key] = marker
    return found
