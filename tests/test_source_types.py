"""T14 — reliability is a property of the source, not of the model's opinion.

`Evidence.reliability` is the number the rest of the pipeline is sceptical by:
the Retriever opens an evidence-gap question for any under-confident claim not
resting on a `HIGH` span, and the memo flags findings supported only by `LOW`
ones. It used to arrive from the model's own extraction output, which let the
extraction grade itself — and on a live press release it gave itself `high` ten
times out of ten, silencing the Retriever exactly where scrutiny was wanted.

These tests hold the taxonomy to the rule the module states, so that adding a
source type is a decision someone has to make rather than one that happens by
default.
"""

from __future__ import annotations

import pytest

from spc_state.models import Reliability
from spc_state.source_types import (
    DEFAULT_SOURCE_TYPE,
    RELIABILITY_BY_SOURCE_TYPE,
    SourceType,
    coerce_source_type,
    reliability_for,
)

#: Sources where someone is answerable for the statement being true — a legal
#: duty of accuracy, or an independent check. Spelled out a second time, by
#: hand, so the mapping cannot quietly promote a source type: changing
#: `RELIABILITY_BY_SOURCE_TYPE` alone fails here.
ACCOUNTABLE = {
    SourceType.REGULATORY_FILING,
    SourceType.AUDITED_FINANCIALS,
    SourceType.COURT_RECORD,
    SourceType.OFFICIAL_STATISTICS,
    SourceType.PEER_REVIEWED,
}

#: Sources whose author benefits from the conclusion, unchecked by anyone else.
INTERESTED = {
    SourceType.PRESS_RELEASE,
    SourceType.MARKETING_MATERIAL,
    SourceType.OPINION,
    SourceType.SOCIAL_MEDIA,
}


def test_every_source_type_has_a_decided_reliability() -> None:
    """A new member must not inherit a weighting by omission."""
    assert set(RELIABILITY_BY_SOURCE_TYPE) == set(SourceType)


@pytest.mark.parametrize("source", sorted(ACCOUNTABLE, key=lambda s: s.value))
def test_only_accountable_sources_are_high(source: SourceType) -> None:
    assert reliability_for(source) is Reliability.HIGH


@pytest.mark.parametrize("source", sorted(INTERESTED, key=lambda s: s.value))
def test_interested_sources_are_low(source: SourceType) -> None:
    assert reliability_for(source) is Reliability.LOW


def test_nothing_else_reaches_high() -> None:
    """The set of `HIGH` sources is exactly the accountable one, not a superset."""
    high = {s for s, r in RELIABILITY_BY_SOURCE_TYPE.items() if r is Reliability.HIGH}
    assert high == ACCOUNTABLE


def test_an_undeclared_source_is_medium_not_low_and_never_high() -> None:
    """"We do not know" is not "we know it is bad" — but it is not a promotion.

    `LOW` would flag every finding of every unclassified run as weakly
    supported, which asserts something about the source nobody established.
    `HIGH` is the free promotion this change exists to remove. `MEDIUM` is the
    only honest answer, and it still wakes the Retriever.
    """
    assert DEFAULT_SOURCE_TYPE is SourceType.UNCLASSIFIED
    assert reliability_for(DEFAULT_SOURCE_TYPE) is Reliability.MEDIUM
    assert reliability_for(None) is Reliability.MEDIUM


def test_unknown_strings_are_weighed_cautiously_rather_than_raising() -> None:
    """Stored state and model output both carry strings we did not write.

    Refusing to read a run because it names a source type this version does not
    know is worse than weighing it as unclassified — and `input_document`, the
    vocabulary the pipeline used before this taxonomy existed, is exactly such
    a string.
    """
    assert reliability_for("input_document") is Reliability.MEDIUM
    assert reliability_for("something_invented_later") is Reliability.MEDIUM
    assert coerce_source_type("nonsense") is SourceType.UNCLASSIFIED


def test_source_types_are_read_case_and_space_insensitively() -> None:
    assert coerce_source_type("  Press_Release ") is SourceType.PRESS_RELEASE
    assert coerce_source_type(SourceType.NEWS_REPORT) is SourceType.NEWS_REPORT


def test_a_press_release_and_a_filing_are_not_weighed_alike() -> None:
    """The distinction the whole change is for, stated as a test."""
    assert reliability_for(SourceType.PRESS_RELEASE) is Reliability.LOW
    assert reliability_for(SourceType.REGULATORY_FILING) is Reliability.HIGH
