"""Phase 2 — JSON Schema export works for every top-level model."""

from __future__ import annotations

import json
from pathlib import Path

from spc_state.models.schema_export import EXPORTED_MODELS, build_schemas, write_schemas


def test_every_exported_model_has_a_schema() -> None:
    schemas = build_schemas()
    assert set(schemas) == set(EXPORTED_MODELS)
    for name, schema in schemas.items():
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
