"""Locate an evidence quote inside the document it claims to come from.

Every Decision Memo says it "asserts nothing the state does not hold", and
every finding it renders carries an `[E#]` citation. That promise rests on
`Evidence.quote_or_span` really being a span of the source document — but the
LLM extract path takes the model's `evidence_quote` on trust, and neither
validation layer is ever handed the source text (see `validation/l2.py`, which
takes `(state, patch)` only). This module is the missing check: a pure,
offline, deterministic lookup the extractor runs before it will build an
`Evidence` object.

**Exact matching is the wrong implementation.** Measured over a live `analyze`
run on a 4-page press release, all ten extracted spans were substantively
faithful — nothing fabricated — yet only *two* were byte-exact substrings of
the input. The other eight differed in ways that say nothing about fidelity:

- **Whitespace.** PDF text extraction breaks lines mid-sentence, so a span the
  model read as one sentence contains a newline in the document.
- **Quote characters.** The model folds the document's typographic quotes to
  ASCII, and folds double quotes to single ones inside a span it is nesting in
  its own JSON string.
- **Terminal punctuation.** Quoting a bullet that has no full stop, the model
  adds one; quoting the first clause of a sentence, it ends the span at a
  comma the document continues past.

So `locate_span` compares under a documented normalization — collapse
whitespace runs, fold typographic quotes/dashes/spaces to ASCII, and allow the
quote's trailing punctuation to differ — and reports the match against the
*original* offsets, so a caller can record exactly where the span sits.

Deliberately **not** normalized: letter case, and any word the model added,
dropped, or reordered inside the span. Those alter what the source says, which
is the thing this check exists to catch.
"""

from __future__ import annotations

from typing import NamedTuple

__all__ = ["SpanMatch", "locate_span", "normalize"]

#: Characters folded to an ASCII equivalent before comparison. A fold may be
#: more than one character (`…` -> `...`); the offset map handles that.
_FOLD: dict[str, str] = {
    # Written as escapes, not literals: several of these are invisible or
    # visually identical to ASCII in an editor, which is exactly the confusion
    # this table exists to resolve.
    "\u2018": "'",  # left single quotation mark
    "\u2019": "'",  # right single quotation mark / apostrophe
    "\u201a": "'",  # single low-9 quotation mark
    "\u201b": "'",  # single high-reversed-9 quotation mark
    # Double quotes fold to the same canonical mark, so a model that renders
    # the document's "quoted phrase" as 'quoted phrase' still matches.
    "\u201c": "'",  # left double quotation mark
    "\u201d": "'",  # right double quotation mark
    "\u201e": "'",  # double low-9 quotation mark
    "\u201f": "'",  # double high-reversed-9 quotation mark
    '"': "'",  # ASCII double quote
    "\u2010": "-",  # hyphen
    "\u2011": "-",  # non-breaking hyphen
    "\u2012": "-",  # figure dash
    "\u2013": "-",  # en dash
    "\u2014": "-",  # em dash
    "\u2015": "-",  # horizontal bar
    "\u2212": "-",  # minus sign
    "\u00a0": " ",  # no-break space
    "\u2007": " ",  # figure space
    "\u2009": " ",  # thin space
    "\u202f": " ",  # narrow no-break space
    "\ufeff": " ",  # zero-width no-break space (BOM)
    "\u2026": "...",  # horizontal ellipsis
}

#: Punctuation allowed to differ at the very end of a quote.
_TERMINAL_PUNCTUATION = ".,;:!?"


class SpanMatch(NamedTuple):
    """Where a quote was found, as offsets into the *original* document."""

    start: int
    end: int


def _normalize_with_map(text: str) -> tuple[str, list[int]]:
    """Normalize `text`, tracking which original index produced each character.

    `origin[i]` is the index in `text` of the character that produced
    normalized character `i`, so a match found in normalized space can be
    reported against the original document.
    """
    chars: list[str] = []
    origin: list[int] = []
    in_whitespace = False

    for index, char in enumerate(text):
        folded = _FOLD.get(char, char)
        if folded.isspace():
            # Collapse each run of whitespace to a single space, anchored at
            # the first character of the run.
            if not in_whitespace:
                chars.append(" ")
                origin.append(index)
                in_whitespace = True
            continue
        in_whitespace = False
        for produced in folded:
            chars.append(produced)
            origin.append(index)

    return "".join(chars), origin


def normalize(text: str) -> str:
    """The comparison form of `text` — see the module docstring for the rules."""
    return _normalize_with_map(text)[0]


def locate_span(quote: str, document: str) -> SpanMatch | None:
    """Find `quote` in `document`, or return `None` if it is not there.

    Comparison happens in normalized space; the returned offsets index the
    original `document`, so `document[match.start:match.end]` is the real span
    the quote refers to. An empty or whitespace-only quote never matches.
    """
    normalized_document, origin = _normalize_with_map(document)
    needle = normalize(quote).strip()
    if not needle:
        return None

    index = normalized_document.find(needle)
    if index == -1:
        # Allow the quote's own terminal punctuation to differ from the
        # document's: a bullet quoted with an added full stop, or a clause
        # quoted up to a comma the document continues past.
        trimmed = needle.rstrip(_TERMINAL_PUNCTUATION)
        if not trimmed or trimmed == needle:
            return None
        index = normalized_document.find(trimmed)
        if index == -1:
            return None
        needle = trimmed

    return SpanMatch(origin[index], origin[index + len(needle) - 1] + 1)
