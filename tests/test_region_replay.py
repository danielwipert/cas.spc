"""T27 — regions, reproducible from a clean clone.

The last of the four live runs T25 named. `region_001` / `region_002`
demonstrated T22 — that reliability belongs to the *span*, not the document —
over an 8-K whose own text disclaims half of itself, and they lived in a
scratchpad like the rest.

The fixture is Netflix's Form 8-K as EDGAR serves the complete submission
(`tests/fixtures/SEC_SOURCES.md`): Item 1.01, which is **filed** and carries
Section 18 liability, followed by Item 7.01 and Exhibit 99.1, which are
**furnished** — and the filing says so in its own words, in the fixture:

    "The information contained in this Item 7.01, including Exhibit 99.1, shall
    not be deemed 'filed' for purposes of Section 18 ..."

Declared `regulatory_filing` with no regions, every span in that document is
weighed as accountable — the press release's marketing copy exactly as heavily
as the merger agreement's terms. One `--region "Item 7.01:press_release"` and
the second half is repriced.

**One recording, replayed twice.** Unlike lineage (T26), a region changes
neither the prompts nor which calls the run makes: it is read after the model
has answered, when the spans are stamped. So both runs here replay the *same*
cassette, with zero drift, which makes this the controlled experiment T26 could
not be — identical model output, one declaration different.
"""

from __future__ import annotations

import datetime as dt
import tempfile
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path

import pytest

from spc_state.analyze import AnalysisResult, run_analysis
from spc_state.modality import spans_are_unsettled
from spc_state.models import EpistemicStatus, Reliability, SemanticState
from spc_state.operators.calibration import (
    GROUNDING_FACTOR,
    MODALITY_FACTOR,
    RELIABILITY_FACTOR,
    _floor2,
)
from spc_state.providers import ReplayProvider
from spc_state.regions import RegionError, SourceRegion, parse_region, resolve_regions
from spc_state.runtime import FixedClock
from spc_state.store import RunPaths

FIXTURES = Path(__file__).parent / "fixtures"
CASSETTES = FIXTURES / "cassettes"
COMPLETE_8K = FIXTURES / "sec_8k_netflix_complete.txt"
CASSETTE = CASSETTES / "analyze_8k_complete.json"
QUESTION = "What did Netflix agree to, and on what terms?"

#: What the caller declares: from the Item 7.01 heading on, this is furnished.
FURNISHED = "Item 7.01:press_release"

#: The disclaimer the filing makes about itself. Quoted from the fixture, because
#: the whole argument for declaring the region is that the document says this.
DISCLAIMER = 'shall not be deemed “filed” for purposes of Section 18'


@dataclass(frozen=True)
class Replay:
    """One replayed run, plus the memo it projected."""

    provider: ReplayProvider
    result: AnalysisResult
    memo: str

    @property
    def final(self) -> SemanticState:
        return self.result.run.final_state

    def calibrated(self) -> dict[str, tuple[float, float]]:
        """Each claim the calibrator moved, as `(from, to)`.

        Read off the patch rather than diffed out of two states: the calibration
        step records what it changed and why, which is the audit trail this
        engine exists to keep (AGENTS.md §III).
        """
        step = self.result.run.steps[-1]
        assert step.patch is not None, "the calibration step proposed no patch"
        assert step.patch.transform_record.transform_type == "calibrate"
        moved: dict[str, tuple[float, float]] = {}
        for update in step.patch.update_objects:
            if update.field == "confidence" and update.object_id in self.final.claims:
                moved[update.object_id] = (
                    float(update.from_value),
                    float(update.to_value),
                )
        return moved

    def is_unsettled(self, claim_id: str) -> bool:
        """Does every span this claim cites talk about an unsettled event (T23)?"""
        claim = self.final.claims[claim_id]
        quotes = [
            self.final.evidence[eid].quote_or_span
            for eid in claim.supporting_evidence
            if eid in self.final.evidence
        ]
        return bool(quotes) and spans_are_unsettled(quotes)

    def offset_of(self, claim_id: str) -> int:
        """Where in the document the span supporting this claim begins."""
        claim = self.final.claims[claim_id]
        for eid in claim.supporting_evidence:
            evidence = self.final.evidence.get(eid)
            if evidence is not None:
                start = evidence.location.get("start")
                if isinstance(start, int):
                    return start
        raise AssertionError(f"{claim_id} cites no locatable span")


def _document() -> str:
    return COMPLETE_8K.read_text(encoding="utf-8")


def _cut() -> int:
    """The offset the declared region starts at, resolved the way the run does."""
    return resolve_regions(_document(), [parse_region(FURNISHED)])[0].start


def _replay(regions: Sequence[SourceRegion]) -> Replay:
    document = _document()
    provider = ReplayProvider.from_path(CASSETTE, document=document)
    clock = FixedClock(
        [dt.datetime(2026, 9, 15, tzinfo=dt.UTC) + dt.timedelta(seconds=10 * i)
         for i in range(120)]
    )
    with tempfile.TemporaryDirectory() as tmp:
        result = run_analysis(
            provider,
            document,
            RunPaths(root=Path(tmp), run_id="region_replay"),
            clock=clock,
            question=QUESTION,
            source_type="regulatory_filing",
            regions=regions,
        )
        memo = (
            Path(result.memo_path).read_text(encoding="utf-8")
            if result.memo_path is not None
            else ""
        )
    return Replay(provider=provider, result=result, memo=memo)


@pytest.fixture(scope="module")
def undeclared() -> Iterator[Replay]:
    """The whole filing weighed as one block, which is what T22 found wrong."""
    yield _replay(())


@pytest.fixture(scope="module")
def declared() -> Iterator[Replay]:
    """The same run, with the furnished half declared as what it is."""
    yield _replay((parse_region(FURNISHED),))


# ---------------------------------------------------------------------------
# the precondition: one document, two kinds of accountability
# ---------------------------------------------------------------------------


def test_the_filing_disclaims_half_of_itself() -> None:
    """The document's own words are the reason the region is declarable.

    Whether Item 7.01 is furnished is a fact about securities law, not something
    the pipeline may infer — but it is not a fact the caller invented either.
    The filing states it, and the fixture keeps the sentence.
    """
    document = _document()
    assert DISCLAIMER in document
    cut = _cut()
    assert 0 < cut < len(document), "the marker must split the document, not top it"
    assert document.index(DISCLAIMER) > cut, "the disclaimer sits inside what it disclaims"


def test_both_halves_carry_claims(undeclared: Replay) -> None:
    """A split with nothing on one side would demonstrate nothing."""
    cut = _cut()
    sides = {cid: undeclared.offset_of(cid) >= cut for cid in undeclared.final.claims}
    assert any(sides.values()) and not all(sides.values())


# ---------------------------------------------------------------------------
# the structural finding: this is a controlled experiment
# ---------------------------------------------------------------------------


def test_one_recording_serves_both_settings(
    undeclared: Replay, declared: Replay
) -> None:
    """A region changes what state records, not what the model is asked.

    It is resolved against offsets the extractor already recorded (T8/T10) and
    applied when spans are stamped, after the model has answered. So both runs
    send byte-identical requests and make the same number of calls, and the same
    cassette replays for both with no drift — which is what makes every
    difference below attributable to the declaration alone.

    Lineage (T26) is the contrast: it also changes no prompt, but it drops
    corroboration candidates before the skeptic pass, so it changes the *calls*
    and needs its own recording.
    """
    assert undeclared.provider.drifted_calls == [], (
        f"{CASSETTE.name} predates the current prompts — re-record it with "
        "tools/record_cassette.py (see the command in TASKS.md T27)"
    )
    assert declared.provider.drifted_calls == []
    assert undeclared.provider.call_count == declared.provider.call_count
    assert undeclared.provider.exhausted and declared.provider.exhausted
    assert sorted(undeclared.final.claims) == sorted(declared.final.claims)


# ---------------------------------------------------------------------------
# the contrast
# ---------------------------------------------------------------------------


def test_undeclared_the_furnished_half_is_weighed_as_filed(
    undeclared: Replay,
) -> None:
    """The defect T22 exists to fix, on real output.

    Declare the document `regulatory_filing` and every span in it is `HIGH` —
    including the ones the filing itself says are not filed.
    """
    final = undeclared.final
    assert {e.reliability for e in final.evidence.values()} == {Reliability.HIGH}
    cut = _cut()
    assert [cid for cid in final.claims if undeclared.offset_of(cid) >= cut], (
        "no claim came from the furnished half, so nothing was mis-weighed"
    )


def test_declaring_the_region_splits_the_document_at_the_marker(
    declared: Replay,
) -> None:
    """Every span takes the weight of the region it falls in, and only that.

    Asserted from the offsets rather than from claim ids, so the test says what
    the rule is instead of restating one recording's answer.
    """
    cut = _cut()
    for evidence in declared.final.evidence.values():
        start = evidence.location.get("start")
        assert isinstance(start, int)
        expected = Reliability.LOW if start >= cut else Reliability.HIGH
        assert evidence.reliability is expected, (
            f"span at {start} (cut {cut}) is {evidence.reliability}"
        )


def test_only_the_furnished_claims_move(
    undeclared: Replay, declared: Replay
) -> None:
    """Nothing in the filed half is touched, and everything after it drops."""
    cut = _cut()
    for cid in undeclared.final.claims:
        before = undeclared.final.claims[cid].confidence
        after = declared.final.claims[cid].confidence
        if undeclared.offset_of(cid) >= cut:
            assert after < before, f"{cid} is furnished and did not drop"
        else:
            assert after == pytest.approx(before), f"{cid} is filed and moved"


def test_what_the_furnished_claims_drop_to(
    undeclared: Replay, declared: Replay
) -> None:
    """The arithmetic, derived from the constants rather than typed.

    A claim is damped once, by `min(reliability, grounding)` (T16/T21). Both
    halves are `REPORTED`, so grounding is the same on both sides and the only
    thing that changes is the reliability the span carries. Read off the
    calibration patch's own `from`/`to`, which is where the run records what it
    moved and why — and the `from` values are identical across the two runs,
    because it is the same recorded model output.
    """
    grounding = GROUNDING_FACTOR[EpistemicStatus.REPORTED]
    cut = _cut()
    before = undeclared.calibrated()
    after = declared.calibrated()
    assert {cid: v[0] for cid, v in before.items()} == {
        cid: v[0] for cid, v in after.items()
    }, "the two runs calibrated different raw confidences"

    moved = [cid for cid in before if undeclared.offset_of(cid) >= cut]
    assert moved
    for cid in moved:
        raw = before[cid][0]
        # Modality multiplies on top of the warrant axis rather than joining its
        # `min` (T23), and it is untouched by the region — a future event is no
        # more settled for being filed. Carrying it here keeps the assertion
        # about the one factor the declaration changes.
        modality = MODALITY_FACTOR if undeclared.is_unsettled(cid) else 1.0
        assert before[cid][1] == _floor2(
            raw * min(RELIABILITY_FACTOR[Reliability.HIGH], grounding) * modality
        )
        assert after[cid][1] == _floor2(
            raw * min(RELIABILITY_FACTOR[Reliability.LOW], grounding) * modality
        )


def test_the_recommendation_follows_its_weakest_limb(
    undeclared: Replay, declared: Replay
) -> None:
    """T15 carries the repricing up to the recommendation without being told to.

    Nothing in the calibrator knows about regions. It caps a recommendation at
    the weakest claim it cites, and one of those claims now rests on a press
    release — so the number the reader sees falls out of the same rule.
    """
    for replay in (undeclared, declared):
        for hypothesis in replay.final.hypotheses.values():
            cited = [
                replay.final.claims[cid].confidence
                for cid in hypothesis.supporting_claims
                if cid in replay.final.claims
            ]
            if cited:
                assert hypothesis.confidence == pytest.approx(min(cited))

    assert max(h.confidence for h in declared.final.hypotheses.values()) < max(
        h.confidence for h in undeclared.final.hypotheses.values()
    )


def test_the_retriever_asks_one_more_question(
    undeclared: Replay, declared: Replay
) -> None:
    """A second rule reprices itself off the same declaration.

    The Retriever questions a claim resting only on lower-reliability evidence.
    Undeclared, the furnished spans are `HIGH` and it has nothing to ask about
    them; declared, it asks — so the run does not merely lower numbers, it
    surfaces work a reader can act on.
    """
    assert len(declared.final.questions) > len(undeclared.final.questions)
    new = set(declared.final.questions) - set(undeclared.final.questions)
    assert new
    cut = _cut()
    furnished = {cid for cid in declared.final.claims if declared.offset_of(cid) >= cut}
    for qid in new:
        question = declared.final.questions[qid]
        assert any(cid in furnished for cid in question.linked_objects), (
            f"{qid} is not about a claim from the furnished half"
        )


def test_the_memo_tells_the_reader_which_it_is(
    undeclared: Replay, declared: Replay
) -> None:
    """The artifact a stakeholder opens, which is where this has to land.

    The evidence appendix names each span's source type, so the same quote reads
    `regulatory_filing` in one run and `press_release` in the other.
    """
    assert "press_release:doc_001" not in undeclared.memo
    assert "press_release:doc_001" in declared.memo
    assert "regulatory_filing:doc_001" in declared.memo, (
        "the filed half must still read as filed"
    )


# ---------------------------------------------------------------------------
# keeping the recording, and the declaration, honest
# ---------------------------------------------------------------------------


def test_a_marker_that_does_not_occur_raises() -> None:
    """T22's stated invariant, exercised on the live path rather than a unit.

    Silently ignoring an unlocatable marker would leave a run that looks
    region-aware and is not: the caller believes the exhibit was discounted
    while every span still carries the filing's weight.
    """
    with pytest.raises(RegionError, match="does not occur"):
        _replay((parse_region("Item 42.99:press_release"),))


def test_the_cassette_is_pinned_to_its_filing() -> None:
    from spc_state.providers.cassette import CassetteError

    document = _document()
    ReplayProvider.from_path(CASSETTE, document=document)
    with pytest.raises(CassetteError, match="recorded against different"):
        ReplayProvider.from_path(CASSETTE, document=document + " tampered")
