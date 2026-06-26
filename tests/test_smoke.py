"""Phase 1 smoke tests. Replaced/augmented by real tests in later phases."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import spc_state


def test_package_imports() -> None:
    """The package imports and exposes a version string."""
    assert isinstance(spc_state.__version__, str)
    assert spc_state.__version__


def test_subpackages_importable() -> None:
    """Every declared subpackage imports without error.

    The Phase 1 skeleton is empty; this test guards against accidentally
    deleting a subpackage or breaking an `__init__.py` in later phases.
    """
    import importlib

    for name in (
        "spc_state.models",
        "spc_state.store",
        "spc_state.validation",
        "spc_state.router",
        "spc_state.runtime",
        "spc_state.operators",
        "spc_state.projection",
        "spc_state.diff",
        "spc_state.receipt",
        "spc_state.audit",
        "spc_state.providers",
        "spc_state.cli",
    ):
        importlib.import_module(name)


def test_cli_help_runs() -> None:
    """`python -m spc_state.cli --help` exits 0 and mentions the demo runner."""
    result = subprocess.run(
        [sys.executable, "-m", "spc_state.cli", "--help"],
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr
    assert "spc-demo" in result.stdout.lower() or "semantic" in result.stdout.lower()


def test_example_input_present() -> None:
    """The demo input from PILOT_SPEC §8.1 ships in `examples/`."""
    here = Path(__file__).resolve().parent
    example = here.parent / "examples" / "ai_coding_assistant.txt"
    assert example.exists(), f"missing demo input: {example}"
    text = example.read_text(encoding="utf-8")
    assert "AI coding assistant" in text
    assert "security" in text.lower()
