"""T6 — SQLite-backed `StateStore` behind the same interface (TASKS.md).

`StateStoreProtocol` (`store/store.py`) is what `Runtime` actually depends
on — not the file-based `StateStore` directly. These tests run the same
generic behavioral suite against both implementations via parametrization,
then run the full deterministic demo pipeline once per backend and assert
the committed state history comes out identical: the storage medium changed,
nothing about what got committed did.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest

from spc_state.runtime import bootstrap_state
from spc_state.store import RunPaths, StateStore, StateStoreProtocol
from spc_state.store.sqlite_store import SQLiteStateStore, StateVersionNotFoundError
from tests._demo_helpers import run_demo

UTC = dt.UTC


@pytest.fixture(params=[StateStore, SQLiteStateStore], ids=["file", "sqlite"])
def backend(request) -> type[StateStoreProtocol]:
    """Both backends share the same constructor shape: `Backend(paths)`."""
    return request.param


def _state(version: int = 0, *, now: dt.datetime | None = None):
    now = now or dt.datetime(2026, 1, 1, tzinfo=UTC)
    return bootstrap_state(
        state_id="sr_001", project_id="p", name="n", now=now
    ).model_copy(update={"state_version": version})


# ---------------------------------------------------------------------------
# The generic behavioral contract — same assertions, either backend.
# ---------------------------------------------------------------------------


def test_latest_version_is_none_before_any_write(tmp_path: Path, backend) -> None:
    paths = RunPaths(root=tmp_path / "runs", run_id="empty")
    store = backend(paths)
    assert store.latest_version() is None


def test_write_then_read_round_trips_the_exact_state(tmp_path: Path, backend) -> None:
    paths = RunPaths(root=tmp_path / "runs", run_id="roundtrip")
    store = backend(paths)
    state = _state(0)

    store.write(state)

    assert store.read(0) == state


def test_latest_version_tracks_the_highest_written_version(tmp_path: Path, backend) -> None:
    paths = RunPaths(root=tmp_path / "runs", run_id="latest")
    store = backend(paths)

    store.write(_state(0))
    store.write(_state(2))  # out of order on purpose
    store.write(_state(1))

    assert store.latest_version() == 2
    assert store.read(0).state_version == 0
    assert store.read(1).state_version == 1
    assert store.read(2).state_version == 2


def test_writing_the_same_version_twice_overwrites_it(tmp_path: Path, backend) -> None:
    paths = RunPaths(root=tmp_path / "runs", run_id="overwrite")
    store = backend(paths)

    store.write(_state(0))
    updated = _state(0).model_copy(update={"name": "revised"})
    store.write(updated)

    assert store.read(0).name == "revised"
    assert store.latest_version() == 0  # not two versions, one overwritten


def test_reading_a_missing_version_raises(tmp_path: Path, backend) -> None:
    paths = RunPaths(root=tmp_path / "runs", run_id="missing")
    store = backend(paths)
    store.write(_state(0))

    with pytest.raises((FileNotFoundError, StateVersionNotFoundError)):
        store.read(7)


def test_sqlite_store_close_releases_the_connection(tmp_path: Path) -> None:
    paths = RunPaths(root=tmp_path / "runs", run_id="close")
    store = SQLiteStateStore(paths)
    store.write(_state(0))
    store.close()

    # The file survives closing; a fresh store can still read it back.
    reopened = SQLiteStateStore(paths)
    assert reopened.read(0).state_version == 0
    reopened.close()


def test_two_runs_do_not_share_state(tmp_path: Path, backend) -> None:
    """Per-run isolation — a SQLite backend must not leak across run ids,
    the way two file-based runs never share a `state/` directory."""
    root = tmp_path / "runs"
    store_a = backend(RunPaths(root=root, run_id="run_a"))
    store_b = backend(RunPaths(root=root, run_id="run_b"))

    store_a.write(_state(0))

    assert store_a.latest_version() == 0
    assert store_b.latest_version() is None


# ---------------------------------------------------------------------------
# The acceptance scenario: a full deterministic demo run, same result either way.
# ---------------------------------------------------------------------------


def test_full_demo_run_on_sqlite_matches_the_file_run(tmp_path: Path) -> None:
    file_paths, file_states = run_demo(tmp_path / "runs", run_id="file_run")
    sqlite_paths, sqlite_states = run_demo(
        tmp_path / "runs", run_id="sqlite_run", state_store_factory=SQLiteStateStore
    )

    assert [s.state_version for s in sqlite_states] == [s.state_version for s in file_states]
    assert sqlite_states == file_states  # every committed object, byte-for-byte equal

    # The storage medium actually differs — this isn't accidentally the same backend.
    assert sqlite_paths.state_db_file().exists()
    assert not sqlite_paths.state_dir.exists()
    assert file_paths.state_dir.exists()
    assert not file_paths.state_db_file().exists()

    # Everything that ISN'T the state store stayed file-based for both runs
    # (T6 invariant: only the state-store implementation changes).
    assert len(list(sqlite_paths.patches_dir.glob("patch_*.json"))) == 3
    assert len(list(file_paths.patches_dir.glob("patch_*.json"))) == 3
