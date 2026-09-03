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
T0–T3 are done, T4–T7 open. This session closed two defects in the LLM path:
the audit-trail gap, then the planner retry.

All four definition-of-done gates pass on a fresh clone:

```
ruff check src tests   ->  All checks passed
python -m mypy         ->  Success: no issues found in 62 source files
pytest                 ->  194 passed
spc-demo demo          ->  artifacts byte-identical, DEMO.md unchanged
```

## What the last session did

Two fixes in the LLM path. Both were found by reviewing the repo; neither
touches the deterministic demo, so the frozen artifacts stay byte-stable.

### 1. Rejected LLM proposals stayed on the record

`Runtime.step` persists a patch *before* validation judges it; `step_llm` only
wrote one inside its COMMIT branch — so when a model proposed something
invalid, what it proposed was nowhere on disk. `step_llm` now mirrors `step`:
every attempt's raw completion is kept verbatim at
`patches/attempt_<NNN>_<K>.txt`, the final parse lands canonically whatever the
router decided, `patch.proposed` is emitted, each attempt keeps its own
validation report, and the fingerprint is stamped on the proposal so a rejected
patch still names its author. The `attempt_` prefix keeps these files out of
the `patch_*` / `validation_*` globs the §20.8 artifact counts use.
Tests: `tests/test_runtime_llm_audit_trail.py`.

### 2. Shape-invalid LLM output now retries (the T0 follow-on)

The planner REJECTed when the model returned valid JSON in the wrong shape,
spending 1 of 3 attempts, because the runtime only RETRYd on `JSON_DECODE`.
Two halves, both needed:

- **Routing.** `router.decide_llm` routes *any* L1 schema failure to RETRY on
  the LLM path — a model can repair its own output. `router.decide` is
  unchanged for deterministic operators, where the same failure is a code bug.
  L2 failures still REJECT on both paths: a well-formed patch that says
  something untrue about the state is a judgement, not a shape.
- **Feedback.** Routing alone would have misdirected the model. The validation
  issues are pydantic errors about `SemanticPatch` fields the planner never
  asked for (it asked for `{"hypothesis": ...}`). Operators that assemble a
  patch from a compact content shape now return an `OperatorCompletion`
  carrying a `repair_hint` from `LLMAssemblyError`, and `step_llm` prefers it.
  Wired in all four assembling operators, not just the planner — same defect.
  The assembly messages were rewritten to be directive, because they are now
  read by the model: `Your output must include a "hypothesis" object with a
  non-empty "text" field naming the single recommended course of action.`

Verified end to end with an injected provider that always returns the wrong
shape: 3 attempts spent (was 1), and each retry prompt carries the hint alone.

⚠ Note for live runs: a persistently wrong-shaped response now costs 3 model
calls instead of 1. That is the point of the retry budget, but it is a real
cost change on `analyze`.

## Next up

Nothing is half-finished — pick any of these cold.

1. **T7 — end-to-end test for `analyze`** (S). `cli.py` sits at 20% coverage
   and the five-stage pipeline has no composition test; every operator is
   tested alone. A wiring regression would pass the whole suite. This is the
   biggest remaining hole.
2. **T4 — State-graph visualizer** (M).
3. **T5 — Per-operator model routing + cost ledger** (M).
4. **T6 — SQLite `StateStore`** (L) ⚠ relaxes a documented v0.1 constraint —
   needs sign-off before starting.

An optional LLM-narrated memo is noted as a possible follow-on under T2, kept
off by default since re-prompting risks the drift SPC exists to prevent.

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
