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
T0–T3 are done, T4–T7 open. This session closed an audit-trail gap in the LLM
path — the first behaviour change since 2026-06-27.

All four definition-of-done gates pass on a fresh clone:

```
ruff check src tests   ->  All checks passed
python -m mypy         ->  Success: no issues found in 62 source files
pytest                 ->  186 passed
spc-demo demo          ->  artifacts byte-identical, DEMO.md unchanged
```

## What the last session did

**Reviewed the repo, then fixed the one real defect the review turned up.**

`Runtime.step` persists a patch *before* validation judges it, so a rejected
proposal stays on the record (`AGENTS.md §III`). `Runtime.step_llm` only wrote
a patch inside its COMMIT branch — so when a live `analyze` run had a model
propose something invalid, **what it proposed was nowhere on disk**. The
validation report said `patch_id: "unparsed_patch"` plus error codes; the audit
log recorded the decision; the content was gone. Verified before the fix with a
wrong-shape planner probe: `patches/` was empty.

`step_llm` now mirrors `step`:

- **Every attempt's raw completion is kept verbatim** at
  `patches/attempt_<NNN>_<K>.txt`, written before validation runs. Raw, because
  a completion may not parse into a patch at all.
- **The final attempt's parsed patch lands canonically** at
  `patches/patch_<NNN>.json` whatever the router decided — rejected included.
- **`patch.proposed` is emitted** on the LLM path (it never was), carrying the
  attempt number and `unparsed_patch` when nothing parsed.
- **Each attempt keeps its own validation report** at
  `validation/attempt_<NNN>_<K>.json`; retries used to overwrite a single file.
- **The proposal is stamped with the model fingerprint** before it is persisted,
  not only on commit — so a *rejected* patch still names its author (§10.6).

The `attempt_` prefix is deliberate: `evaluation/metrics.py` counts
`patch_*.json` and `validation_*.json` with non-recursive globs for the §20.8
artifact score, and the attempt files must not inflate it. A test pins that.

Eight acceptance tests in `tests/test_runtime_llm_audit_trail.py`. The
deterministic demo is untouched (it uses `step`, not `step_llm`), so the frozen
artifacts stay byte-stable.

## Next up

Nothing is half-finished — pick any of these cold.

1. **Planner RETRY fix** (unlisted, cheapest win). The planner REJECTs when the
   model returns valid JSON in the wrong shape, because the runtime only RETRYs
   on `JSON_DECODE`. Confirmed: 1 attempt used of `max_attempts=3`.
   ⚠ **Routing it to RETRY is not sufficient on its own.** The feedback fed back
   would be pydantic errors about `SemanticPatch` fields (`L1.MISSING`,
   `L1.EXTRA_FORBIDDEN`) — but the planner never asked the model for a
   `SemanticPatch`, it asked for the compact `{"hypothesis": ...}` shape. The
   operator has to supply its own repair feedback ("include a hypothesis"),
   which means `LLMAssemblyError`'s message needs to reach the retry loop.
   Noted as a follow-on under T0 in `TASKS.md`.
2. **T7 — end-to-end test for `analyze`** (S). `cli.py` sits at 20% coverage and
   the five-stage pipeline has no composition test; every operator is tested
   alone. A wiring regression would pass the whole suite.
3. **T4 — State-graph visualizer** (M).
4. **T5 — Per-operator model routing + cost ledger** (M).
5. **T6 — SQLite `StateStore`** (L) ⚠ relaxes a documented v0.1 constraint —
   needs sign-off before starting.

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
