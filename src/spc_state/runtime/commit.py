"""Apply a validated SemanticPatch to produce the next SemanticState version.

See PILOT_SPEC.md §15. This is the **only** function in the codebase that
returns a SemanticState different from the one it was given. Every other
operator, validator, projector, and CLI handler treats `SemanticState` as
immutable.

The commit produces:
- a new top-level container with `state_version` bumped and `updated_at` set,
- every new object from `patch.add_objects` inserted into its container,
- every `update_objects` entry applied via `obj.model_copy(update={...})`,
- every `archive_objects` entry flipped to `status='archived'`,
- the patch's relations appended to `state.relations`,
- the patch's `transform_record` appended to `transform_log` with the new
  `output_state_version` filled in,
- the patch_id appended to `audit.committed_patches`.

The base state is not mutated. The returned state is a fresh frozen model.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from ..models import (
    Assumption,
    Claim,
    Contradiction,
    Entity,
    Evidence,
    Hypothesis,
    Inference,
    ObjectStatus,
    Question,
    Relation,
    SemanticPatch,
    SemanticState,
)
from ..models.patch import ArchiveObject, UpdateObject


class CommitError(RuntimeError):
    """The runtime tried to commit a patch that did not survive validation."""


def commit_patch(
    state: SemanticState,
    patch: SemanticPatch,
    *,
    now: dt.datetime,
) -> SemanticState:
    """Return the post-commit `SemanticState`. Does not mutate `state`."""
    next_version = state.state_version + 1

    # Copy each container so we can mutate the copies safely.
    entities = dict(state.entities)
    claims = dict(state.claims)
    evidence = dict(state.evidence)
    assumptions = dict(state.assumptions)
    inferences = dict(state.inferences)
    hypotheses = dict(state.hypotheses)
    questions = dict(state.questions)
    contradictions = dict(state.contradictions)
    relations: list[Relation] = list(state.relations)

    # 1. Add new objects.
    for e in patch.add_objects.entities:
        entities[e.id] = e
    for c in patch.add_objects.claims:
        claims[c.id] = c
    for ev in patch.add_objects.evidence:
        evidence[ev.id] = ev
    for a in patch.add_objects.assumptions:
        assumptions[a.id] = a
    for inf in patch.add_objects.inferences:
        inferences[inf.id] = inf
    for h in patch.add_objects.hypotheses:
        hypotheses[h.id] = h
    for q in patch.add_objects.questions:
        questions[q.id] = q
    for con in patch.add_objects.contradictions:
        contradictions[con.id] = con

    containers: dict[str, dict[str, Any]] = {
        "entities": entities,
        "claims": claims,
        "evidence": evidence,
        "assumptions": assumptions,
        "inferences": inferences,
        "hypotheses": hypotheses,
        "questions": questions,
        "contradictions": contradictions,
    }

    # 2. Apply field updates.
    for upd in patch.update_objects:
        _apply_update(containers, relations, upd)

    # 3. Archive objects (soft-delete).
    for arc in patch.archive_objects:
        _apply_archive(containers, relations, arc)

    # 4. Append relations.
    relations.extend(patch.add_relations)

    # 5. Append transform record with the resolved output version.
    new_transform = patch.transform_record.model_copy(
        update={"output_state_version": next_version}
    )
    transform_log = [*state.transform_log, new_transform]

    # 6. Bump audit ledger.
    new_audit = state.audit.model_copy(
        update={"committed_patches": [*state.audit.committed_patches, patch.patch_id]}
    )

    # 7. Build the next state via model_copy on the frozen base.
    return state.model_copy(
        update={
            "state_version": next_version,
            "previous_state_version": state.state_version,
            "updated_at": now,
            "entities": entities,
            "claims": claims,
            "evidence": evidence,
            "assumptions": assumptions,
            "inferences": inferences,
            "hypotheses": hypotheses,
            "questions": questions,
            "contradictions": contradictions,
            "relations": relations,
            "transform_log": transform_log,
            "audit": new_audit,
        }
    )


_OBJECT_CLASSES: tuple[type, ...] = (
    Entity,
    Claim,
    Evidence,
    Assumption,
    Inference,
    Hypothesis,
    Question,
    Contradiction,
)


def _apply_update(
    containers: dict[str, dict[str, Any]],
    relations: list[Relation],
    upd: UpdateObject,
) -> None:
    for container in containers.values():
        if upd.object_id in container:
            current = container[upd.object_id]
            container[upd.object_id] = current.model_copy(update={upd.field: upd.to_value})
            return
    for i, rel in enumerate(relations):
        if rel.id == upd.object_id:
            relations[i] = rel.model_copy(update={upd.field: upd.to_value})
            return
    raise CommitError(
        f"update_objects target {upd.object_id!r} not found at commit time; "
        f"L2 should have rejected this patch."
    )


def _apply_archive(
    containers: dict[str, dict[str, Any]],
    relations: list[Relation],
    arc: ArchiveObject,
) -> None:
    for container in containers.values():
        if arc.object_id in container:
            current = container[arc.object_id]
            container[arc.object_id] = current.model_copy(
                update={"status": ObjectStatus.ARCHIVED}
            )
            return
    for i, rel in enumerate(relations):
        if rel.id == arc.object_id:
            relations[i] = rel.model_copy(update={"status": ObjectStatus.ARCHIVED})
            return
    raise CommitError(
        f"archive_objects target {arc.object_id!r} not found at commit time."
    )


__all__ = ["CommitError", "commit_patch"]
