"""SQLite-backed `StateStore` (T6) — proves the storage seam is real.

`AGENTS.md §V` sets file-based storage as the v0.1 norm and says the
`runs/` tree "is generated and gitignored." This is a deliberate, sanctioned
relaxation of that constraint for exactly one artifact type — versioned
`SemanticState` snapshots — behind the *same* `StateStoreProtocol` the
file-based `StateStore` already implements. Nothing else about the runtime
changes: patches, validation reports, the audit log, diffs, and receipts
stay file-based. `Runtime` never imports this module; a caller who wants a
SQLite-backed run constructs one and hands it to `Runtime(state_store=...)`.

The row payload is the exact same `model_dump_json(by_alias=True)` text the
file backend writes to `semantic_state_v<N>.json` — only where it lives
changes, not what it says. One `.sqlite3` file per run
(`RunPaths.state_db_file`), never shared across runs, so the file store's
per-run isolation carries over unchanged.
"""

from __future__ import annotations

import sqlite3

from ..models import SemanticState
from .paths import RunPaths


class StateVersionNotFoundError(KeyError):
    """No row exists for the requested `state_version` (T6)."""


class SQLiteStateStore:
    """Versioned `SemanticState` snapshots in a per-run SQLite file.

    Same constructor shape and the same three methods as the file-based
    `StateStore` (`write`, `read`, `latest_version`) — `StateStoreProtocol`
    is structural, so this satisfies it with no shared base class.
    """

    def __init__(self, paths: RunPaths) -> None:
        self.paths = paths
        db_path = paths.state_db_file()
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(db_path)
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS state_versions ("
            "state_version INTEGER PRIMARY KEY, payload TEXT NOT NULL)"
        )
        self._conn.commit()

    def write(self, state: SemanticState) -> None:
        payload = state.model_dump_json(by_alias=True)
        self._conn.execute(
            "INSERT OR REPLACE INTO state_versions (state_version, payload) VALUES (?, ?)",
            (state.state_version, payload),
        )
        self._conn.commit()

    def read(self, state_version: int) -> SemanticState:
        row = self._conn.execute(
            "SELECT payload FROM state_versions WHERE state_version = ?",
            (state_version,),
        ).fetchone()
        if row is None:
            raise StateVersionNotFoundError(
                f"No state v{state_version} in {self.paths.state_db_file()}"
            )
        return SemanticState.model_validate_json(row[0])

    def latest_version(self) -> int | None:
        row = self._conn.execute("SELECT MAX(state_version) FROM state_versions").fetchone()
        return row[0] if row is not None and row[0] is not None else None

    def close(self) -> None:
        """Release the SQLite connection. Not required before the process
        exits, but tests that read back a just-closed run's db, or that spin
        up many stores in one session, should call it."""
        self._conn.close()


__all__ = ["SQLiteStateStore", "StateVersionNotFoundError"]
