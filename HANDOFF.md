# Handoff

> **Protocol.** Read this file at the start of every session. Rewrite it at the
> close of every session. It is a **snapshot, not a ledger** — it holds only
> what was just done and what comes next. Overwrite it wholesale each time;
> never append. The durable record lives in git history, `ROADMAP.md`, and
> `TASKS.md` — not here.

**Last session:** 2026-09-10 · **Branch:** `claude/fervent-franklin-k6nffp`

---

## Where things stand

Roadmap complete through **Phase 9**; all three milestones shipped. The
`TASKS.md` backlog is **done through T9** and is empty again.

This session was the first to run a **real, non-demo document end to end
through the live pipeline**. That test found a gap, the gap became T8, and T8
shipped and was verified against live model output.

All four definition-of-done gates pass on a fresh clone:

```
ruff check src tests   ->  All checks passed
python -m mypy         ->  Success: no issues found in 68 source files
pytest                 ->  265 passed
spc-demo demo          ->  artifacts byte-identical, DEMO.md unchanged
```

## What the last session did

### 1. First live end-to-end run on a real document

A 4-page press release (Paramount/WBD merger announcement, ~3,300 words) run
through `spc-demo analyze` on `deepseek/deepseek-chat`. All five stages
COMMIT, no retries: 10 claims, 10 evidence, 4 assumptions, 1 hypothesis, 7
questions, 0 contradictions (correct — a press release does not argue with
itself). Whole run: 8,226 tokens, ~$0.0014.

The PDF needed converting to text first (`analyze` reads UTF-8 text, not PDF).
`pypdf` did it; note the container's Debian `cryptography` is broken and has to
be shadowed with `pip install --ignore-installed cffi cryptography` first.

### 2. T8 — evidence quotes verified against the source document

The run's real finding: **nothing checked that an evidence quote was actually
in the document.** The extractor copied the model's `evidence_quote` on trust
and no validation layer is ever handed the source text, so a fabricated span
would have committed silently and rendered as an `[E#]` citation in the memo.
Nothing was fabricated in that run — but only by luck.

Measurement that shaped the design: only **2 of 10 spans were byte-exact**
substrings of the input. PDF extraction breaks lines mid-sentence, the model
folds typographic quotes to ASCII, and it adds terminal periods to bullets. So
exact matching would have rejected 8 good quotes. `provenance.locate_span`
compares under a documented normalization instead, and returns offsets into the
original document (now stored in `Evidence.location`, previously always `{}`).

Verified on live output, not just fixtures: re-running the same press release
with the check active, all 10 spans located on the **first attempt**, no false
rejections, every offset resolving to a real span.

### 3. T9 — live-run regression harness (record/replay cassettes)

`providers/cassette.py`: `RecordingProvider` captures a live provider's
completions verbatim, `ReplayProvider` feeds them back offline. A real
`deepseek/deepseek-chat` five-stage run is committed as
`tests/fixtures/cassettes/analyze_five_stage.json` (over an authored fixture
document, not third-party text), so CI regression-tests the whole pipeline
against genuine model output with no key and no network.

Exhaustion raises rather than repeating; document identity is verified; prompt
drift is *reported*, not fatal, because a contributor without a key cannot
re-record. Re-record or inspect drift with `tools/record_cassette.py`.

**If you change an LLM operator's prompt, re-record the cassette** —
`test_committed_cassette_matches_the_current_prompts` is the signal.

### 4. Gate fix — `mypy` was environment-dependent

`from openai import OpenAI` carried an inline
`type: ignore[import-not-found]`, required when the optional `openrouter` extra
is absent and flagged as an unused ignore when it is installed. Replaced with
an `ignore_missing_imports` override scoped to `openai.*`, keeping
`warn_unused_ignores = true` project-wide. Verified clean both with and without
the extra. This mattered because working on T8 requires installing that extra.

## Next up

**The `TASKS.md` backlog is empty.** Nothing is queued. Options, none urgent:

- **A second cassette for a failure path.** The committed one is a clean
  five-stage success. A recording where the model fabricates a quote, or
  returns prose, would regression-test the retry/reject paths against real
  output too — those are currently only mock-driven.
- **Attempt-level cost accounting** (the T5 follow-on): tokens spent on a step
  that never produced a patch at all are not currently reconciled. T8 makes
  this more likely to matter — a rejected extraction now burns up to 3 billed
  attempts and commits nothing.
- **Contradictions need an explicit `Relation`** to the claims they conflict
  with, or they stay visually isolated in the T4 state graph. Changes what the
  contradiction operator commits, not just how it renders.
- **`--state-backend sqlite`** if a SQLite-backed end-to-end run is wanted; T6
  proved the seam, this would ship the user-facing switch.

## Gate notes a future session still needs

**Run `python -m mypy`, never bare `mypy`.** The `mypy` on PATH is a
uv-installed tool in an isolated environment that cannot see pydantic, typer or
rich; it reports ~17 phantom `import-not-found` errors.

A fresh container has **no dev dependencies installed** — `pip install -e
".[dev]"` first, plus `pip install openai` (or the `openrouter` extra) for any
live path.

> ⚠ **Do not "fix" UP042.** It wants `class X(str, Enum)` → `StrEnum` across
> `models/enums.py`. Verified in a REPL: that changes `str()` and f-string
> output from `ObjectType.CLAIM` to `claim`, which would silently alter every
> rendered receipt and memo and break the byte-stable demo artifacts. The
> ignore is deliberate and documented at the rule.

> ⚠ **`provenance.py`'s fold table is written as unicode escapes, not literal
> characters.** Several of those characters are invisible or ASCII-lookalikes
> in an editor, and ruff's RUF001 flags the literals as ambiguous. Keep the
> escapes.

## Before touching code

Read [`AGENTS.md`](./AGENTS.md). The hard invariant: **no operator mutates
`SemanticState` directly** — all change flows through a validated
`SemanticPatch`. Since T8 there is a second one on the LLM extract path: an
`Evidence` quote must be locatable in the source document, or the operator asks
the model to re-quote rather than committing the citation. The full definition
of done is in `TASKS.md`; note that `spc-demo demo` rewrites `DEMO.md` in the
repo root, so run it with the default `--runs-dir` or the run path gets baked
into the committed file.
