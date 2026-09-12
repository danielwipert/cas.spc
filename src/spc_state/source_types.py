"""What kind of document a span came from, and what that is worth.

`Evidence.reliability` decides how hard the pipeline looks for corroboration:
the Retriever opens an evidence-gap question for any under-confident claim that
does not rest on at least one `HIGH` span (`operators/retriever.py`), the
projection builder marks non-`HIGH` spans weak, and the Decision Memo flags a
finding supported only by `LOW` evidence. It is the one number that decides how
sceptical the rest of the run is.

Until now the *model* supplied it, as an `evidence_reliability` field in its own
extraction output. That is incoherent in two ways. It asks a model to grade the
trustworthiness of a document from the document itself, which is the one place
the answer cannot be found; and it lets the extraction that most wants scrutiny
exempt itself from it. Measured on a live run over a four-page corporate press
release, the model returned `high` for all ten spans it extracted — so the
Retriever found nothing to ask about, the run committed the company's own
framing at face value, and the memo recommended proceeding at 90% confidence.

Reliability is a property of *where the text came from*, which the operator
knows and the model does not. So it is declared once, for the document, and
derived here.

**The rule.** A source is `HIGH` when someone is accountable for the statement
being true — a legal duty of accuracy attaches to it, or an independent party
has checked it. It is `LOW` when the author has a stake in the conclusion and
nobody has checked it. Everything else — a disinterested author, an editorial
process, no verification — is `MEDIUM`.

`MEDIUM` is also the answer for a source nobody classified, and deliberately so.
"We do not know what this is" is not the same as "we know it is bad", so an
undeclared document is not smeared as `LOW`; but it does not get `HIGH` either,
which is the promotion that was previously free. Nothing reaches `HIGH` without
someone declaring where the text came from.
"""

from __future__ import annotations

from enum import Enum

from .models import Reliability

__all__ = [
    "DEFAULT_SOURCE_TYPE",
    "LEGACY_INPUT_DOCUMENT",
    "RELIABILITY_BY_SOURCE_TYPE",
    "SourceType",
    "coerce_source_type",
    "reliability_for",
]


class SourceType(str, Enum):
    """The kinds of document the pipeline knows how to weigh.

    Deliberately coarse. The taxonomy only has to separate sources that differ
    in *accountability*, because that is the only distinction `Reliability` can
    express; finer publisher-level judgement is not something three buckets can
    carry honestly.
    """

    # Accountable: a duty of accuracy, or an independent check.
    REGULATORY_FILING = "regulatory_filing"
    AUDITED_FINANCIALS = "audited_financials"
    COURT_RECORD = "court_record"
    OFFICIAL_STATISTICS = "official_statistics"
    PEER_REVIEWED = "peer_reviewed"

    # Disinterested, but unverified.
    NEWS_REPORT = "news_report"
    TECHNICAL_DOCUMENTATION = "technical_documentation"
    TRANSCRIPT = "transcript"
    INTERNAL_DOCUMENT = "internal_document"
    UNCLASSIFIED = "unclassified"

    # Interested: the author benefits from the conclusion.
    PRESS_RELEASE = "press_release"
    MARKETING_MATERIAL = "marketing_material"
    OPINION = "opinion"
    SOCIAL_MEDIA = "social_media"


#: What a source type is worth. Exhaustive over `SourceType` by construction —
#: `tests/test_source_types.py` fails if a member is added without a decision
#: here, so a new kind of document cannot inherit a reliability by accident.
RELIABILITY_BY_SOURCE_TYPE: dict[SourceType, Reliability] = {
    # Accountable for the statement being true.
    SourceType.REGULATORY_FILING: Reliability.HIGH,
    SourceType.AUDITED_FINANCIALS: Reliability.HIGH,
    SourceType.COURT_RECORD: Reliability.HIGH,
    SourceType.OFFICIAL_STATISTICS: Reliability.HIGH,
    SourceType.PEER_REVIEWED: Reliability.HIGH,
    # Disinterested, but nobody checked it.
    SourceType.NEWS_REPORT: Reliability.MEDIUM,
    SourceType.TECHNICAL_DOCUMENTATION: Reliability.MEDIUM,
    # A transcript is a reliable record of what was *said*, which is not a
    # reliable record of what is true — so the utterance, not its content.
    SourceType.TRANSCRIPT: Reliability.MEDIUM,
    SourceType.INTERNAL_DOCUMENT: Reliability.MEDIUM,
    SourceType.UNCLASSIFIED: Reliability.MEDIUM,
    # Written by a party with a stake in the conclusion.
    SourceType.PRESS_RELEASE: Reliability.LOW,
    SourceType.MARKETING_MATERIAL: Reliability.LOW,
    SourceType.OPINION: Reliability.LOW,
    SourceType.SOCIAL_MEDIA: Reliability.LOW,
}

#: What a caller gets for saying nothing. See the module docstring: not `LOW`,
#: and never `HIGH`.
DEFAULT_SOURCE_TYPE = SourceType.UNCLASSIFIED

#: The `source_type` string the pipeline wrote before this taxonomy existed, and
#: still writes from the deterministic demo extractor. Recognised so state
#: recorded by an older run — or a model that echoes the old vocabulary — is
#: read as "the document under analysis" rather than as some unknown source.
LEGACY_INPUT_DOCUMENT = "input_document"


def coerce_source_type(value: SourceType | str | None) -> SourceType:
    """Read a source type from a string, falling back to the default.

    Unknown strings do not raise: they arrive from stored state and from model
    output, where refusing to read a run is worse than weighing it cautiously.
    The CLI validates its own input up front, so a typo there is still caught.
    """
    if isinstance(value, SourceType):
        return value
    if value is None:
        return DEFAULT_SOURCE_TYPE
    try:
        return SourceType(value.strip().lower())
    except ValueError:
        return DEFAULT_SOURCE_TYPE


def reliability_for(value: SourceType | str | None) -> Reliability:
    """The reliability a span from this kind of source carries."""
    return RELIABILITY_BY_SOURCE_TYPE[coerce_source_type(value)]
