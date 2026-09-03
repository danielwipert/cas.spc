# Handoff

> **Protocol.** Read this file at the start of every session. Rewrite it at the
> close of every session. It is a **snapshot, not a ledger** — it holds only
> what was just done and what comes next. Overwrite it wholesale each time;
> never append. The durable record lives in git history, `ROADMAP.md`, and
> `TASKS.md` — not here.

**Last session:** 2026-09-03 · **Branch:** `claude/project-review-7als6t`

---

## Where things stand

Roadmap complete through **Phase 9**; all three milestones shipped. Tasks
T0–T5 and T7 are done — only **T6** (SQLite `StateStore`, ⚠ needs sign-off)
remains. This session closed two defects in the LLM path (audit trail,
planner retry), then shipped T7, T4, and T5 in sequence.

All four definition-of-done gates pass on a fresh clone:

```
ruff check src tests   ->  All checks passed
python -m mypy         ->  Success: no issues found in 65 source files
pytest                 ->  222 passed
spc-demo demo          ->  artifacts byte-identical, DEMO.md unchanged
```

## What the last session did

Five pieces of work, each verified against the four gates before moving on.
None touch the deterministic demo, so the frozen artifacts stay byte-stable.

### 1–2. Two LLM-path defects (audit trail, planner retry)

See git log (`Runtime: keep rejected LLM proposals on the record`, `LLM path:
retry shape-invalid output with the operator's own feedback`) — both fixes
and their tests are unchanged since. Summary: a rejected LLM proposal used to
vanish entirely (nothing on disk); now every attempt is persisted verbatim,
the final parse lands as the canonical patch regardless of outcome, and the
model is named even when rejected. Separately, the planner used to REJECT
(no retry) on valid JSON in the wrong shape, wasting 2 of 3 attempts; the LLM
path now RETRYs on any L1 schema failure (`router.decide_llm`), and operators
supply their own repair hint (`OperatorCompletion.repair_hint`) rather than
misdirecting the model with `SemanticPatch`-shaped validator noise.

### 3. T7 — end-to-end test for the `analyze` pipeline

`cli.analyze`'s operator list + runtime run factored into
`src/spc_state/analyze.py` (`run_analysis`), shared by the CLI and
`tests/test_analyze_pipeline.py`. `cli.py` was ~20% covered with the whole
five-stage pipeline untested; `analyze.py` is now 100% covered.

### 4. T4 — state-graph Mermaid export

`src/spc_state/receipt/graph.py` (`render_mermaid_graph`) projects a
`SemanticState` to a Mermaid flowchart — one node per active object, one edge
per active `Relation` (never invented from a claim's `assumptions`/
`supporting_evidence` fields). Embedded into `render_markdown()` as a new
"State Graph" section, so every Reasoning Receipt gets one — both `demo` and
`analyze`, no CLI changes. `tests/fixtures/reasoning_receipt_demo.md`
regenerated to match; confirmed `DEMO.md` doesn't change (it counts the
receipt as a metric, never renders its content).

### 5. T5 — per-operator model routing + cost ledger

**Per-operator model routing needed no new mechanism** — every operator
already takes its own `LLMProvider`, and a provider carries its own model;
two operators with two differently-configured providers already run two
different models. What's new is the accounting:

- `TokenUsage` (`models/transform.py`) on `ProviderResponse.usage` — real API
  usage from OpenRouter when reported, a deterministic estimate
  (`tokens.py`) otherwise (`MockProvider` always estimates).
- `TransformRecord.token_usage` — `Runtime.step_llm` now sums usage across
  *every* attempt of a step (a retry is a real, billed call, not a free
  do-over) and stamps the total the same way it stamps `model_fingerprint` —
  including on a REJECTed patch, composing directly with fix #1 above.
  `LLMContradictionOperator`'s two-pass detection sums both its calls into
  the one `TransformRecord` they share.
- `providers/openrouter.py::estimate_cost_usd` + a small illustrative
  pricing table, unlisted models falling back to a documented default
  instead of a misleading $0.00.
- `src/spc_state/cost_ledger.py` (`build_cost_ledger`, `write_cost_ledger`) —
  one entry per `TransformRecord` that spent tokens; writes
  `runs/<id>/cost_ledger.json`. Wired into `analyze.py` (always) and into
  `cli.py run` / `demo.py run_full_demo`'s `--live-critic` paths only, so the
  deterministic default writes no new file.

Known, documented scope boundary: a step where every attempt was unparseable
never assembles a patch, so it has no `TransformRecord` to ledger — the
ledger sums per `TransformRecord`, per its literal T5 scope, not a full
attempt-by-attempt accounting. 22 new/changed tests across
`tests/test_cost_ledger.py`, `test_openrouter_provider.py`, and
`test_analyze_pipeline.py`. `cost_ledger.py` and `runtime/loop.py` are 100%
covered.

## Next up

Only **T6 — SQLite `StateStore`** (L) remains in `TASKS.md`, and it is ⚠
gated: it relaxes a documented v0.1 constraint (`AGENTS.md §V` — file-based
storage only), so get sign-off before starting it.

Everything else is genuinely open-ended:

- An optional LLM-narrated memo, noted as a possible follow-on under T2, kept
  off by default since re-prompting risks the drift SPC exists to prevent.
- A possible follow-on under T4: give contradictions an explicit `Relation`
  to each claim they conflict with, so contradiction nodes stop being
  visually isolated in the state graph — changes what the contradiction
  operator commits, not just how it's rendered, so it wasn't done alongside
  T4 itself.
- A possible follow-on under T5: attempt-level (not just per-`TransformRecord`)
  cost accounting, to capture the tokens spent on a step that never produced
  a patch at all (every attempt unparseable). Documented as a known boundary,
  not a bug, but a real gap if a live run needs to reconcile against an
  actual OpenRouter invoice.

Full specs with acceptance tests are in [`TASKS.md`](./TASKS.md).

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
