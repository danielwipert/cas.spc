"""T23 — an accountable source cannot settle a future event.

T21 stopped a filing buying *certainty* and left a contested merger at 0.90. The
reason was visible in the spans: ten of `verify_001`'s seventeen claims were
about the future — *"WBD **will** become a wholly owned subsidiary"*, *"each
share **shall** be converted"* — and nothing read the difference. The model was
asked (`claim_type` offers `predictive_claim`) and answered `factual_claim` **17
times out of 17**.

T22 established there is nothing structural left to read: the PSLRA safe harbor
says a filing *contains* forward-looking statements and never marks a sentence.
So this reads language — the **source's** words, not the model's — and these
tests pin the four things that make that acceptable: it only lowers, it never
fires when any cited span is settled, it names the marker it found, and its
misses are visible rather than hidden.
"""

from __future__ import annotations

import re

import pytest

from spc_state.modality import (
    MODAL_PATTERN,
    ModalMarker,
    first_marker,
    spans_are_unsettled,
)

# Verbatim from the Netflix and WBD Form 8-K Item 1.01 filings, as committed in
# `verify_001`. The classification is the one a reader would make.
SETTLED = [
    "On December 4, 2025, Netflix, Inc., a Delaware corporation, and Warner Bros. "
    "Discovery, Inc. entered into an Agreement and Plan of Merger",
    "The Boards of Directors of Netflix and WBD have unanimously approved the "
    "Merger Agreement",
    "the board of directors of WBD has resolved to recommend that WBD's "
    "stockholders approve the Merger",
]
UNSETTLED = [
    "Merger Sub will merge with and into WBD, with WBD surviving as a wholly "
    "owned subsidiary of Netflix",
    "The “Exchange Ratio” will be determined based on the per share "
    "volume-weighted average trading price",
    "each share of WBD Common Stock issued and outstanding immediately prior to "
    "the Effective Time shall be converted into the right to receive $23.25",
]


@pytest.mark.parametrize("span", SETTLED)
def test_a_completed_act_reads_as_settled(span: str) -> None:
    """Zero false positives on the real filings is what makes this usable."""
    assert first_marker(span) is None


@pytest.mark.parametrize("span", UNSETTLED)
def test_a_future_or_conditional_span_is_caught(span: str) -> None:
    marker = first_marker(span)
    assert marker is not None
    assert marker.word in {"will", "shall"}


def test_the_marker_records_where_it_was_found() -> None:
    """A heuristic a reader can audit in one glance is a different thing.

    The receipt names the word, and the offset lets anyone check the span.
    """
    marker = first_marker("Merger Sub will merge with and into WBD")
    assert marker == ModalMarker("will", len("Merger Sub "))


def test_can_is_deliberately_not_a_marker() -> None:
    """`can` is capability, not contingency.

    "the library can parse JSON" is a settled fact about the library. Including
    it would conflate what a thing does with what may happen to it — and would
    discount the deterministic demo's one hedged span, "coding assistants can
    accelerate routine tasks", which is a claim about what they do.
    """
    assert first_marker("Coding assistants can accelerate routine tasks.") is None
    assert first_marker("The merger may be delayed.") is not None


# ---------------------------------------------------------------------------
# the claim-level rule: biased against firing
# ---------------------------------------------------------------------------


def test_every_span_must_be_unsettled_for_the_claim_to_be() -> None:
    """One settled span is enough to settle a claim.

    Mirrors `best_reliability`, where one solid source is enough to ground one —
    and biases a heuristic toward doing nothing, which is the safe direction when
    the rule only ever lowers.
    """
    assert spans_are_unsettled([UNSETTLED[0], UNSETTLED[1]]) is not None
    assert spans_are_unsettled([UNSETTLED[0], SETTLED[0]]) is None
    assert spans_are_unsettled([SETTLED[0]]) is None


def test_a_claim_citing_nothing_carries_no_modality_signal() -> None:
    """Already priced as unsourced by T16; this axis has nothing to say."""
    assert spans_are_unsettled([]) is None


def test_the_reported_marker_comes_from_the_first_span() -> None:
    found = spans_are_unsettled(["A shall happen", "B will happen"])
    assert found is not None and found.word == "shall"


# ---------------------------------------------------------------------------
# the limits, pinned so they stay known rather than discovered
# ---------------------------------------------------------------------------


def test_a_modal_free_future_span_is_missed_and_that_is_the_safe_direction() -> None:
    """The shape of what this misses, from the real data.

    Two of `verify_001`'s spans are this construction — a gerund about a future
    event with no modal in it. The check does nothing, the number stays where it
    was, and nothing invents confidence. Pinned so the limit stays known.
    """
    gerund = (
        "with the stockholders of WBD immediately prior to the effective time of "
        "the Holdco Merger becoming the stockholders of Newco"
    )
    assert first_marker(gerund) is None


def test_the_check_is_english_only_and_says_so() -> None:
    """A German filing is never discounted for modality.

    `tests/fixtures/live_document_german.txt` contains none of these markers and
    never will. The engine is not multilingual here; a non-English run simply
    gets the behaviour it had before T23, which is honest rather than silent.
    """
    german = "Die Transaktion wird voraussichtlich im dritten Quartal abgeschlossen."
    assert first_marker(german) is None


def test_markers_match_on_word_boundaries() -> None:
    """`will` must not fire inside `goodwill`, nor `may` inside `Mayfair`."""
    assert first_marker("The goodwill impairment was recorded.") is None
    assert first_marker("Mayfair Capital completed the purchase.") is None
    assert first_marker("It will be recorded.") is not None


def test_the_pattern_is_case_insensitive() -> None:
    assert first_marker("WILL be converted") is not None
    assert first_marker("Subject to regulatory clearance") is not None


def test_every_marker_in_the_pattern_is_reachable() -> None:
    """No dead alternative: each word the pattern lists actually matches.

    A typo in one alternative would otherwise sit there looking like coverage.
    """
    words = re.search(r"\(\n?\s*(.+?)\s*\n?\)", MODAL_PATTERN.pattern, re.S)
    assert words is not None
    for word in words.group(1).replace("\n", "").split("|"):
        word = word.strip()
        assert first_marker(f"The thing {word} happen.") is not None, word
