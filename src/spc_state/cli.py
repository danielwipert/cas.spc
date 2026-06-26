"""Command-line interface for the SPC pilot demo.

Phase 1 ships the entrypoint and `--help` only. The `run` subcommand is
wired up in Phase 3 once the runtime, store, and operators land.
"""

from __future__ import annotations

import typer

from . import __version__

app = typer.Typer(
    name="spc-demo",
    help="SPC Shared Semantic State Engine — pilot demo runner.",
    add_completion=False,
    no_args_is_help=True,
)


@app.command()
def version() -> None:
    """Print the engine version."""
    typer.echo(f"spc-state {__version__}")


@app.command()
def run(
    input: str = typer.Option(..., "--input", "-i", help="Path to input document."),
    run_id: str = typer.Option("demo_001", "--run-id", help="Identifier for this run."),
) -> None:
    """Run the deterministic demo pipeline (implemented in Phase 3)."""
    typer.secho(
        f"`spc-demo run` is not implemented yet. Phase 3 will wire the "
        f"runtime that turns '{input}' into runs/{run_id}/.",
        fg=typer.colors.YELLOW,
        err=True,
    )
    raise typer.Exit(code=2)


if __name__ == "__main__":  # pragma: no cover
    app()
