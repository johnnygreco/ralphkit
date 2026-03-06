from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from rich import box
from rich.rule import Rule
from rich.table import Table

from ralphkit.ui import console, fmt_duration, print_banner


@dataclass
class StepRecord:
    step_name: str
    model: str
    phase: str  # "pipe", "setup", "loop", "cleanup"
    iteration: int | None = None
    duration_s: float = 0.0
    num_turns: int | None = None
    session_id: str | None = None
    is_error: bool | None = None
    duration_api_ms: int | None = None
    model_usage: dict | None = None  # raw modelUsage from Claude JSON
    lines_added: int = 0
    lines_deleted: int = 0


@dataclass
class RunReport:
    steps: list[StepRecord] = field(default_factory=list)
    outcome: str | None = None
    iterations_completed: int = 0
    total_duration_s: float = 0.0

    def record_step(
        self,
        *,
        step_name: str,
        model: str,
        phase: str,
        duration_s: float,
        iteration: int | None = None,
        claude_output: dict | None = None,
        lines_added: int = 0,
        lines_deleted: int = 0,
    ) -> None:
        num_turns = None
        session_id = None
        is_error = None
        duration_api_ms = None
        model_usage = None

        if claude_output and isinstance(claude_output, dict):
            num_turns = claude_output.get("num_turns")
            session_id = claude_output.get("session_id")
            is_error = claude_output.get("is_error")
            duration_api_ms = claude_output.get("duration_api_ms")
            model_usage = claude_output.get("modelUsage")

        self.steps.append(
            StepRecord(
                step_name=step_name,
                model=model,
                phase=phase,
                iteration=iteration,
                duration_s=duration_s,
                num_turns=num_turns,
                session_id=session_id,
                is_error=is_error,
                duration_api_ms=duration_api_ms,
                model_usage=model_usage,
                lines_added=lines_added,
                lines_deleted=lines_deleted,
            )
        )

    def total_turns(self) -> int:
        return sum(s.num_turns for s in self.steps if s.num_turns is not None)

    def token_usage_by_model(self) -> dict[str, dict[str, int]]:
        result: dict[str, dict[str, int]] = {}
        for step in self.steps:
            if not step.model_usage or not isinstance(step.model_usage, dict):
                continue
            for model_id, usage in step.model_usage.items():
                if not isinstance(usage, dict):
                    continue
                if model_id not in result:
                    result[model_id] = {}
                for key, value in usage.items():
                    if isinstance(value, (int, float)):
                        result[model_id][key] = result[model_id].get(key, 0) + int(
                            value
                        )
        return result

    def to_dict(self) -> dict:
        steps = []
        for s in self.steps:
            steps.append(
                {
                    "step_name": s.step_name,
                    "model": s.model,
                    "phase": s.phase,
                    "iteration": s.iteration,
                    "duration_s": s.duration_s,
                    "num_turns": s.num_turns,
                    "session_id": s.session_id,
                    "is_error": s.is_error,
                    "duration_api_ms": s.duration_api_ms,
                    "model_usage": s.model_usage,
                    "lines_added": s.lines_added,
                    "lines_deleted": s.lines_deleted,
                }
            )
        return {
            "outcome": self.outcome,
            "iterations_completed": self.iterations_completed,
            "total_duration_s": self.total_duration_s,
            "total_turns": self.total_turns(),
            "token_usage_by_model": self.token_usage_by_model(),
            "steps": steps,
        }

    def save(self, path: Path) -> None:
        path.write_text(json.dumps(self.to_dict(), indent=2) + "\n")


# ── Git helpers ────────────────────────────────────────────────────


def _parse_shortstat(text: str) -> tuple[int, int]:
    insertions = 0
    deletions = 0
    m = re.search(r"(\d+)\s+insertion", text)
    if m:
        insertions = int(m.group(1))
    m = re.search(r"(\d+)\s+deletion", text)
    if m:
        deletions = int(m.group(1))
    return insertions, deletions


def git_diff_stat() -> tuple[int, int]:
    try:
        proc = subprocess.run(
            ["git", "diff", "--shortstat", "HEAD"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return _parse_shortstat(proc.stdout)
    except Exception:
        return (0, 0)


# ── Report display ─────────────────────────────────────────────────


def _short_model(model: str) -> str:
    """Shorten model ID for display (e.g., 'claude-opus-4-6' -> 'opus')."""
    for part in ("opus", "sonnet", "haiku"):
        if part in model.lower():
            return part
    return model


def print_report(report: RunReport) -> None:
    console.print()
    print_banner("RUN REPORT")
    console.print()

    # Outcome
    outcome_str = report.outcome or "UNKNOWN"
    if report.iterations_completed > 0:
        outcome_str += f" ({report.iterations_completed} iteration(s))"
    if report.outcome in ("SHIP", "PIPE_COMPLETE"):
        outcome_display = f"[bold green]{outcome_str}[/]"
    elif report.outcome in ("MAX_ITERATIONS", "ERROR"):
        outcome_display = f"[bold red]{outcome_str}[/]"
    else:
        outcome_display = outcome_str
    console.print(f"  Outcome:     {outcome_display}")

    # Total time
    total_api_ms = sum(
        s.duration_api_ms for s in report.steps if s.duration_api_ms is not None
    )
    time_str = f"{fmt_duration(report.total_duration_s)}"
    if total_api_ms > 0:
        time_str += f" [dim](API: {fmt_duration(total_api_ms / 1000)})[/]"
    console.print(f"  Total time:  {time_str}")
    console.print()

    # Token usage table
    usage = report.token_usage_by_model()
    if usage:
        table = Table(
            title="Token Usage",
            title_style="bold yellow",
            box=box.SIMPLE_HEAVY,
            show_edge=False,
            padding=(0, 1),
        )
        table.add_column("Model", style="bold")
        table.add_column("Input", justify="right")
        table.add_column("Output", justify="right")
        table.add_column("Cache Read", justify="right")
        table.add_column("Cache Write", justify="right")
        for model_id, tokens in sorted(usage.items()):
            inp = tokens.get("inputTokens", 0)
            out = tokens.get("outputTokens", 0)
            cr = tokens.get("cacheReadInputTokens", 0)
            cw = tokens.get("cacheCreationInputTokens", 0)
            table.add_row(model_id, f"{inp:,}", f"{out:,}", f"{cr:,}", f"{cw:,}")
        console.print(table)
        console.print()

    # Steps table
    if report.steps:
        table = Table(
            title="Steps",
            title_style="bold yellow",
            box=box.SIMPLE_HEAVY,
            show_edge=False,
            padding=(0, 1),
        )
        table.add_column("Phase")
        table.add_column("Step")
        table.add_column("Model")
        table.add_column("Duration", justify="right")
        table.add_column("Turns", justify="right")
        table.add_column("+/-", justify="right")
        for s in report.steps:
            phase = s.phase
            if s.iteration is not None:
                phase = f"loop:{s.iteration}"
            turns_str = str(s.num_turns) if s.num_turns is not None else "-"
            diff_str = f"[green]+{s.lines_added}[/]/[red]-{s.lines_deleted}[/]"
            table.add_row(
                phase,
                s.step_name,
                _short_model(s.model),
                fmt_duration(s.duration_s),
                turns_str,
                diff_str,
            )
        console.print(table)
        console.print()

    # Totals
    total_added = sum(s.lines_added for s in report.steps)
    total_deleted = sum(s.lines_deleted for s in report.steps)
    total_turns = report.total_turns()
    error_count = sum(1 for s in report.steps if s.is_error is True)

    console.print(Rule("Totals", style="yellow"))
    console.print(
        f"  Lines changed:  [green]+{total_added}[/] / [red]-{total_deleted}[/]"
    )
    console.print(f"  Total turns:    {total_turns}")
    console.print(f"  Errors:         {error_count}")
    console.print()
