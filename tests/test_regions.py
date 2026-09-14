"""T22 — a document is not one block of accountability.

T14 established that `Evidence.reliability` is a fact about *where the text came
from*, which the caller knows and the model cannot see. It then stamped one value
on every span in the file. A filing is not one block of accountability, and the
document says so itself: an 8-K's Item 7.01 is **furnished**, not filed, and
states outright that it is not "subject to the liabilities of that section".

EDGAR serves each filing as one complete submission concatenating the 8-K body
with its exhibits, so declaring "the 8-K" a `regulatory_filing` used to weigh the
attached press release — marketing copy included — exactly as heavily as the
merger agreement's terms. Measured on `region_001`: three of six claims came from
the disclaimed region at `HIGH`.

These tests pin the rule (last region beginning at or before the span wins), the
boundary index, that an unlocatable marker raises rather than silently doing
nothing, and that a document with no regions declared is byte-for-byte what it
was before.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import pytest

from spc_state.models import Reliability
from spc_state.operators import LLMExtractOperator
from spc_state.providers.mock import MockProvider
from spc_state.regions import (
    RegionError,
    SourceRegion,
    parse_region,
    resolve_regions,
    source_type_at,
)
from spc_state.runtime import FixedClock, Runtime, bootstrap_state
from spc_state.source_types import SourceType
from spc_state.store import RunPaths

NOW = dt.datetime(2026, 9, 14, tzinfo=dt.UTC)

# A miniature of the real shape: a filed section, then a furnished one whose
# disclaimer the document states itself, then the exhibit's promotional prose.
DOCUMENT = """Item 1.01 Entry into a Material Definitive Agreement.

On December 4, 2025, Netflix and WBD entered into an Agreement and Plan of Merger.

Item 7.01 Regulation FD Disclosure.

The information contained in this Item 7.01, including Exhibit 99.1, shall not be
deemed "filed" for purposes of Section 18 of the Securities Exchange Act of 1934.

EXHIBIT 99.1

The merger unites Warner Bros.' iconic franchises with Netflix's leading service.
"""

FILED_QUOTE = "On December 4, 2025, Netflix and WBD entered into an Agreement and Plan of Merger"
FURNISHED_QUOTE = "The merger unites Warner Bros.' iconic franchises"
BOUNDARY = DOCUMENT.index("Item 7.01")


def _region(marker: str = "Item 7.01", kind: str = "press_release") -> SourceRegion:
    return SourceRegion(marker, SourceType(kind))


# ---------------------------------------------------------------------------
# parsing a declaration
# ---------------------------------------------------------------------------


def test_a_declaration_parses_into_a_marker_and_a_source_type() -> None:
    parsed = parse_region("Item 7.01:press_release")
    assert parsed == SourceRegion("Item 7.01", SourceType.PRESS_RELEASE)


def test_a_marker_may_contain_a_colon() -> None:
    """Split on the *last* colon: real headings contain them."""
    parsed = parse_region("Item 7.01: Regulation FD Disclosure:press_release")
    assert parsed.marker == "Item 7.01: Regulation FD Disclosure"
    assert parsed.source_type is SourceType.PRESS_RELEASE


@pytest.mark.parametrize("spec", ["Item 7.01", "Item 7.01:", ":press_release", ""])
def test_a_malformed_declaration_raises(spec: str) -> None:
    with pytest.raises(RegionError):
        parse_region(spec)


def test_an_unknown_source_type_raises_and_lists_the_known_ones() -> None:
    with pytest.raises(RegionError) as exc:
        parse_region("Item 7.01:furnished_exhibit")
    assert "regulatory_filing" in str(exc.value)


# ---------------------------------------------------------------------------
# resolving against a document
# ---------------------------------------------------------------------------


def test_a_marker_that_does_not_occur_raises() -> None:
    """Silently ignoring it leaves a document that looks region-aware and is not.

    The caller would believe the exhibit had been discounted while every span
    still carried the filing's weight — the exact failure this task prevents.
    """
    with pytest.raises(RegionError) as exc:
        resolve_regions(DOCUMENT, [_region("Item 8.99")])
    assert "Item 8.99" in str(exc.value)


def test_regions_resolve_in_document_order_however_they_were_declared() -> None:
    resolved = resolve_regions(
        DOCUMENT, [_region("EXHIBIT 99.1"), _region("Item 7.01")]
    )
    assert [r.start for r in resolved] == sorted(r.start for r in resolved)


def test_a_marker_is_located_through_whitespace_differences() -> None:
    """Markers use the same `locate_span` as citations, so real text works."""
    resolved = resolve_regions(DOCUMENT, [_region("Item   7.01")])
    assert resolved[0].start == BOUNDARY


# ---------------------------------------------------------------------------
# which region a span belongs to
# ---------------------------------------------------------------------------


def test_a_span_before_the_first_region_keeps_the_documents_own_type() -> None:
    resolved = resolve_regions(DOCUMENT, [_region()])
    assert source_type_at(0, resolved, SourceType.REGULATORY_FILING) is (
        SourceType.REGULATORY_FILING
    )


def test_a_span_after_the_marker_takes_the_regions_type() -> None:
    resolved = resolve_regions(DOCUMENT, [_region()])
    assert source_type_at(
        BOUNDARY + 50, resolved, SourceType.REGULATORY_FILING
    ) is SourceType.PRESS_RELEASE


def test_a_span_exactly_at_the_marker_belongs_to_the_region() -> None:
    """The only ambiguous index, pinned: the heading is part of what it marks."""
    resolved = resolve_regions(DOCUMENT, [_region()])
    assert source_type_at(
        BOUNDARY, resolved, SourceType.REGULATORY_FILING
    ) is SourceType.PRESS_RELEASE


def test_the_last_region_beginning_at_or_before_the_span_wins() -> None:
    resolved = resolve_regions(
        DOCUMENT, [_region("Item 7.01"), _region("EXHIBIT 99.1", "marketing_material")]
    )
    exhibit = DOCUMENT.index("EXHIBIT 99.1")
    assert source_type_at(
        BOUNDARY + 10, resolved, SourceType.REGULATORY_FILING
    ) is SourceType.PRESS_RELEASE
    assert source_type_at(
        exhibit + 10, resolved, SourceType.REGULATORY_FILING
    ) is SourceType.MARKETING_MATERIAL


def test_no_regions_declared_leaves_every_span_on_the_document() -> None:
    for offset in (0, BOUNDARY, len(DOCUMENT) - 1):
        assert source_type_at(offset, (), SourceType.REGULATORY_FILING) is (
            SourceType.REGULATORY_FILING
        )


# ---------------------------------------------------------------------------
# reaching committed state — on both routes in
# ---------------------------------------------------------------------------


def _payload(*quotes: str) -> str:
    return json.dumps(
        {
            "claims": [
                {
                    "text": f"Claim {i}.",
                    "claim_type": "factual_claim",
                    "confidence": 0.9,
                    "evidence_quote": q,
                    "assumption": None,
                }
                for i, q in enumerate(quotes, start=1)
            ]
        }
    )


def _full_patch(quote: str, claimed_type: str, claimed_reliability: str) -> str:
    """The other way in: a patch the model wrote, asserting its own weight."""
    now = "2026-09-14T00:00:00Z"
    return json.dumps(
        {
            "patch_id": "patch_001",
            "base_state_id": "sr_x",
            "base_state_version": 0,
            "proposed_by": "llm_extract_transform@0.1.0",
            "created_at": now,
            "read_set": [],
            "add_objects": {
                "claims": [
                    {
                        "id": "claim_001",
                        "object_type": "claim",
                        "text": "A claim.",
                        "claim_type": "factual_claim",
                        "epistemic_status": "reported",
                        "confidence": 0.9,
                        "status": "active",
                        "supporting_evidence": ["ev_001"],
                        "assumptions": [],
                        "extracted_by": "transform_extract_001",
                    }
                ],
                "evidence": [
                    {
                        "id": "ev_001",
                        "object_type": "evidence",
                        "source_type": claimed_type,
                        "source_id": "doc_001",
                        "quote_or_span": quote,
                        "reliability": claimed_reliability,
                        "status": "active",
                        "extracted_by": "transform_extract_001",
                    }
                ],
            },
            "transform_record": {
                "id": "transform_extract_001",
                "transform_type": "extract",
                "operator": "llm_extract_transform",
                "operator_version": "llm_extract_transform@0.1.0",
                "input_state_version": 0,
                "output_state_version": None,
                "read_set": [],
                "write_set": ["claim_001", "ev_001"],
                "confidence_changes": [],
                "started_at": now,
                "finished_at": now,
            },
            "status": "proposed",
        }
    )


def _extract(tmp_path: Path, payload: str, regions: list[SourceRegion]):
    clock = FixedClock([NOW + dt.timedelta(seconds=10 * i) for i in range(20)])
    operator = LLMExtractOperator(
        MockProvider([payload], provider="fake", model="fake-extract-v0"),
        input_text=DOCUMENT,
        clock=clock,
        source_type=SourceType.REGULATORY_FILING,
        regions=regions,
    )
    runtime = Runtime(paths=RunPaths(root=tmp_path, run_id="regions"), clock=clock)
    result = runtime.run(
        initial_state=bootstrap_state(
            state_id="sr_x", project_id="p", name="filing", now=clock.now()
        ),
        operators=[operator],
        input_text=DOCUMENT,
    )
    assert result.final_state.state_version == 1, "the extraction must have committed"
    return result.final_state


def test_the_furnished_exhibit_is_not_weighed_as_the_filing(tmp_path: Path) -> None:
    """The defect, at its smallest: `region_001` in one assertion.

    Both spans come from one document declared `regulatory_filing`. Only the
    filed one is accountable, and the document says so in the text between them.
    """
    state = _extract(tmp_path, _payload(FILED_QUOTE, FURNISHED_QUOTE), [_region()])
    by_quote = {e.quote_or_span: e for e in state.evidence.values()}

    filed = by_quote[FILED_QUOTE]
    assert filed.reliability is Reliability.HIGH
    assert filed.source_type == SourceType.REGULATORY_FILING.value

    furnished = by_quote[FURNISHED_QUOTE]
    assert furnished.reliability is Reliability.LOW
    assert furnished.source_type == SourceType.PRESS_RELEASE.value


def test_without_regions_both_spans_are_weighed_as_the_filing(tmp_path: Path) -> None:
    """The before picture, and the no-op guarantee for everyone not using this."""
    state = _extract(tmp_path, _payload(FILED_QUOTE, FURNISHED_QUOTE), [])
    assert {e.reliability for e in state.evidence.values()} == {Reliability.HIGH}


def test_a_patch_asserting_its_own_weight_is_overruled_by_the_region(
    tmp_path: Path,
) -> None:
    """The second way in, which T8, T11, T14, T17 and T20 each had to close.

    A patch claiming the furnished exhibit is a `regulatory_filing` at `high`
    must not keep it: the region is the caller's fact, and believing the patch
    would restore exactly the defect.
    """
    state = _extract(
        tmp_path,
        _full_patch(FURNISHED_QUOTE, "regulatory_filing", "high"),
        [_region()],
    )
    item = next(iter(state.evidence.values()))
    assert item.reliability is Reliability.LOW
    assert item.source_type == SourceType.PRESS_RELEASE.value
