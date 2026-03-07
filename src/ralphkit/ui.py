"""Centralized terminal output using Rich."""

import time as _time

from rich import box
from rich.box import HEAVY
from rich.console import Console
from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table
from rich.theme import Theme

RALPH_THEME = Theme(
    {
        "banner": "bold blue",
        "label": "yellow",
        "success": "bold green",
        "error": "bold red",
        "warning": "yellow",
        "info": "blue",
        "dim": "dim",
    }
)

console = Console(theme=RALPH_THEME)
err_console = Console(theme=RALPH_THEME, stderr=True)


def _print_panel(title: str, style: str) -> None:
    console.print(Panel(f"  {title}", box=HEAVY, style=style, expand=True))


def print_banner(title: str) -> None:
    _print_panel(title, "banner")


def print_outcome(title: str, *, success: bool) -> None:
    _print_panel(title, "success" if success else "error")


def print_rule(label: str) -> None:
    console.print(Rule(label, style="info"))


def print_step_start(idx: int, total: int, name: str, model: str | None = None) -> None:
    model_part = f" [dim]({model})[/]" if model else ""
    console.print(f"  \u2192 [{idx}/{total}] {name}{model_part}...")


def print_step_done(elapsed: str) -> None:
    console.print(f"  [success]\u2713 Done[/] [dim]({elapsed})[/]")


def print_kv(key: str, value: str) -> None:
    console.print(f"  [label]{key + ':':<10}[/] {value}")


def print_indented_block(header: str, body: str) -> None:
    indented = "\n".join(f"       {line}" for line in body.splitlines())
    console.print(f"\n     [label]{header}:[/]\n{indented}\n")


def fmt_duration(seconds: float) -> str:
    if seconds >= 60:
        m = int(seconds) // 60
        s = seconds - m * 60
        return f"{m}m {s:.0f}s"
    return f"{seconds:.1f}s"


def print_error(msg: str) -> None:
    err_console.print(f"[error]{msg}[/]")


def print_warning(msg: str) -> None:
    console.print(f"[warning]{msg}[/]")


def print_jobs_table(jobs: list[dict], host_label: str) -> None:
    """Display a rich table of jobs with status and duration."""
    table = Table(box=box.SIMPLE_HEAVY, show_edge=False, padding=(0, 1))
    table.add_column("Job ID", style="label")
    table.add_column("Host")
    table.add_column("Status")
    table.add_column("Duration", justify="right")

    now = _time.time()
    for job in jobs:
        status = (
            "[error]exited[/]" if job.get("pane_dead") == "1" else "[success]running[/]"
        )
        created = int(job.get("created") or now)
        duration = fmt_duration(now - created)
        table.add_row(job["name"], host_label, status, duration)

    console.print(table)
