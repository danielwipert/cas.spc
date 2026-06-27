"""Tests for the minimal `.env` loader (`spc_state.config`)."""

from __future__ import annotations

import os
from pathlib import Path

from spc_state.config import find_dotenv, load_dotenv, parse_dotenv


def test_parse_handles_spaces_quotes_comments_and_export() -> None:
    text = "\n".join(
        [
            "# a comment",
            "",
            "OPENROUTER_API_KEY = sk-or-abc123",  # spaces around =
            'SPC_OPENROUTER_MODEL="deepseek/deepseek-chat"',
            "export FOO = 'bar baz'",
            "NOEQUALS",
        ]
    )
    parsed = parse_dotenv(text)
    assert parsed["OPENROUTER_API_KEY"] == "sk-or-abc123"
    assert parsed["SPC_OPENROUTER_MODEL"] == "deepseek/deepseek-chat"
    assert parsed["FOO"] == "bar baz"
    assert "NOEQUALS" not in parsed


def test_load_sets_missing_keys_and_returns_names(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text("SPC_TEST_TOKEN = xyz\n", encoding="utf-8")
    os.environ.pop("SPC_TEST_TOKEN", None)
    try:
        names = load_dotenv(env)
        assert names == ["SPC_TEST_TOKEN"]
        assert os.environ["SPC_TEST_TOKEN"] == "xyz"
    finally:
        os.environ.pop("SPC_TEST_TOKEN", None)


def test_existing_env_var_wins_unless_override(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text("SPC_TEST_TOKEN=fromfile\n", encoding="utf-8")
    os.environ["SPC_TEST_TOKEN"] = "fromenv"
    try:
        assert load_dotenv(env) == []  # not overwritten
        assert os.environ["SPC_TEST_TOKEN"] == "fromenv"
        assert load_dotenv(env, override=True) == ["SPC_TEST_TOKEN"]
        assert os.environ["SPC_TEST_TOKEN"] == "fromfile"
    finally:
        os.environ.pop("SPC_TEST_TOKEN", None)


def test_missing_file_is_noop(tmp_path: Path) -> None:
    assert load_dotenv(tmp_path / "nope.env") == []


def test_find_dotenv_searches_parents(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("X=1\n", encoding="utf-8")
    nested = tmp_path / "a" / "b"
    nested.mkdir(parents=True)
    found = find_dotenv(nested)
    assert found == (tmp_path / ".env").resolve()
