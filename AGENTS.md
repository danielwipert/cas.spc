# AGENTS.md — Architectural Invariants for cas.spc

This file is for any human or AI contributor working on the SPC Shared
Semantic State Engine. It is short on purpose. Read it before writing code.

The canonical specification is [`PILOT_SPEC.md`](./PILOT_SPEC.md). This file
extracts the rules that must not be broken.

**Start here each session.** Read [`HANDOFF.md`](./HANDOFF.md) first — it is a
snapshot of what the previous session did and what comes next. Rewrite it at
the close of every session (overwrite wholesale; it is not a running ledger).

**Status (v0.1).** Phases 1–9 are complete and the pilot report has shipped
(see [`ROADMAP.md`](./ROADMAP.md)). The engine has two entry points, both over
the same runtime and the same patch loop:

- `spc-demo demo` / `run` — the deterministic pilot. `extract → planner →
  critic` with pattern-matching operators, byte-for-byte reproducible. The
  frozen artifacts (DEMO.md, pilot report, §8.4 follow-ups) are snapshot-tested;
  keep them byte-stable.
- `spc-demo analyze` — the live pipeline over *any* document, five stages:
  `extract → plan → critique → retrieve → verify`. Extract, plan, critique and
  the contradiction verifier are LLM-backed via OpenRouter; the retriever is
  deterministic (no model call). Output is a Decision Memo plus a Reasoning
  Receipt, both projected from committed state. Needs `OPENROUTER_API_KEY`, and
  the run is non-deterministic by nature.

All tasks T0–T13 in [`TASKS.md`](./TASKS.md) are done, T6 included (⚠
signed off 2026-09-03 — see §V). The backlog there is currently empty; add a
task before picking one up, and keep the invariants below intact.

Note the T8 invariant when touching the LLM extract path: an `Evidence` quote
must be locatable in the source document (`provenance.locate_span`), or the
operator asks the model to re-quote rather than committing the citation. That
holds on **both** ways in — assembled from compact content, or a full patch
passed through (T11).

Related trap: the runtime decides by validating the text an operator returns,
so an operator cannot reject output by handing it back unchanged if that output
would itself parse as a patch. See `_rejected_completion`.

If you change an LLM operator's **prompt**, re-record the T9 cassette
(`python tools/record_cassette.py record ...`, needs `OPENROUTER_API_KEY`).
`tests/test_live_replay.py` replays real model output offline and will tell you
the committed recording has gone stale.

---

## I. The Hard Invariant

> **No operator may directly mutate `SemanticState`.**
> All changes must be proposed as a `SemanticPatch`, validated by the
> runtime, routed (COMMIT / REVIEW / REJECT / RETRY), and committed into a
> new state version.

If you find yourself wanting to write to `state.claims[id] = ...` from
anywhere outside the runtime's `commit()` function, you are wrong.
Stop and propose a patch instead.

`SemanticState` instances are immutable (`model_config = ConfigDict(frozen=True)`).
A test asserts that direct attribute writes raise `ValidationError`. Do not
remove or weaken that test.

---

## II. The Operator Contract

Every operator obeys this contract (spec §13.5):

1. Receives a `Projection`, not raw `SemanticState`.
2. Returns a `SemanticPatch`.
3. Never mutates the projection or the underlying state.
4. Includes `read_set` and `write_set` in its `TransformRecord`.
5. Preserves provenance for new claims (evidence ref, assumption ref, or
   explicit `epistemic_status: speculative`).
6. Does not silently drop uncertainty (confidence, contradictions, open
   questions).
7. Does not propose overwriting committed objects without a versioned
   `update_objects` entry that includes `from`/`to`/`reason`.

A patch that violates this contract should be **caught by validation**, not
silently accepted. If validation lets a contract violation through, the bug
is in the validator — fix it there, not by patching the operator.

---

## III. The Patch is the Audit Trail

Patches are the only durable record of *who changed what and why*. They
must be:

- **Small enough to inspect.** One patch per operator step (spec §12.5).
- **Large enough to mean something.** Avoid per-field micro-patches.
- **Self-describing.** A patch must carry its own `transform_record`,
  `base_state_version`, `read_set`, `write_set`, and `reason` strings for
  every update.
- **Reproducible.** Given the same base state and the same patch, the
  runtime must produce the same next state. No nondeterminism inside the
  commit path.

---

## IV. Validation Layers

The runtime validates patches in this order (spec §16):

1. **L1 Schema** — Pydantic. Required fields, types, ID uniqueness,
   `confidence ∈ [0, 1]`, valid patch status, `base_state_version` present.
2. **L2 Referential / Provenance** — every referenced ID exists in base
   state; new major claims include provenance; no silent overwrite of
   committed objects.
3. **L3 Model-judgmental review** — optional smoke alarm. Flags for review,
   never the sole basis for rejection.
4. **L4 Heuristic** — large confidence jumps, empty-evidence high-confidence
   claims, sweeping conclusions from narrow input. Flags for review.

L1 and L2 are deterministic and must be enforced for every patch. L3 and L4
arrive in later phases.

---

## V. Storage Discipline

The pilot is file-based. Do not introduce a database, embedding index, or
queue in v0.1 — with one sanctioned, scoped exception (T6, signed off
2026-09-03): a SQLite backend for state-version storage only, opt-in per
caller, never the default. State versions live at:

```text
runs/<run_id>/state/semantic_state_v000.json
runs/<run_id>/state/semantic_state_v001.json
runs/<run_id>/state.sqlite3                        # opt-in alternative (T6) — not both
runs/<run_id>/patches/patch_<NNN>.json
runs/<run_id>/patches/attempt_<NNN>_<K>.txt        # LLM steps only
runs/<run_id>/validation/validation_<NNN>.json
runs/<run_id>/validation/attempt_<NNN>_<K>.json    # LLM steps only
runs/<run_id>/audit/audit_log.jsonl
runs/<run_id>/diffs/diff_v<A>_v<B>.json
runs/<run_id>/receipts/reasoning_receipt_v<N>.md
runs/<run_id>/cost_ledger.json                     # LLM-backed runs only
```

**The T6 exception, precisely.** `Runtime` depends only on
`StateStoreProtocol` (`store/store.py` — `write`/`read`/`latest_version`,
structural, not a base class), never on the file-based `StateStore`
directly. `store/sqlite_store.py::SQLiteStateStore` implements the same
protocol against a per-run `.sqlite3` file — same row content
(`model_dump_json(by_alias=True)`), different medium. Nothing else may use
this exception without its own sign-off: patches, validation, the audit
log, diffs, and receipts stay file-based no matter which state backend is
active. No CLI flag selects it — a caller wanting SQLite constructs
`SQLiteStateStore(paths)` and passes it to `Runtime(state_store=...)`
directly; the default remains file-based everywhere nothing opts in.

Every patch a runtime step proposes is written **before** validation judges
it, so a rejected proposal is still on the record (§III). An LLM step may take
several attempts (`Runtime.step_llm`), and a completion may not parse into a
patch at all: the `attempt_<NNN>_<K>` files hold each attempt's raw completion
and its validation report, while the canonical `patch_<NNN>.json` /
`validation_<NNN>.json` hold the final outcome. The `attempt_` prefix keeps
them out of the `patch_*` / `validation_*` globs the §20.8 artifact counts use.

`cost_ledger.json` (T5) sums estimated token spend per `TransformRecord` —
`src/spc_state/cost_ledger.py`, written only when a run actually called a
model, so a purely deterministic run adds no new file.

The `runs/` directory is **generated and gitignored**. Every demo run must
be reproducible from `examples/` plus the engine. Do not commit run output.

---

## VI. Projections, Not Raw State

Operators receive perspective-specific projections. The critic does not see
what the writer sees. This is not optimization — it is a correctness
property: an operator that receives the whole state can accidentally use
information that didn't belong to its perspective, making the system harder
to reason about and audit.

Projections may **emphasize or hide**, but **must not mutate** canonical
state (spec §14.4).

---

## VII. LLM Operators (wired in Phases 6–7)

The mock provider (Phase 6) and a live OpenRouter provider (Phase 7) are in the
tree. Any LLM operator — existing or new:

- must return structured `SemanticPatch` JSON, not prose;
- on any output the runtime cannot validate as a patch — prose, malformed JSON,
  or valid JSON in the wrong shape — the runtime routes to RETRY and asks
  again (`Runtime.step_llm`, routed by `router.decide_llm`). Do not silently
  repair. A model can fix its own output, so **every** L1 schema failure is
  retryable on this path; L2 referential failures still REJECT, because a
  well-formed patch that says something untrue about the state is a judgement,
  not a shape;
- if it assembles its own patch from a compact content shape, it returns an
  `OperatorCompletion` carrying a `repair_hint` when assembly fails. The
  validator can only report the `SemanticPatch` fields it found missing — which
  the operator never asked the model for — so the operator supplies the repair
  feedback instead, phrased for the shape it actually requested;
- records provider, model, and resolved version in
  `TransformRecord.model_fingerprint`, and (T5) token usage in
  `TransformRecord.token_usage` — the runtime stamps both once per step,
  summed across every retry attempt, since a retry is a real billed call;
  `cost_ledger.py` prices these into `runs/<id>/cost_ledger.json`;
- chooses a **value-based, per-task** model — never a hardcoded frontier
  flagship — and keeps the model configurable. **Per-operator model
  routing is just handing different operators differently-configured
  provider instances** — there is no separate mechanism to opt into;
- **never asks the model for a fact about the world outside the document**
  (T14). The model contributes semantic *content* — what the claims are, which
  span supports each. Facts about the source itself belong to the caller, who
  knows them, and the operator derives from that: `Evidence.reliability` comes
  from the declared `source_type` (`source_types.py`), not from an
  `evidence_reliability` field the model fills in. A model asked to grade the
  trustworthiness of a document from inside that document will grade its own
  extraction generously — measured, it rated 6 of 11 spans of a corporate press
  release `high`. If you find yourself adding a prompt field for something the
  caller already knows and the model cannot see, that is the same mistake;
- is tested with an **injected client** (no network, no key in CI). A test must
  show that an LLM proposing direct-mutation prose ("the new state is …") is
  **rejected**, not absorbed.

LLMs are processors, not authorities. The runtime decides what commits.

---

## VIII. What This Repo Is Not

- Not a chatbot.
- Not an autonomous agent.
- Not a knowledge graph.
- Not a vector database.
- Not a production system.

It is a kernel that tests one architectural claim. The pilot report has now
shipped — extensions are welcome (see [`TASKS.md`](./TASKS.md)), but each one
must keep the kernel honest: the operator/patch invariant holds, and the
v0.1 constraints above (file-based storage, no DB/index/queue) only relax by a
deliberate, documented decision.

---

## IX. When in Doubt

The spec is authoritative. If `AGENTS.md` and `PILOT_SPEC.md` disagree,
the spec wins, and someone should update this file.
