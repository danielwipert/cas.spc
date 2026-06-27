# AGENTS.md — Architectural Invariants for cas.spc

This file is for any human or AI contributor working on the SPC Shared
Semantic State Engine. It is short on purpose. Read it before writing code.

The canonical specification is [`PILOT_SPEC.md`](./PILOT_SPEC.md). This file
extracts the rules that must not be broken.

**Status (v0.1).** Phases 1–8 plus the narrated demo are complete and the pilot
report has shipped (see [`ROADMAP.md`](./ROADMAP.md)). The engine runs
`extract → planner → critic` deterministically, a live OpenRouter critic is
wired behind the same loop, and `spc-demo demo` tells the whole story. Open
work is tracked in [`TASKS.md`](./TASKS.md); pick a task from there and keep the
invariants below intact.

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
queue in v0.1. State versions live at:

```text
runs/<run_id>/state/semantic_state_v000.json
runs/<run_id>/state/semantic_state_v001.json
runs/<run_id>/patches/patch_<NNN>.json
runs/<run_id>/validation/validation_<NNN>.json
runs/<run_id>/audit/audit_log.jsonl
runs/<run_id>/diffs/diff_v<A>_v<B>.json
runs/<run_id>/receipts/reasoning_receipt_v<N>.md
```

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
- on prose or malformed JSON, the runtime routes to RETRY with the validation
  error passed back (`Runtime.step_llm`). Do not silently repair;
- records provider, model, and resolved version in
  `TransformRecord.model_fingerprint`;
- chooses a **value-based, per-task** model — never a hardcoded frontier
  flagship — and keeps the model configurable;
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
