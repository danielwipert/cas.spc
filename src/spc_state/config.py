"""Minimal `.env` loading — no third-party dependency.

The pilot keeps its dependency surface small (see `AGENTS.md §VIII`), so rather
than pull in `python-dotenv` we parse a `.env` ourselves. The CLI calls
`load_dotenv()` once at startup so a key dropped in `.env` (e.g.
`OPENROUTER_API_KEY`) is picked up by the live operators without the user
having to export it into the shell.

Rules, deliberately forgiving of hand-edited files:
- blank lines and `#` comments are ignored;
- an optional leading `export ` is stripped;
- `KEY = value` with spaces around `=` is fine (both sides are trimmed);
- a value wrapped in matching single or double quotes is unquoted.

Real environment variables win: a key already present in `os.environ` is never
overwritten unless `override=True`.
"""

from __future__ import annotations

import os
from pathlib import Path

__all__ = ["find_dotenv", "load_dotenv", "parse_dotenv"]


def parse_dotenv(text: str) -> dict[str, str]:
    """Parse `.env` text into a mapping, applying the forgiving rules above."""
    out: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :]
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        if key:
            out[key] = value
    return out


def find_dotenv(start: Path | None = None, *, max_levels: int = 4) -> Path | None:
    """Search `start` (default cwd) and a few parent directories for a `.env`."""
    here = (start or Path.cwd()).resolve()
    for directory in [here, *here.parents][: max_levels + 1]:
        candidate = directory / ".env"
        if candidate.is_file():
            return candidate
    return None


def load_dotenv(
    path: Path | None = None, *, override: bool = False
) -> list[str]:
    """Load a `.env` into `os.environ`; return the names of keys that were set.

    Returns key **names** only — never values — so callers can log what loaded
    without leaking secrets. A missing file is a no-op (returns `[]`).
    """
    env_path = path or find_dotenv()
    if env_path is None or not env_path.is_file():
        return []
    parsed = parse_dotenv(env_path.read_text(encoding="utf-8"))
    set_keys: list[str] = []
    for key, value in parsed.items():
        if override or key not in os.environ:
            os.environ[key] = value
            set_keys.append(key)
    return set_keys
