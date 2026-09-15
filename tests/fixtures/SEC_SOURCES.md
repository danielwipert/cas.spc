# Where the SEC fixtures came from

These are excerpts of public filings, retrieved from EDGAR. They are kept as
**pure document text** — no header, no comment lines — because the extractor
reads the whole file, and anything added here would become extractable content
and show up as a claim.

| fixture | filing | CIK | accession | file |
|---|---|---|---|---|
| `sec_8k_netflix.txt` | Netflix, Inc. Form 8-K, Item 1.01, filed 2025-12-05 | 0001065280 | 0001193125-25-308651 | `d65144d8k.htm` |
| `sec_8k_wbd.txt` | Warner Bros. Discovery, Inc. Form 8-K, Item 1.01, filed 2025-12-05 | 0001437107 | 0001193125-25-309873 | `d73469d8k.htm` |
| `joint_pr_netflix.txt` | Netflix, Inc. Form 8-K, Exhibit 99.1, filed 2025-12-05 | 0001065280 | 0001193125-25-308651 | `d65144dex991.htm` |
| `joint_pr_wbd.txt` | Warner Bros. Discovery, Inc. Form 8-K, Exhibit 99.1, filed 2025-12-05 | 0001437107 | 0001193125-25-308759 | `d16580dex991.htm` |
| `sec_8k_netflix_complete.txt` | Netflix, Inc. Form 8-K body **+** its Exhibit 99.1 | 0001065280 | 0001193125-25-308651 | `d65144d8k.htm` + `d65144dex991.htm` |

All are reachable at
`https://www.sec.gov/Archives/edgar/data/<cik>/<accession without dashes>/<file>`.
EDGAR requires a `User-Agent` naming the requester; a bare request gets a 403.

**What was trimmed.** Item 1.01 only, and within it the paragraphs stating the
merger agreement's parties and date, the board approvals, and the consideration.
The text inside each retained paragraph is **verbatim** — that is what makes it
usable as evidence, since T8 requires every citation to be locatable in the
source. The equity-award mechanics and the exhibit list were dropped to keep the
fixtures small.

**Why the two 8-K excerpts.** They describe the same agreement from opposite
sides of it: two separate registrants, each legally accountable for its own
Item 1.01, and neither derived from the other. That is what lets a claim reach
`VERIFIED` — the pairing the backlog had been asking for since T19, and the one
`tests/test_verify_replay.py` pins.

**Why the two Exhibit 99.1 excerpts, which are the opposite case.** They are the
**same joint press release**, filed by each counterparty as its own exhibit —
two accession numbers, two `source_id`s, one document. The retained text is
word-for-word identical; the files differ only in where each filer's HTML wraps
the headline, and the fixtures keep that rather than normalising it away. Every
corroboration the pipeline finds between them is therefore false, which is what
makes the pair worth committing: `tests/test_lineage_replay.py` runs it with the
lineage undeclared and declared, and the declaration is the only difference.

Note that WBD filed the release under a **different accession** from its Item
1.01 8-K: the Item 7.01 filing of the same day, which is why the two WBD rows
above name different accessions.

**Why the complete submission.** `sec_8k_netflix_complete.txt` is the one
fixture that is not a single continuous excerpt: it is the 8-K body's Item 1.01
and Item 7.01 followed by the Exhibit 99.1 press release, which is how EDGAR
serves a filing as one submission and how a user who downloads "the 8-K" reads
it. That makes it one document containing two kinds of accountability — Item
1.01 is *filed* and carries Section 18 liability, Item 7.01 and its exhibit are
*furnished*, and the filing says so itself in a sentence the fixture keeps.
`tests/test_region_replay.py` replays it twice, with the region declared and
without.

**What was kept in it.** From the body: the Item 1.01 heading and the two
paragraphs stating the merger's parties and the consideration, then Item 7.01
in full — it is three short paragraphs, one of which is the disclaimer the whole
exercise turns on. From the exhibit: the headline block, the dateline, the
valuation paragraph and two of the benefit bullets, because the marketing copy
is exactly what is mis-weighed when the document is treated as one block.

**What was trimmed from the press releases.** The headline block, the dateline
paragraph and the "Transaction Details and Timing" section. The marketing
narrative, the executive quotes, the bullet list of benefits, the advisor roster
and the contact block were dropped, on the same principle as the 8-Ks: keep the
paragraphs that assert checkable facts, verbatim.
