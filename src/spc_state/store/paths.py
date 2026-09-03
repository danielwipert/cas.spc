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

    @property
    def baseline_dir(self) -> Path:
        return self.run_dir / "baseline"

    @property
    def report_dir(self) -> Path:
        return self.run_dir / "report"

    def state_file(self, state_version: int) -> Path:
        return self.state_dir / f"semantic_state_v{state_version:03d}.json"

    def patch_file(self, ordinal: int) -> Path:
        return self.patches_dir / f"patch_{ordinal:03d}.json"

    def validation_file(self, ordinal: int) -> Path:
        return self.validation_dir / f"validation_{ordinal:03d}.json"

    # -- per-attempt artifacts (the LLM retry trail) ----------------------
    # An LLM step may take several attempts before the runtime commits or
    # gives up. The canonical `patch_*.json` / `validation_*.json` files hold
    # the final outcome; these hold every attempt that led there. The
    # `attempt_` prefix keeps them out of the `patch_*` / `validation_*` globs
    # the §20.8 artifact counts use.

    def patch_attempt_file(self, ordinal: int, attempt: int) -> Path:
        """The model's raw completion for one attempt, kept verbatim."""
        return self.patches_dir / f"attempt_{ordinal:03d}_{attempt:02d}.txt"

    def validation_attempt_file(self, ordinal: int, attempt: int) -> Path:
        """The validation report for one attempt."""
        return self.validation_dir / f"attempt_{ordinal:03d}_{attempt:02d}.json"

    def receipt_file(self, state_version: int) -> Path:
        return self.receipts_dir / f"reasoning_receipt_v{state_version:03d}.md"

    def audit_log(self) -> Path:
        return self.audit_dir / "audit_log.jsonl"

    def diff_file(self, version_a: int, version_b: int) -> Path:
        return self.diffs_dir / f"diff_v{version_a:03d}_v{version_b:03d}.json"

    def baseline_file(self, name: str) -> Path:
        return self.baseline_dir / name

    def report_file(self, name: str = "pilot_report.md") -> Path:
        return self.report_dir / name

    def cost_ledger_file(self) -> Path:
        return self.run_dir / "cost_ledger.json"

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
