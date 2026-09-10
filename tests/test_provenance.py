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
