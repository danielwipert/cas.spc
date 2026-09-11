"""T8 — evidence quotes are verified against the source document.

Two halves. `locate_span` is a pure function, tested directly against the
normalization contract in `provenance.py`. Then the operator half: an injected
`MockProvider` (no network, no key) proves a fabricated quote never reaches
committed state as a citation, and that the model is told precisely what to
repair.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

from spc_state.operators import LLMExtractOperator
from spc_state.provenance import locate_span, normalize
from spc_state.providers.mock import MockProvider
from spc_state.runtime import FixedClock, Runtime, bootstrap_state
from spc_state.store import RunPaths

DOCUMENT = (
    "A company is weighing a permanent remote-work policy. Studies show a 13% "
    "productivity gain for routine tasks, but managers reported weaker ad-hoc "
    "collaboration when teams are fully remote."
)


# ---------------------------------------------------------------------------
# locate_span — the normalization contract
# ---------------------------------------------------------------------------


def test_verbatim_quote_locates_at_its_real_offsets() -> None:
    quote = "Studies show a 13% productivity gain for routine tasks"
    match = locate_span(quote, DOCUMENT)
    assert match is not None
    # The offsets index the original document, not the normalized form.
    assert DOCUMENT[match.start : match.end] == quote


def test_quote_spanning_a_line_break_locates() -> None:
    """The single most common real failure: PDF text breaks lines mid-sentence."""
    document = "The combined company will own a film\nlibrary of more than 15,000 titles."
    match = locate_span("The combined company will own a film library of more than 15,000 titles.", document)
    assert match is not None
    assert match.start == 0
    assert document[match.start : match.end] == document


def test_typographic_quotes_and_dashes_fold() -> None:
    document = "Paramount (“the buyer”) — a studio — said so."
    assert locate_span("Paramount ('the buyer') - a studio - said so.", document) is not None


def test_added_terminal_period_locates() -> None:
    """A bullet has no full stop; a model quoting it habitually adds one."""
    document = "- Committed to producing a minimum of 30 theatrical films annually\n"
    match = locate_span(
        "Committed to producing a minimum of 30 theatrical films annually.", document
    )
    assert match is not None
    assert document[match.start : match.end].endswith("annually")


def test_quote_truncated_at_a_comma_locates() -> None:
    match = locate_span("Studies show a 13% productivity gain for routine tasks.", DOCUMENT)
    assert match is not None
    assert DOCUMENT[match.start : match.end].endswith("routine tasks")


def test_line_end_hyphenation_locates_however_it_is_quoted() -> None:
    """PDF extraction of justified text splits words at line ends.

    The same document text must be findable whether the model joins the word,
    copies the hyphen and break literally, or copies it with the break already
    collapsed to a space.
    """
    document = "a material impair-\nment charge was recorded"
    for quote in (
        "a material impairment charge",
        "a material impair-\nment charge",
        "a material impair- ment charge",
    ):
        match = locate_span(quote, document)
        assert match is not None, quote
        # Offsets point at the document's own text, hyphen and break intact.
        assert document[match.start : match.end] == "a material impair-\nment charge"


def test_a_real_hyphen_that_wrapped_still_locates() -> None:
    """The ambiguous case that rules out simply joining every line-end hyphen.

    "pre-\ntax" is a compound that happened to wrap, not a split word, and a
    model quotes it "pre-tax". Both readings are tried, so both resolve.
    """
    assert locate_span("a pre-tax non-cash charge", "a pre-\ntax non-cash charge") is not None
    assert locate_span("a pretax non-cash charge", "a pre-\ntax non-cash charge") is not None


def test_soft_hyphen_character_is_ignored() -> None:
    """U+00AD is a discretionary break, never part of the word."""
    assert locate_span("impairment charge", "impair\u00adment charge") is not None


def test_a_standalone_dash_is_never_erased() -> None:
    """A hyphen must be attached to a word to count as a line-end split.

    Found by an adversarial sweep: without this, the join reading erased a
    standalone dash, so a quote that dropped or moved it still matched. A dash
    between spaces separates clauses and is content.
    """
    document = "MERIDIAN GRID CORPORATION - CURRENT REPORT filed today"
    assert locate_span("MERIDIAN GRID CORPORATION CURRENT REPORT", document) is None
    assert locate_span("MERIDIAN GRID - CORPORATION CURRENT REPORT", document) is None
    assert locate_span("MERIDIAN GRID CORPORATION - CURRENT REPORT", document) is not None


def test_an_in_word_hyphen_is_not_dropped() -> None:
    """The boundary: leniency covers breaks, not hyphens inside a word.

    Nothing marks "ausserplan-maessige" as split — no break follows the hyphen —
    so quoting it joined drops a character the source contains. A real recorded
    model did exactly this; see `tests/test_live_replay.py`.
    """
    document = "eine ausserplan-maessige Wertberichtigung"
    assert locate_span("eine ausserplanmaessige Wertberichtigung", document) is None
    assert locate_span("eine ausserplan-maessige Wertberichtigung", document) is not None


def test_fabricated_quote_does_not_locate() -> None:
    assert locate_span("Studies show a 40% productivity gain", DOCUMENT) is None
    assert locate_span("Leadership plans to grow headcount", DOCUMENT) is None


def test_paraphrase_and_dropped_words_do_not_locate() -> None:
    """Normalization must not paper over an altered span."""
    assert locate_span("Studies show a productivity gain for routine tasks", DOCUMENT) is None
    assert locate_span("Studies indicate a 13% productivity gain", DOCUMENT) is None


def test_fabricated_quote_ending_in_punctuation_does_not_locate() -> None:
    """Trailing-punctuation tolerance must not rescue a span that is not there."""
    assert locate_span("Studies show a 40% productivity gain.", DOCUMENT) is None
    assert locate_span("The board approved the policy!", DOCUMENT) is None


def test_locate_span_answers_presence_only() -> None:
    """A documented boundary: `locate_span` asks "is this span here?", nothing more.

    An ellipsis is absent from the document, so it does not locate. A lone
    period genuinely *is* a span of the document and therefore does — it is a
    useless citation, but judging a quote's substance is a separate concern
    from verifying its provenance, and inventing a minimum length here would
    be an undocumented policy of its own.
    """
    assert locate_span("...", DOCUMENT) is None
    assert locate_span(".", DOCUMENT) is not None


def test_case_change_does_not_locate() -> None:
    """Case is content, not transport — deliberately not normalized."""
    assert locate_span("STUDIES SHOW A 13% PRODUCTIVITY GAIN", DOCUMENT) is None


def test_a_quote_that_is_only_a_dangling_hyphen() -> None:
    """Under the join reading this normalizes to nothing, which must never match.

    It still resolves against a document that really contains a dash — the
    presence-only boundary documented above, the same as a lone ".".
    """
    assert locate_span("- ", "a document with no dashes at all") is None
    assert locate_span("- ", "a document with a - dash in it") is not None


def test_empty_quote_never_locates() -> None:
    assert locate_span("", DOCUMENT) is None
    assert locate_span("   \n\t ", DOCUMENT) is None


def test_normalize_is_deterministic_and_collapses_whitespace() -> None:
    assert normalize("a  \n\t b") == "a b"
    assert normalize(DOCUMENT) == normalize(DOCUMENT)


# ---------------------------------------------------------------------------
# the operator half
# ---------------------------------------------------------------------------


def _claim(quote: str) -> dict[str, object]:
    return {
        "text": "Remote work raises measured productivity.",
        "claim_type": "analytical_claim",
        "epistemic_status": "inferred",
        "confidence": 0.7,
        "evidence_quote": quote,
        "evidence_reliability": "medium",
        "assumption": None,
    }


def _payload(*quotes: str) -> str:
    return json.dumps({"claims": [_claim(q) for q in quotes]})


def _clock() -> FixedClock:
    start = dt.datetime(2026, 6, 26, tzinfo=dt.UTC)
    return FixedClock([start + dt.timedelta(seconds=30 * i) for i in range(12)])


def _run(root: Path, script: list[str]):
    paths = RunPaths(root=root, run_id="provenance")
    clock = _clock()
    provider = MockProvider(script, provider="fake", model="fake-extract-v0")
    runtime = Runtime(paths=paths, clock=clock)
    result = runtime.run(
        initial_state=bootstrap_state(
            state_id="sr_x", project_id="p", name="Remote work", now=clock.now()
        ),
        operators=[LLMExtractOperator(provider, input_text=DOCUMENT, clock=clock)],
        input_text=DOCUMENT,
    )
    return paths, result


def _full_patch(quote: str, *, source_type: str = "input_document") -> str:
    """A complete `SemanticPatch`, the shape a model sometimes returns unasked.

    `_assemble` passes such a patch straight through rather than building one,
    so this is the path that must not skip the provenance check.
    """
    now = "2026-06-26T00:00:00Z"
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
                        "text": "Remote work raises measured productivity.",
                        "claim_type": "analytical_claim",
                        "epistemic_status": "inferred",
                        "confidence": 0.7,
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
                        "source_type": source_type,
                        "source_id": "doc_001",
                        "quote_or_span": quote,
                        "reliability": "high",
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


GOOD_QUOTE = "Studies show a 13% productivity gain for routine tasks"
FABRICATED = "Studies show a 40% productivity gain for routine tasks"


def test_fabricated_quote_never_commits(tmp_path: Path) -> None:
    """Every attempt fabricates, so nothing reaches state — v0, no citations."""
    _, result = _run(tmp_path, [_payload(FABRICATED)])
    final = result.final_state
    assert final.state_version == 0
    assert final.evidence == {}
    assert final.claims == {}


def test_fabricated_quote_is_retried_then_repaired(tmp_path: Path) -> None:
    """Attempt 1 fabricates, attempt 2 quotes the document — commit on the retry."""
    paths, result = _run(tmp_path, [_payload(FABRICATED), _payload(GOOD_QUOTE)])
    final = result.final_state
    assert final.state_version == 1
    assert [e.quote_or_span for e in final.evidence.values()] == [GOOD_QUOTE]

    # A retry is a real, separately billed call (T5) — both attempts are on the
    # record, not just the one that won.
    attempts = sorted(p.name for p in paths.patches_dir.glob("attempt_001_*.txt"))
    assert attempts == ["attempt_001_01.txt", "attempt_001_02.txt"]
    assert FABRICATED in paths.patch_attempt_file(1, 1).read_text()


def test_repair_hint_names_the_offending_span(tmp_path: Path) -> None:
    """The model is told which quote failed, not just that something did."""
    other = "Leadership plans to grow headcount next year"
    paths, _ = _run(tmp_path, [_payload(FABRICATED, other)])
    audit = (paths.audit_dir / "audit_log.jsonl").read_text()
    retries = [
        json.loads(line)
        for line in audit.splitlines()
        if json.loads(line)["event"] == "patch.retry"
    ]
    assert retries, "a quote that is not in the document must trigger a retry"
    hint = retries[0]["repair_hint"]
    assert "do not appear in the document" in hint
    # Both offenders are reported together, so one retry can fix both.
    assert "40% productivity gain" in hint
    assert "grow headcount" in hint


def test_located_quote_records_its_offsets(tmp_path: Path) -> None:
    """`Evidence.location` was always `{}` — now it pins the span in the source."""
    _, result = _run(tmp_path, [_payload(GOOD_QUOTE)])
    evidence = next(iter(result.final_state.evidence.values()))
    start, end = evidence.location["start"], evidence.location["end"]
    assert isinstance(start, int) and isinstance(end, int)
    assert DOCUMENT[start:end] == GOOD_QUOTE


# ---------------------------------------------------------------------------
# the full-patch passthrough — the same rule, the other way in
# ---------------------------------------------------------------------------


def test_passthrough_patch_with_a_fabricated_quote_never_commits(
    tmp_path: Path,
) -> None:
    """A model-authored patch must not smuggle an unverified citation through.

    `_assemble` trusts such a patch's *shape* to the validator — but the
    validator is never handed the source document, so without this check the
    span would commit and render as provenance.
    """
    _, result = _run(tmp_path, [_full_patch(FABRICATED)])
    final = result.final_state
    assert final.state_version == 0
    assert final.evidence == {}


def test_passthrough_patch_is_retried_then_repaired(tmp_path: Path) -> None:
    """Rejection feeds the same retry loop, so the model can re-quote."""
    _, result = _run(tmp_path, [_full_patch(FABRICATED), _full_patch(GOOD_QUOTE)])
    final = result.final_state
    assert final.state_version == 1
    assert [e.quote_or_span for e in final.evidence.values()] == [GOOD_QUOTE]


def test_passthrough_patch_records_its_offsets(tmp_path: Path) -> None:
    """The same guarantee as the assembled path: a citation you can resolve."""
    _, result = _run(tmp_path, [_full_patch(GOOD_QUOTE)])
    evidence = next(iter(result.final_state.evidence.values()))
    start, end = int(evidence.location["start"]), int(evidence.location["end"])
    assert DOCUMENT[start:end] == GOOD_QUOTE


def test_passthrough_leaves_other_sources_alone(tmp_path: Path) -> None:
    """Only spans claiming to come from *this* document are ours to verify.

    Evidence citing an external source has no text here to check against, so it
    passes through unverified rather than being rejected for the wrong reason.
    """
    _, result = _run(tmp_path, [_full_patch(FABRICATED, source_type="external_source")])
    final = result.final_state
    assert final.state_version == 1
    evidence = next(iter(final.evidence.values()))
    assert evidence.quote_or_span == FABRICATED
    assert evidence.location == {}, "no offsets claimed for text we cannot see"


def test_repair_hint_summarises_when_many_spans_fail(tmp_path: Path) -> None:
    """Four offenders name three and count the rest — a hint, not a dump."""
    quotes = [f"Studies show a {n}% productivity gain" for n in (40, 50, 60, 70)]
    paths, _ = _run(tmp_path, [_payload(*quotes)])
    audit = (paths.audit_dir / "audit_log.jsonl").read_text(encoding="utf-8")
    hint = next(
        json.loads(line)["repair_hint"]
        for line in audit.splitlines()
        if json.loads(line)["event"] == "patch.retry"
    )
    assert "4 evidence_quote value(s) do not appear" in hint
    assert "and 1 more" in hint


def test_passthrough_evidence_without_a_quote_is_skipped(tmp_path: Path) -> None:
    """An empty span has nothing to locate, and is not an unlocatable one."""
    _, result = _run(tmp_path, [_full_patch("   ")])
    final = result.final_state
    assert final.state_version == 1, "an empty quote is not a provenance failure"
    assert next(iter(final.evidence.values())).location == {}
