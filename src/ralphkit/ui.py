"""Centralized terminal output using Rich."""

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


def print_plan_summary(plan: dict) -> None:
    """Print a Rich table summarizing plan items."""
    items = plan.get("items", [])
    table = Table(
        box=box.SIMPLE_HEAVY,
        show_edge=False,
        padding=(0, 1),
    )
    table.add_column("#", justify="right", style="bold")
    table.add_column("Item")
    table.add_column("Done", justify="center")
    for item in items:
        done_icon = "\u2611" if item.get("done", False) else "\u2610"
        table.add_row(
            str(item.get("id", "")),
            item.get("title", ""),
            done_icon,
        )
    console.print(table)


def print_plan_progress(done: int, total: int) -> None:
    """Print progress bar for plan items."""
    if total == 0:
        return
    filled = int(10 * done / total)
    bar = "\u2588" * filled + "\u2591" * (10 - filled)
    console.print(f"  [label]Progress:[/] {done}/{total} items done  {bar}")


def print_current_item(item: dict) -> None:
    """Print the current plan item being worked on."""
    item_id = item.get("id", "?")
    title = item.get("title", "")
    console.print(f"  [label]Item:[/] #{item_id} \u2014 {title}")
