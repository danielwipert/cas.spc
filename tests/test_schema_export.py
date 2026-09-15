"""Phase 2 — JSON Schema export works for every top-level model."""

from __future__ import annotations

import json
from pathlib import Path

from spc_state.models.schema_export import EXPORTED_MODELS, build_schemas, write_schemas


def test_every_exported_model_has_a_schema() -> None:
    schemas = build_schemas()
    assert set(schemas) == set(EXPORTED_MODELS)
    for _name, schema in schemas.items():
        # Each schema is a non-empty dict and is JSON-serialisable.
        assert isinstance(schema, dict) and schema
        json.dumps(schema)


def test_semantic_state_schema_marks_required_fields() -> None:
    schemas = build_schemas()
    state_schema = schemas["semantic_state"]
    required = set(state_schema.get("required", []))
    # `state_version` must be required — it's the version anchor for patches.
    assert "state_version" in required
    assert "state_id" in required
    assert "project_id" in required


def test_write_schemas_creates_one_file_per_model(tmp_path: Path) -> None:
    written = write_schemas(tmp_path)
    names = {p.stem for p in written}
    assert names == {f"{n}.schema" for n in EXPORTED_MODELS}
    for path in written:
        assert path.exists()
        # Each written file is well-formed JSON.
        json.loads(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# T24 — the committed schemas must match the models that generate them
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent.parent
COMMITTED_SCHEMAS = REPO_ROOT / "schemas"
REGENERATE = "python -m spc_state.models.schema_export schemas"


def _committed(name: str) -> Path:
    return COMMITTED_SCHEMAS / f"{name}.schema.json"


def test_no_exported_model_is_missing_a_committed_schema() -> None:
    missing = sorted(n for n in EXPORTED_MODELS if not _committed(n).exists())
    assert not missing, f"no committed schema for {missing}. Run: {REGENERATE}"


def test_no_committed_schema_outlives_its_model() -> None:
    """A model that goes away must not leave its schema behind.

    T20 removed two `EpistemicStatus` members; a whole model could go the same
    way, and a stale file would keep documenting something that no longer exists.
    """
    on_disk = {p.name.removesuffix(".schema.json") for p in COMMITTED_SCHEMAS.glob("*.schema.json")}
    orphaned = sorted(on_disk - set(EXPORTED_MODELS))
    assert not orphaned, f"{orphaned} no longer exported. Run: {REGENERATE}"


def test_the_committed_schemas_match_the_models(tmp_path: Path) -> None:
    """The gap that let `schemas/` drift for fifteen tasks.

    `schemas/` is a committed artifact generated from the models, and until now
    nothing compared the two. T20 regenerated them and the diff picked up a
    `TokenUsage` block missing since **T5** — ten tasks of schema changes had
    landed without anyone noticing, because the only tests wrote to a temp
    directory and checked the output was well-formed JSON.

    Compared as **exact text**, not as parsed JSON: the committed file is the
    artifact, so a hand-edit or a change to the writer's own formatting is drift
    too. `write_schemas` is the single source of the expected bytes, so this can
    never disagree with it about indentation or key order.
    """
    fresh = {p.name: p.read_text(encoding="utf-8") for p in write_schemas(tmp_path)}

    stale = []
    for name in sorted(EXPORTED_MODELS):
        path = _committed(name)
        if not path.exists():
            continue  # reported by its own test, with its own message
        if path.read_text(encoding="utf-8") != fresh[path.name]:
            stale.append(name)

    assert not stale, (
        f"schemas/ is out of date for {stale} — the models changed and the "
        f"committed artifact did not. Run: {REGENERATE}"
    )
