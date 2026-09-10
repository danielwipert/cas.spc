# Handoff

> **Protocol.** Read this file at the start of every session. Rewrite it at the
> close of every session. It is a **snapshot, not a ledger** — it holds only
> what was just done and what comes next. Overwrite it wholesale each time;
> never append. The durable record lives in git history, `ROADMAP.md`, and
> `TASKS.md` — not here.

**Last session:** 2026-09-03 · **Branch:** `claude/project-review-7als6t`

---

## Where things stand

Roadmap complete through **Phase 9**; all three milestones shipped. **The
entire `TASKS.md` backlog is now done — T0 through T7, including T6.** This
session closed two defects in the LLM path (audit trail, planner retry),
then shipped T7, T4, T5, and T6 in sequence, each verified against the four
gates before moving to the next.

All four definition-of-done gates pass on a fresh clone:

```
ruff check src tests   ->  All checks passed
python -m mypy         ->  Success: no issues found in 66 source files
pytest                 ->  236 passed
spc-demo demo          ->  artifacts byte-identical, DEMO.md unchanged
```

## What the last session did

Six pieces of work. None touch the deterministic demo — verified with a real
`spc-demo demo` run after every single one, not just at the end.

### 1–2. Two LLM-path defects (audit trail, planner retry)

A rejected LLM proposal used to vanish entirely (nothing on disk); every
attempt is now persisted verbatim, the final parse lands as the canonical
patch regardless of outcome, and the model is named even when rejected.
Separately, the planner used to REJECT (no retry) on valid JSON in the wrong
shape, wasting 2 of 3 attempts; the LLM path now RETRYs on any L1 schema
failure, and operators supply their own repair hint rather than misdirecting
the model with `SemanticPatch`-shaped validator noise.

### 3. T7 — end-to-end test for the `analyze` pipeline

`cli.analyze`'s operator list + runtime run factored into
`src/spc_state/analyze.py` (`run_analysis`), shared by the CLI and
`tests/test_analyze_pipeline.py`. `analyze.py` is 100% covered.

### 4. T4 — state-graph Mermaid export

`src/spc_state/receipt/graph.py` (`render_mermaid_graph`) — one node per
active object, one edge per active `Relation`, never invented from a
claim's structural fields. Embedded into every Reasoning Receipt as a new
"State Graph" section. `tests/fixtures/reasoning_receipt_demo.md`
regenerated; `DEMO.md` confirmed unaffected (it counts the receipt as a
metric, never renders its content).

### 5. T5 — per-operator model routing + cost ledger

Per-operator model routing needed no new mechanism — every operator already
takes its own `LLMProvider`, and a provider carries its own model. Built the
accounting around that: `TokenUsage` on `ProviderResponse`/`TransformRecord`,
summed across every retry attempt (a retry is a real billed call) and
stamped even on a rejected patch (composes with fix #1). `cost_ledger.py`
prices these via `providers/openrouter.py::estimate_cost_usd` into
`runs/<id>/cost_ledger.json` — wired into `analyze` always, and into the two
`--live-critic` paths only, so the deterministic default writes nothing new.

### 6. T6 ⚠ — SQLite-backed StateStore (sign-off given this session)

`StateStoreProtocol` (`store/store.py`) — a structural `Protocol`, three
methods (`write`/`read`/`latest_version`) — is what `Runtime` actually
depends on. `Runtime.__init__` gained exactly one optional keyword,
`state_store: StateStoreProtocol | None = None`; omitted, it builds the
file-based store exactly as before. That is the *entire* runtime-side
change — matches the "the runtime must not change" invariant literally, not
just in spirit.

`src/spc_state/store/sqlite_store.py` (`SQLiteStateStore`) implements the
same protocol against a per-run `.sqlite3` file — one table, one row per
version, the row payload the exact same `model_dump_json(by_alias=True)`
text the file backend writes. Everything else (patches, validation, audit,
diffs, receipts) stays file-based regardless of backend; no CLI flag was
added — T6 proves the seam exists, it doesn't ship a new user-facing switch.

Incidental fix found while testing: `RunPaths.ensure_dirs()` used to
unconditionally pre-create an empty `state/` directory, which was already
redundant for the file backend (self-creates on first write) and actively
misleading for a SQLite-backed run (an empty dir sitting next to
`state.sqlite3`). Removed.

`tests/test_store_backends.py`: a 6-test generic behavioral suite
parametrized over both backends (12 runs), plus the literal acceptance
scenario — the full deterministic demo pipeline run once per backend,
asserting the committed state history is identical **object-for-object**
(not just version numbers), while confirming the storage medium genuinely
differs so the comparison isn't accidentally testing the same backend
against itself. `sqlite_store.py` is 100% covered.

## Next up

**T8 is queued** — added 2026-09-10 after running a real document through
the live `analyze` pipeline (a 4-page press release, `deepseek/deepseek-chat`,
5/5 stages COMMIT, ~$0.0014). That test found no fabricated evidence but
proved nothing would have caught one: the extractor copies the model's quote
verbatim and no validation layer ever sees the source document. T8 adds the
check. Note the measured constraint recorded in the task — only 2 of 10
quotes were byte-exact substrings of the input, so exact matching is the
wrong implementation.

Other options, none urgent:
- The two possible follow-ons noted inline in `TASKS.md`: an optional
  LLM-narrated memo (T2, kept off by default — re-prompting risks the drift
  SPC exists to prevent), and giving contradictions an explicit `Relation`
  to each claim they conflict with so they stop being visually isolated in
  the T4 state graph (changes what the contradiction operator commits, not
  just how it renders, so it wasn't bundled into T4 itself).
- A possible T5 follow-on: attempt-level (not just per-`TransformRecord`)
  cost accounting, to capture tokens spent on a step that never produced a
  patch at all. Documented as a known, deliberate boundary in T5 — real if a
  live run ever needs to reconcile against an actual OpenRouter invoice.
- If a SQLite-backed *end-to-end* run is wanted (not just the storage seam
  proven, which T6 already did) — a `--state-backend sqlite` CLI flag on
  `run`/`analyze`/`demo`, plus teaching `_load_history`/`followups`/`memo`
  which backend a given run used. Deliberately not built in T6: that's a
  new user-facing feature, a different scope than "prove the seam is real."

## Gate notes a future session still needs

**Run `python -m mypy`, never bare `mypy`.** The `mypy` on PATH is a
uv-installed tool in an isolated environment that cannot see pydantic, typer or
rich; it reports ~17 phantom `import-not-found` errors.

> ⚠ **Do not "fix" UP042.** It wants `class X(str, Enum)` → `StrEnum` across
> `models/enums.py`. Verified in a REPL: that changes `str()` and f-string
> output from `ObjectType.CLAIM` to `claim`, which would silently alter every
> rendered receipt and memo and break the byte-stable demo artifacts. The
> ignore is deliberate and documented at the rule.

## Before touching code

Read [`AGENTS.md`](./AGENTS.md). The hard invariant: **no operator mutates
`SemanticState` directly** — all change flows through a validated
`SemanticPatch`. The full definition of done is in `TASKS.md`; note that
`spc-demo demo` rewrites `DEMO.md` in the repo root, so run it with the default
`--runs-dir` or the run path gets baked into the committed file.
