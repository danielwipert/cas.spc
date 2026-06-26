"""Append-only JSONL audit log for one run.

See PILOT_SPEC.md §15.1 step 9. Every runtime decision (operator started,
patch validated, router decision, state committed/rejected) appends one
line. The audit log is the human-debuggable record of what the runtime did.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any


class AuditLog:
    """Append a JSON event per line to `runs/<id>/audit/audit_log.jsonl`."""

    def __init__(self, path: Path) -> None:
        self._path = path
        path.parent.mkdir(parents=True, exist_ok=True)

    @property
    def path(self) -> Path:
        return self._path

    def append(
        self,
        event_type: str,
        *,
        at: dt.datetime,
        **fields: Any,
    ) -> None:
        record: dict[str, Any] = {
            "at": at.isoformat(),
            "event": event_type,
            **fields,
        }
        with self._path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, sort_keys=True) + "\n")

    def read(self) -> list[dict[str, Any]]:
        if not self._path.exists():
            return []
        out: list[dict[str, Any]] = []
        for line in self._path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            out.append(json.loads(line))
        return out


__all__ = ["AuditLog"]
