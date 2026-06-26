"""Canonical filesystem layout for a single demo run.

See PILOT_SPEC.md §17.1. One `runs/<run_id>/` tree per run; the tree is
fully reproducible from `examples/` + the engine and is gitignored.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class RunPaths:
    """All on-disk paths for a single run, derived from a root + run_id."""

    root: Path
    run_id: str

    @property
    def run_dir(self) -> Path:
        return self.root / self.run_id

    @property
    def input_dir(self) -> Path:
        return self.run_dir / "input"

    @property
    def state_dir(self) -> Path:
        return self.run_dir / "state"

    @property
    def patches_dir(self) -> Path:
        return self.run_dir / "patches"

    @property
    def validation_dir(self) -> Path:
        return self.run_dir / "validation"

    @property
    def receipts_dir(self) -> Path:
        return self.run_dir / "receipts"

    @property
    def audit_dir(self) -> Path:
        return self.run_dir / "audit"

    @property
    def diffs_dir(self) -> Path:
        return self.run_dir / "diffs"

    def state_file(self, state_version: int) -> Path:
        return self.state_dir / f"semantic_state_v{state_version:03d}.json"

    def patch_file(self, ordinal: int) -> Path:
        return self.patches_dir / f"patch_{ordinal:03d}.json"

    def validation_file(self, ordinal: int) -> Path:
        return self.validation_dir / f"validation_{ordinal:03d}.json"

    def receipt_file(self, state_version: int) -> Path:
        return self.receipts_dir / f"reasoning_receipt_v{state_version:03d}.md"

    def audit_log(self) -> Path:
        return self.audit_dir / "audit_log.jsonl"

    def diff_file(self, version_a: int, version_b: int) -> Path:
        return self.diffs_dir / f"diff_v{version_a:03d}_v{version_b:03d}.json"

    def input_copy(self) -> Path:
        return self.input_dir / "input.txt"

    def ensure_dirs(self) -> None:
        for d in (
            self.input_dir,
            self.state_dir,
            self.patches_dir,
            self.validation_dir,
            self.receipts_dir,
            self.audit_dir,
            self.diffs_dir,
        ):
            d.mkdir(parents=True, exist_ok=True)


__all__ = ["RunPaths"]
