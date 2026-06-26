"""Export JSON Schemas for the top-level models.

Usage::

    python -m spc_state.models.schema_export schemas/

Writes one `<model>.schema.json` per top-level model. The runtime does not
depend on the on-disk schemas; they are produced from the Pydantic models
as a side artifact for documentation, downstream tools, and contracts with
LLM providers (Phase 7).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from .patch import SemanticPatch
from .projection import Projection
from .receipt import ReasoningReceipt
from .state import SemanticState
from .transform import TransformRecord
from .validation import ValidationReport

EXPORTED_MODELS: dict[str, type[BaseModel]] = {
    "semantic_state": SemanticState,
    "semantic_patch": SemanticPatch,
    "transform_record": TransformRecord,
    "validation_report": ValidationReport,
    "projection": Projection,
    "reasoning_receipt": ReasoningReceipt,
}


def build_schemas() -> dict[str, dict[str, Any]]:
    """Return `{filename_stem: schema_dict}` for every exported model."""
    return {name: model.model_json_schema() for name, model in EXPORTED_MODELS.items()}


def write_schemas(target_dir: Path) -> list[Path]:
    """Write every exported schema into `target_dir/<name>.schema.json`."""
    target_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for name, schema in build_schemas().items():
        path = target_dir / f"{name}.schema.json"
        path.write_text(json.dumps(schema, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        written.append(path)
    return written


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        print("usage: python -m spc_state.models.schema_export <target_dir>", file=sys.stderr)
        return 2
    target = Path(args[0])
    written = write_schemas(target)
    for p in written:
        print(p)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
