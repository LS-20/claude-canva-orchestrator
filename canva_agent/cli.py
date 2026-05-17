"""Typer CLI and conversational REPL."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.json import JSON
from rich.panel import Panel
from rich.prompt import Prompt
from rich.table import Table

from canva_agent.config import (
    DEFAULT_ANALYSIS_MODEL,
    DEFAULT_BUILD_MODEL,
    PROJECT_ROOT,
    ensure_env,
    format_cost_estimate,
    load_env,
    resolve_model,
)
from canva_agent.phase1_analyze import analyze_image, revise_spec, spec_from_json, spec_to_json
from canva_agent.phase2_build import build_design
from canva_agent.schemas import DesignSpec

app = typer.Typer(
    name="canva-agent",
    help="Two-phase design agent: analyze reference images, then build in Canva.",
    no_args_is_help=False,
)
console = Console()
SAVED_SPECS_DIR = PROJECT_ROOT / "saved_specs"
SESSIONS_DIR = PROJECT_ROOT / "sessions"


def _slug(text: str, max_len: int = 40) -> str:
    slug = "".join(c if c.isalnum() else "-" for c in text.lower()).strip("-")
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug[:max_len] or "spec"


def _display_spec(spec: DesignSpec) -> None:
    table = Table(title="Design Spec Summary", show_header=True)
    table.add_column("Field", style="cyan")
    table.add_column("Value")
    table.add_row("Type", spec.design_type)
    table.add_row("Dimensions", spec.dimensions_estimate)
    table.add_row("Mood", spec.mood)
    table.add_row("Colors", str(len(spec.color_palette)))
    table.add_row("Typography", str(len(spec.typography)))
    table.add_row("Components", str(len(spec.components)))
    table.add_row("Stock queries", str(len(spec.stock_asset_queries)))
    console.print(table)
    console.print(JSON(spec_to_json(spec)))


def _save_spec(spec: DesignSpec) -> Path:
    SAVED_SPECS_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = SAVED_SPECS_DIR / f"{ts}-{_slug(spec.design_type)}.json"
    path.write_text(spec_to_json(spec), encoding="utf-8")
    return path


def _load_memory_context() -> str:
    if not SAVED_SPECS_DIR.exists():
        return ""
    summaries: list[str] = []
    for path in sorted(SAVED_SPECS_DIR.glob("*.json"))[-5:]:
        try:
            spec = spec_from_json(path.read_text(encoding="utf-8"))
            summaries.append(
                f"- {path.name}: {spec.design_type}, mood={spec.mood}, "
                f"colors={len(spec.color_palette)}"
            )
        except Exception:
            continue
    return "\n".join(summaries)


def _edit_spec_interactive(spec: DesignSpec) -> DesignSpec:
    editor = os.environ.get("EDITOR", "nano")
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, encoding="utf-8"
    ) as f:
        f.write(spec_to_json(spec))
        tmp_path = f.name
    try:
        subprocess.run([editor, tmp_path], check=False)
        edited = Path(tmp_path).read_text(encoding="utf-8")
        return spec_from_json(edited)
    finally:
        Path(tmp_path).unlink(missing_ok=True)


class SessionLogger:
    def __init__(self, enabled: bool) -> None:
        self.enabled = enabled
        self.lines: list[str] = []
        self.path: Path | None = None
        if enabled:
            SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
            ts = datetime.now().strftime("%Y%m%d-%H%M%S")
            self.path = SESSIONS_DIR / f"{ts}.md"
            self.log(f"# Session {ts}\n")

    def log(self, line: str) -> None:
        if not self.enabled:
            return
        redacted = line
        for secret_key in ("ANTHROPIC_API_KEY", "CANVA_ACCESS_TOKEN", "sk-ant"):
            if secret_key in redacted:
                redacted = redacted.replace(secret_key, "[REDACTED]")
        self.lines.append(redacted)

    def flush(self) -> None:
        if self.enabled and self.path:
            self.path.write_text("\n".join(self.lines), encoding="utf-8")
            console.print(f"[dim]Session log saved to {self.path}[/dim]")


def _review_loop(
    spec: DesignSpec,
    image_path: Path,
    notes: str,
    analysis_model: str,
    build_model: str,
    memory_context: str,
    logger: SessionLogger,
) -> None:
    while True:
        _display_spec(spec)
        console.print(
            "\nWhat would you like to do? "
            "(approve / edit / revise <feedback> / restart / save / quit)"
        )
        choice = Prompt.ask(">").strip()

        if choice == "approve":
            logger.log("User approved spec for Phase 2")
            console.print(
                f"\n[bold]Building with {resolve_model(build_model)} via Canva MCP...[/bold] "
                f"estimated cost: {format_cost_estimate(build_model)}"
            )
            build_design(spec, model=build_model)
            _post_build_loop(spec, build_model, logger)
            return

        if choice == "edit":
            try:
                spec = _edit_spec_interactive(spec)
                console.print("[green]Spec updated.[/green]")
                logger.log("User edited spec manually")
            except Exception as e:
                console.print(f"[red]Edit failed: {e}[/red]")
            continue

        if choice.startswith("revise "):
            feedback = choice[7:].strip()
            if not feedback:
                console.print("[yellow]Usage: revise <your feedback>[/yellow]")
                continue
            console.print(
                f"[cyan]Revising with {resolve_model(analysis_model)}...[/cyan] "
                f"estimated cost: {format_cost_estimate(analysis_model)}"
            )
            try:
                spec = revise_spec(spec, feedback, analysis_model)
                logger.log(f"Revised spec: {feedback[:200]}")
            except Exception as e:
                console.print(f"[red]Revise failed: {e}[/red]")
            continue

        if choice == "restart":
            console.print("[cyan]Re-analyzing image...[/cyan]")
            new_notes = Prompt.ask("Brief notes about your intent?", default=notes)
            spec = analyze_image(image_path, new_notes, analysis_model, memory_context)
            notes = new_notes
            logger.log("Restarted Phase 1 analysis")
            continue

        if choice == "save":
            path = _save_spec(spec)
            console.print(f"[green]Saved to {path}[/green]")
            logger.log(f"Saved spec to {path.name}")
            continue

        if choice in ("quit", "q", "exit"):
            console.print("Exiting without building. Bye.")
            logger.log("User quit before Phase 2")
            return

        console.print("[yellow]Unknown command. Try: approve, edit, revise ..., restart, save, quit[/yellow]")


def _post_build_loop(spec: DesignSpec, build_model: str, logger: SessionLogger) -> None:
    while True:
        console.print("\nWhat next? (tweak <feedback> / done)")
        choice = Prompt.ask(">").strip()
        if choice == "done":
            console.print("Bye.")
            logger.log("Session complete")
            return
        if choice.startswith("tweak "):
            feedback = choice[6:].strip()
            if not feedback:
                console.print("[yellow]Usage: tweak <your feedback>[/yellow]")
                continue
            logger.log(f"Tweak: {feedback[:200]}")
            build_design(spec, model=build_model, feedback=feedback)
            continue
        console.print("[yellow]Unknown command. Try: tweak ..., done[/yellow]")


@app.callback(invoke_without_command=True)
def main(ctx: typer.Context) -> None:
    if ctx.invoked_subcommand is None:
        console.print("Welcome to [bold]canva-design-agent[/bold].")
        console.print("Run: [cyan]python -m canva_agent run --image <path>[/cyan]")


@app.command()
def run(
    image: Optional[Path] = typer.Option(None, "--image", "-i", help="Reference image path"),
    analysis_model: str = typer.Option(
        DEFAULT_ANALYSIS_MODEL, "--analysis-model", help="haiku | sonnet | opus"
    ),
    build_model: str = typer.Option(
        DEFAULT_BUILD_MODEL, "--build-model", help="haiku | sonnet | opus"
    ),
    memory: bool = typer.Option(False, "--memory", help="Load prior saved specs as context"),
    log_session: bool = typer.Option(False, "--log-session", help="Save session transcript"),
) -> None:
    """Analyze a reference image and optionally build in Canva."""
    try:
        load_env()
        logger = SessionLogger(log_session)

        if image is None:
            image_str = Prompt.ask("Reference image path?")
            image = Path(image_str)
        else:
            image = Path(image)

        image = image.expanduser().resolve()
        if not image.exists():
            console.print(f"[red]Image not found: {image}[/red]")
            raise typer.Exit(1)

        notes = Prompt.ask("Brief notes about your intent?", default="")

        memory_context = ""
        if memory:
            memory_context = _load_memory_context()
            count = len([l for l in memory_context.splitlines() if l.strip()])
            console.print(f"[dim]Loaded {count} prior specs as context.[/dim]")
            logger.log(f"Memory: {count} prior specs")

        console.print(
            f"\n[bold]Analyzing with {resolve_model(analysis_model)}...[/bold] "
            f"estimated cost: {format_cost_estimate(analysis_model)}"
        )
        logger.log(f"Phase 1: image={image.name}, model={analysis_model}")

        spec = analyze_image(image, notes, analysis_model, memory_context)
        logger.log("Phase 1 complete")
        _review_loop(spec, image, notes, analysis_model, build_model, memory_context, logger)
        logger.flush()

    except KeyboardInterrupt:
        console.print("\nInterrupted. Bye.")
        raise typer.Exit(0)
    except (RuntimeError, ValueError, FileNotFoundError) as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)
    except Exception as e:
        console.print(f"[red]Unexpected error:[/red] {e}")
        raise typer.Exit(1)


def _main() -> None:
    app()


if __name__ == "__main__":
    _main()
