"""Regions — reliability is a property of the span, not of the document (T22).

T14 established that `Evidence.reliability` is a fact about *where the text came
from*, which the caller knows and the model cannot see. It then stamped one value
on every span in the file, and a filing is not one block of accountability.

The SEC's own machinery says so in the document's own words. An 8-K's Item 1.01
is **filed** and carries Section 18 liability; its Item 7.01 is **furnished**,
and the filing states the difference outright:

    "The information contained in this Item 7.01, including Exhibit 99.1, shall
    not be deemed 'filed' for purposes of Section 18 of the Securities Exchange
    Act of 1934 ... or otherwise subject to the liabilities of that section."

EDGAR serves every filing as one complete submission concatenating the 8-K body
with all of its exhibits, so "the 8-K" as a user downloads it holds an accountable
region and a region the document disclaims. Measured (`region_001`): declared
`regulatory_filing`, **three of six claims** came from the disclaimed region at
`HIGH` — the press release's marketing copy among them, weighed exactly as
heavily as the merger agreement's terms.

**A region is declared, not detected.** Whether Item 7.01 is furnished is a fact
about securities law, not something visible from inside the sentence, so it comes
from the caller for exactly T14's reason. A pipeline that silently knew what an
"Item 7.01" was would have taken a fact about the world into itself, which is the
mistake T14 exists to prevent — and it would work on one filing format and
quietly mislead on every other.

**Nothing new has to be derived.** T8 made every citation locatable and T10
hardened it, so `Evidence.location` already carries offsets into the source. A
region is a marker plus a source type; a span takes the source type of the last
region beginning at or before it, and the document's own declaration before that.

With no regions declared the whole document is one region and every span is
weighed exactly as it was — this module is a no-op for anyone who does not use it.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from .provenance import locate_span
from .source_types import SourceType, coerce_source_type

__all__ = [
    "RegionError",
    "ResolvedRegion",
    "SourceRegion",
    "parse_region",
    "resolve_regions",
    "source_type_at",
]


class RegionError(ValueError):
    """A declared region could not be resolved against the document."""


@dataclass(frozen=True)
class SourceRegion:
    """A caller's declaration: "from this marker onward, weigh spans as this"."""

    marker: str
    source_type: SourceType


@dataclass(frozen=True)
class ResolvedRegion:
    """A `SourceRegion` located in a specific document."""

    start: int
    source_type: SourceType


def parse_region(spec: str) -> SourceRegion:
    """Parse a `"<marker>:<source_type>"` declaration.

    Split on the **last** colon, because a marker legitimately contains one:
    `"Item 7.01: Regulation FD Disclosure:press_release"` is a marker of
    `"Item 7.01: Regulation FD Disclosure"`, not a parse error.
    """
    marker, _, raw_type = spec.rpartition(":")
    if not marker.strip() or not raw_type.strip():
        raise RegionError(
            f"--region {spec!r} is not '<marker>:<source_type>'. The marker is "
            "text to find in the document; the source type says how to weigh "
            "spans from there on."
        )
    known = {s.value for s in SourceType}
    if raw_type.strip() not in known:
        raise RegionError(
            f"--region {spec!r} names an unknown source type "
            f"{raw_type.strip()!r}. Known: {', '.join(sorted(known))}."
        )
    return SourceRegion(marker.strip(), coerce_source_type(raw_type.strip()))


def resolve_regions(
    document: str, regions: Sequence[SourceRegion]
) -> tuple[ResolvedRegion, ...]:
    """Locate every declared marker in `document`, in document order.

    A marker that does not occur **raises**. Ignoring it would leave a document
    that looks region-aware and is not — the caller would believe the exhibit had
    been discounted while every span still carried the filing's weight, which is
    the failure this task exists to prevent.

    Markers are located with the same `locate_span` the extractor uses for
    citations, so a marker survives the whitespace and hyphenation differences a
    real document has.
    """
    resolved: list[ResolvedRegion] = []
    for region in regions:
        match = locate_span(region.marker, document)
        if match is None:
            raise RegionError(
                f"--region marker {region.marker!r} does not occur in the "
                "document. A region that cannot be located would silently leave "
                "every span at the document's own weight."
            )
        resolved.append(ResolvedRegion(match.start, region.source_type))
    # Stable sort keeps declaration order among markers at the same offset, and
    # `source_type_at` takes the last match — so the later declaration wins.
    return tuple(sorted(resolved, key=lambda r: r.start))


def source_type_at(
    offset: int, regions: Sequence[ResolvedRegion], default: SourceType
) -> SourceType:
    """How to weigh a span starting at `offset`.

    The last region beginning at or before the span wins; before the first
    region, the document's own declared type stands. A span starting exactly at a
    marker belongs to that region — the marker heading is part of what it marks.
    """
    current = default
    for region in regions:
        if region.start <= offset:
            current = region.source_type
        else:
            break
    return current
