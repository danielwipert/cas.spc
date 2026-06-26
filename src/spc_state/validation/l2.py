"""L2 — referential and provenance validation. See PILOT_SPEC.md §16.2.

L2 runs against a `(base_state, patch)` pair after L1 succeeds. It checks
that the patch is *coherent* with the base state:

- The patch's `base_state_id` / `base_state_version` match the base state.
- Every ID referenced by `read_set`, `update_objects`, `archive_objects`,
  `add_relations` (source/target), and the `transform_record` exists in the
  base state.
- New object IDs (anywhere in `add_objects` or `add_relations`) do not
  collide with existing IDs.
- For every `UpdateObject`, the target object exists in the base state.
- The `transform_record.input_state_version` matches `patch.base_state_version`.
- New high-confidence claims either cite evidence or carry an explicit
  speculative/assumed `epistemic_status`.

L2 returns a list of `ValidationIssue` records. The runtime uses these to
decide REJECT vs. REVIEW vs. COMMIT via the router.
"""

from __future__ import annotations

from ..models import (
    EpistemicStatus,
    SemanticPatch,
    SemanticState,
    ValidationIssue,
    ValidationLayer,
    ValidationSeverity,
)


def _err(code: str, message: str, *, object_id: str | None = None, field: str | None = None) -> ValidationIssue:
    return ValidationIssue(
        layer=ValidationLayer.L2_REFERENTIAL,
        severity=ValidationSeverity.ERROR,
        code=code,
        message=message,
        object_id=object_id,
        field=field,
    )


def _warn(code: str, message: str, *, object_id: str | None = None) -> ValidationIssue:
    return ValidationIssue(
        layer=ValidationLayer.L2_REFERENTIAL,
        severity=ValidationSeverity.WARNING,
        code=code,
        message=message,
        object_id=object_id,
    )


_PROVENANCE_FREE_STATUSES = {EpistemicStatus.ASSUMED, EpistemicStatus.SPECULATIVE}


def validate_patch(state: SemanticState, patch: SemanticPatch) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []

    # --- base state alignment --------------------------------------------
    if patch.base_state_id != state.state_id:
        issues.append(
            _err(
                "L2.BASE_STATE_ID_MISMATCH",
                f"Patch base_state_id={patch.base_state_id!r} does not match "
                f"current state_id={state.state_id!r}.",
                field="base_state_id",
            )
        )
    if patch.base_state_version != state.state_version:
        issues.append(
            _err(
                "L2.BASE_STATE_VERSION_MISMATCH",
                f"Patch base_state_version={patch.base_state_version} does not "
                f"match current state_version={state.state_version}.",
                field="base_state_version",
            )
        )
    if patch.transform_record.input_state_version != patch.base_state_version:
        issues.append(
            _err(
                "L2.TRANSFORM_INPUT_VERSION_MISMATCH",
                f"transform_record.input_state_version="
                f"{patch.transform_record.input_state_version} does not match "
                f"patch.base_state_version={patch.base_state_version}.",
                field="transform_record.input_state_version",
            )
        )

    existing_ids = state.all_object_ids()

    # --- read-set refs must exist ----------------------------------------
    for ref_id in patch.read_set:
        if ref_id not in existing_ids:
            issues.append(
                _err(
                    "L2.UNRESOLVED_READ_SET_REF",
                    f"read_set references unknown object {ref_id!r}.",
                    object_id=ref_id,
                    field="read_set",
                )
            )
    for ref_id in patch.transform_record.read_set:
        if ref_id not in existing_ids:
            issues.append(
                _err(
                    "L2.UNRESOLVED_TRANSFORM_READ_REF",
                    f"transform_record.read_set references unknown object {ref_id!r}.",
                    object_id=ref_id,
                    field="transform_record.read_set",
                )
            )

    # --- new IDs must not collide ----------------------------------------
    new_ids = _collect_added_ids(patch)
    for new_id in new_ids:
        if new_id in existing_ids:
            issues.append(
                _err(
                    "L2.DUPLICATE_OBJECT_ID",
                    f"add_objects/add_relations introduces id {new_id!r} which "
                    f"already exists in state.",
                    object_id=new_id,
                )
            )
    if len(new_ids) != len(set(new_ids)):
        # Duplicate within the patch itself
        seen: set[str] = set()
        for nid in new_ids:
            if nid in seen:
                issues.append(
                    _err(
                        "L2.DUPLICATE_NEW_ID_IN_PATCH",
                        f"id {nid!r} appears more than once inside this patch.",
                        object_id=nid,
                    )
                )
            seen.add(nid)

    # --- update_objects must target an existing id -----------------------
    for upd in patch.update_objects:
        if upd.object_id not in existing_ids:
            issues.append(
                _err(
                    "L2.UNRESOLVED_UPDATE_TARGET",
                    f"update_objects refers to unknown object {upd.object_id!r}.",
                    object_id=upd.object_id,
                    field="update_objects",
                )
            )

    # --- archive_objects must target an existing id ----------------------
    for arc in patch.archive_objects:
        if arc.object_id not in existing_ids:
            issues.append(
                _err(
                    "L2.UNRESOLVED_ARCHIVE_TARGET",
                    f"archive_objects refers to unknown object {arc.object_id!r}.",
                    object_id=arc.object_id,
                    field="archive_objects",
                )
            )

    # --- add_relations must resolve to existing or freshly-added IDs -----
    resolvable = existing_ids | set(new_ids)
    for rel in patch.add_relations:
        if rel.source not in resolvable:
            issues.append(
                _err(
                    "L2.RELATION_SOURCE_UNRESOLVED",
                    f"Relation {rel.id!r} source {rel.source!r} does not resolve.",
                    object_id=rel.id,
                    field="add_relations.source",
                )
            )
        if rel.target not in resolvable:
            issues.append(
                _err(
                    "L2.RELATION_TARGET_UNRESOLVED",
                    f"Relation {rel.id!r} target {rel.target!r} does not resolve.",
                    object_id=rel.id,
                    field="add_relations.target",
                )
            )

    # --- provenance for new high-confidence claims -----------------------
    for claim in patch.add_objects.claims:
        if claim.epistemic_status in _PROVENANCE_FREE_STATUSES:
            continue
        has_evidence = bool(claim.supporting_evidence)
        has_assumption = bool(claim.assumptions)
        if not (has_evidence or has_assumption):
            severity = ValidationSeverity.ERROR if claim.confidence >= 0.6 else ValidationSeverity.WARNING
            issues.append(
                ValidationIssue(
                    layer=ValidationLayer.L2_REFERENTIAL,
                    severity=severity,
                    code="L2.CLAIM_MISSING_PROVENANCE",
                    message=(
                        f"Claim {claim.id!r} (confidence={claim.confidence}) lacks "
                        f"supporting_evidence and assumptions, but its "
                        f"epistemic_status is {claim.epistemic_status.value!r}, "
                        f"not 'assumed' or 'speculative'."
                    ),
                    object_id=claim.id,
                    field="supporting_evidence",
                )
            )

    # --- write_set must include every id the patch actually writes -------
    declared_writes = set(patch.transform_record.write_set)
    actual_writes: set[str] = set(new_ids)
    actual_writes.update(u.object_id for u in patch.update_objects)
    actual_writes.update(a.object_id for a in patch.archive_objects)
    undeclared = actual_writes - declared_writes
    for w in sorted(undeclared):
        issues.append(
            _warn(
                "L2.UNDECLARED_WRITE",
                f"Patch writes {w!r} but transform_record.write_set does not include it.",
                object_id=w,
            )
        )

    return issues


def _collect_added_ids(patch: SemanticPatch) -> list[str]:
    out: list[str] = []
    out.extend(o.id for o in patch.add_objects.entities)
    out.extend(o.id for o in patch.add_objects.claims)
    out.extend(o.id for o in patch.add_objects.evidence)
    out.extend(o.id for o in patch.add_objects.assumptions)
    out.extend(o.id for o in patch.add_objects.inferences)
    out.extend(o.id for o in patch.add_objects.hypotheses)
    out.extend(o.id for o in patch.add_objects.questions)
    out.extend(o.id for o in patch.add_objects.contradictions)
    out.extend(r.id for r in patch.add_relations)
    return out


__all__ = ["validate_patch"]
