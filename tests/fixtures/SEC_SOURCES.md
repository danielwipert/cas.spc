# Where the SEC fixtures came from

`sec_8k_netflix.txt` and `sec_8k_wbd.txt` are excerpts of two public filings,
retrieved from EDGAR. They are kept as **pure document text** — no header, no
comment lines — because the extractor reads the whole file, and anything added
here would become extractable content and show up as a claim.

| fixture | filing | CIK | accession | file |
|---|---|---|---|---|
| `sec_8k_netflix.txt` | Netflix, Inc. Form 8-K, Item 1.01, filed 2025-12-05 | 0001065280 | 0001193125-25-308651 | `d65144d8k.htm` |
| `sec_8k_wbd.txt` | Warner Bros. Discovery, Inc. Form 8-K, Item 1.01, filed 2025-12-05 | 0001437107 | 0001193125-25-309873 | `d73469d8k.htm` |

Both are reachable at
`https://www.sec.gov/Archives/edgar/data/<cik>/<accession without dashes>/<file>`.
EDGAR requires a `User-Agent` naming the requester; a bare request gets a 403.

**What was trimmed.** Item 1.01 only, and within it the paragraphs stating the
merger agreement's parties and date, the board approvals, and the consideration.
The text inside each retained paragraph is **verbatim** — that is what makes it
usable as evidence, since T8 requires every citation to be locatable in the
source. The equity-award mechanics and the exhibit list were dropped to keep the
fixtures small.

**Why these two.** They describe the same agreement from opposite sides of it:
two separate registrants, each legally accountable for its own Item 1.01, and
neither derived from the other. That is what lets a claim reach `VERIFIED` — the
pairing the backlog had been asking for since T19, and the one
`tests/test_verify_replay.py` pins.
