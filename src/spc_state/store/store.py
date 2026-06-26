"""File-based state store for SemanticState, SemanticPatch, ValidationReport.

See PILOT_SPEC.md §17. The store is intentionally dumb: write JSON, read
JSON, that's it. No locking, no atomic temp-rename, no compression. Pilot
scope.

Every write goes through Pydantic's `model_dump_json(by_alias=True)` so the
on-disk shape matches the spec (including the `from`/`to` aliases inside
patches).
"""

from __future__ import annotations

from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel

from ..models import SemanticPatch, SemanticState, ValidationReport
from .paths import RunPaths

M = TypeVar("M", bound=BaseModel)


def _write_model(path: Path, model: BaseModel) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = model.model_dump_json(by_alias=True, indent=2)
    path.write_text(payload + "\n", encoding="utf-8")
    return path


def _read_model(path: Path, model_cls: type[M]) -> M:
    return model_cls.model_validate_json(path.read_text(encoding="utf-8"))


class StateStore:
    """Reads and writes versioned SemanticState snapshots for one run."""

    def __init__(self, paths: RunPaths) -> None:
        self.paths = paths

    def write(self, state: SemanticState) -> Path:
        return _write_model(self.paths.state_file(state.state_version), state)

    def read(self, state_version: int) -> SemanticState:
        return _read_model(self.paths.state_file(state_version), SemanticState)

    def latest_version(self) -> int | None:
        if not self.paths.state_dir.exists():
            return None
        versions: list[int] = []
        for p in self.paths.state_dir.glob("semantic_state_v*.json"):
            try:
                versions.append(int(p.stem.removeprefix("semantic_state_v")))
            except ValueError:  # pragma: no cover - defensive
                continue
        return max(versions) if versions else None


class PatchStore:
    """Reads and writes SemanticPatch artifacts for one run."""

    def __init__(self, paths: RunPaths) -> None:
        self.paths = paths

    def write(self, patch: SemanticPatch, ordinal: int) -> Path:
        return _write_model(self.paths.patch_file(ordinal), patch)

    def read(self, ordinal: int) -> SemanticPatch:
        return _read_model(self.paths.patch_file(ordinal), SemanticPatch)


class ValidationStore:
    """Reads and writes ValidationReport artifacts for one run."""

    def __init__(self, paths: RunPaths) -> None:
        self.paths = paths

    def write(self, report: ValidationReport, ordinal: int) -> Path:
        return _write_model(self.paths.validation_file(ordinal), report)

    def read(self, ordinal: int) -> ValidationReport:
        return _read_model(self.paths.validation_file(ordinal), ValidationReport)


__all__ = ["PatchStore", "StateStore", "ValidationStore"]
