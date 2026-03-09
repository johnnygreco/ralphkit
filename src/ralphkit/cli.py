from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Optional

import typer

from ralphkit.ui import console

if TYPE_CHECKING:
    from collections.abc import Callable

    from ralphkit.config import RalphConfig, StepConfig


app = typer.Typer(
    help="ralphkit \u2014 agent pipes and loops for Claude Code.",
    rich_markup_mode="rich",
    no_args_is_help=True,
    add_completion=False,
)


# -- Shared option types --

ModelOpt = Annotated[
    Optional[str], typer.Option("--default-model", help="Override default model")
]
StateDirOpt = Annotated[
    Optional[str], typer.Option("--state-dir", help="Override state directory")
]
HostOpt = Annotated[
    Optional[str],
    typer.Option("--host", "-H", help="Host ('local' for tmux, or SSH host name)"),
]
MaxIterOpt = Annotated[
    Optional[int], typer.Option("--max-iterations", help="Override max iterations")
]
WorkingDirOpt = Annotated[
    Optional[str],
    typer.Option("--working-dir", help="Working directory for background job"),
]
RalphVersionOpt = Annotated[
    Optional[str],
    typer.Option(
        "--ralph-version", help="ralphkit version for remote (default: latest)"
    ),
]
ForceOpt = Annotated[bool, typer.Option("-f", "--force", help="Skip confirmation")]


# -- Version callback --


def _version_callback(value: bool) -> None:
    if value:
        from ralphkit._version import version

        print(f"ralphkit {version}")
        raise typer.Exit()


@app.callback()
def main_callback(
    version: Annotated[
        Optional[bool],
        typer.Option(
            "--version", callback=_version_callback, is_eager=True, help="Show version"
        ),
    ] = None,
) -> None:
    pass


# -- Dispatch helpers --


def _is_remote(host: str | None) -> bool:
    """Check if a host refers to a remote SSH target (not local or None)."""
    return host is not None and host != "local"


def _print_submit_info(job_id: str, host: str, working_dir: str | None) -> None:
    is_remote = _is_remote(host)
    host_flag = f" --host {host}" if is_remote else ""
    console.print()
    console.print(f"  [success]Submitted[/] {job_id}")
    console.print(f"  [dim]Host:[/]      {host if is_remote else 'localhost'}")
    if working_dir:
        console.print(f"  [dim]Dir:[/]       {working_dir}")
    console.print(f"  [dim]Session:[/]   {job_id}")
    if is_remote:
        console.print(f"  [dim]Attach:[/]    ssh -t {host} tmux attach -t {job_id}")
    else:
        console.print(f"  [dim]Attach:[/]    tmux attach -t {job_id}")
    console.print(f"  [dim]Logs:[/]      ralphkit logs {job_id}{host_flag}")
    console.print()


def _dispatch(
    *,
    subcommand: str,
    task: str | None,
    host: str | None,
    force: bool,
    default_model: str | None = None,
    state_dir: str | None = None,
    ralph_config: "RalphConfig | None" = None,
    config_file: Path | None = None,
    max_iterations: int | None = None,
    plan_path: str | None = None,
    plan_only: bool = False,
    plan_model: str | None = None,
    working_dir: str | None = None,
    ralph_version: str | None = None,
) -> None:
    """Route a command to foreground execution or background submission."""
    if host is None and (working_dir or ralph_version):
        from ralphkit.ui import print_error

        unused = []
        if working_dir:
            unused.append("--working-dir")
        if ralph_version:
            unused.append("--ralph-version")
        print_error(f"{', '.join(unused)} requires --host")
        raise SystemExit(1)

    if ralph_config is not None and config_file is not None:
        raise ValueError("cannot pass both ralph_config and config_file")

    if host is None:
        from ralphkit.engine import run_foreground

        run_foreground(
            task=task,
            config_path=str(config_file) if config_file else None,
            max_iterations=max_iterations,
            default_model=default_model,
            state_dir=state_dir,
            force=force,
            plan_path=plan_path,
            plan_only=plan_only,
            plan_model=plan_model,
            ralph_config=ralph_config,
        )
        return

    # -- Background submission --
    from ralphkit.engine import resolve_task
    from ralphkit.jobs import make_job_id

    resolved_task = resolve_task(task) if task else None
    job_id = make_job_id(resolved_task or "job")
    is_remote = _is_remote(host)

    # Build CLI args for the background subcommand
    args: list[str] = []
    if resolved_task:
        args.append(resolved_task)
    if config_file and not is_remote:
        args += ["--config", str(config_file.resolve())]
    if max_iterations is not None:
        args += ["--max-iterations", str(max_iterations)]
    if default_model:
        args += ["--default-model", default_model]
    if state_dir:
        args += ["--state-dir", state_dir]
    if plan_model:
        args += ["--plan-model", plan_model]
    if plan_path and not is_remote:
        args += ["--plan", plan_path]
    if plan_only:
        args.append("--plan-only")
    args.append("--force")

    config_content = config_file.read_text() if (is_remote and config_file) else None

    plan_content = None
    if is_remote and plan_path:
        try:
            plan_content = Path(plan_path).read_text()
        except (FileNotFoundError, OSError):
            from ralphkit.ui import print_error

            print_error(f"Plan file not found: {plan_path}")
            raise SystemExit(1)

    if is_remote:
        from ralphkit.remote import submit_job

        submit_job(
            host,
            job_id,
            args,
            subcommand=subcommand,
            working_dir=working_dir,
            ralph_version=ralph_version,
            config_content=config_content,
            plan_content=plan_content,
        )
    else:
        from ralphkit.local import submit_local

        submit_local(job_id, args, subcommand=subcommand, working_dir=working_dir)

    _print_submit_info(job_id, host=host, working_dir=working_dir)


# -- Workflow commands --


def _pipe_workflow(
    subcommand: str,
    task: str,
    steps_factory: "Callable[[], list[StepConfig]]",
    *,
    default_model: str | None,
    state_dir: str | None,
    host: str | None,
    force: bool,
    working_dir: str | None,
    ralph_version: str | None,
) -> None:
    """Shared implementation for pipe-based workflow commands."""
    from ralphkit.config import (
        DEFAULT_MAX_ITERATIONS,
        DEFAULT_MODEL,
        STATE_DIR,
        RalphConfig,
    )

    ralph_config = RalphConfig(
        max_iterations=DEFAULT_MAX_ITERATIONS,
        default_model=DEFAULT_MODEL,
        state_dir=STATE_DIR,
        loop=[],
        pipe=steps_factory(),
    )

    _dispatch(
        subcommand=subcommand,
        task=task,
        host=host,
        force=force,
        ralph_config=ralph_config,
        default_model=default_model,
        state_dir=state_dir,
        working_dir=working_dir,
        ralph_version=ralph_version,
    )


@app.command()
def build(
    task: Annotated[
        str, typer.Argument(help="Task description (string or path to .md file)")
    ],
    default_model: ModelOpt = None,
    state_dir: StateDirOpt = None,
    host: HostOpt = None,
    force: ForceOpt = False,
    max_iterations: MaxIterOpt = None,
    plan_model: Annotated[
        Optional[str],
        typer.Option("--plan-model", help="Override model for planning step"),
    ] = None,
    plan: Annotated[
        Optional[Path],
        typer.Option("--plan", help="Path to pre-made tickets.json (skips planning)"),
    ] = None,
    plan_only: Annotated[
        bool,
        typer.Option("--plan-only", help="Generate plan and exit"),
    ] = False,
    working_dir: WorkingDirOpt = None,
    ralph_version: RalphVersionOpt = None,
) -> None:
    """Build a feature using a plan-driven loop (plan \u2192 build \u2192 review)."""
    from ralphkit.config import (
        DEFAULT_MAX_ITERATIONS,
        DEFAULT_MODEL,
        STATE_DIR,
        RalphConfig,
    )
    from ralphkit.prompts import make_build_config

    cfg = make_build_config()
    ralph_config = RalphConfig(
        max_iterations=DEFAULT_MAX_ITERATIONS,
        default_model=DEFAULT_MODEL,
        state_dir=STATE_DIR,
        loop=cfg["loop"],
        cleanup=cfg["cleanup"],
    )

    _dispatch(
        subcommand="build",
        task=task,
        host=host,
        force=force,
        ralph_config=ralph_config,
        default_model=default_model,
        state_dir=state_dir,
        max_iterations=max_iterations,
        plan_path=str(plan) if plan else None,
        plan_only=plan_only,
        plan_model=plan_model,
        working_dir=working_dir,
        ralph_version=ralph_version,
    )


@app.command()
def fix(
    task: Annotated[
        str, typer.Argument(help="Bug description (string or path to .md file)")
    ],
    default_model: ModelOpt = None,
    state_dir: StateDirOpt = None,
    host: HostOpt = None,
    force: ForceOpt = False,
    working_dir: WorkingDirOpt = None,
    ralph_version: RalphVersionOpt = None,
) -> None:
    """Fix a bug using a diagnostic pipeline (diagnose \u2192 fix \u2192 verify)."""
    from ralphkit.prompts import make_fix_config

    _pipe_workflow(
        "fix",
        task,
        make_fix_config,
        default_model=default_model,
        state_dir=state_dir,
        host=host,
        force=force,
        working_dir=working_dir,
        ralph_version=ralph_version,
    )


@app.command()
def research(
    task: Annotated[
        str, typer.Argument(help="Research topic (string or path to .md file)")
    ],
    default_model: ModelOpt = None,
    state_dir: StateDirOpt = None,
    host: HostOpt = None,
    force: ForceOpt = False,
    working_dir: WorkingDirOpt = None,
    ralph_version: RalphVersionOpt = None,
) -> None:
    """Research a topic using a pipeline (explore \u2192 synthesize \u2192 report)."""
    from ralphkit.prompts import make_research_config

    _pipe_workflow(
        "research",
        task,
        make_research_config,
        default_model=default_model,
        state_dir=state_dir,
        host=host,
        force=force,
        working_dir=working_dir,
        ralph_version=ralph_version,
    )


@app.command()
def plan(
    task: Annotated[
        str, typer.Argument(help="Task to plan (string or path to .md file)")
    ],
    default_model: ModelOpt = None,
    state_dir: StateDirOpt = None,
    host: HostOpt = None,
    force: ForceOpt = False,
    working_dir: WorkingDirOpt = None,
    ralph_version: RalphVersionOpt = None,
) -> None:
    """Plan an implementation (analyze \u2192 design document)."""
    from ralphkit.prompts import make_plan_config

    _pipe_workflow(
        "plan",
        task,
        make_plan_config,
        default_model=default_model,
        state_dir=state_dir,
        host=host,
        force=force,
        working_dir=working_dir,
        ralph_version=ralph_version,
    )


@app.command()
def big_swing(
    task: Annotated[
        str, typer.Argument(help="Task description (string or path to .md file)")
    ],
    default_model: ModelOpt = None,
    state_dir: StateDirOpt = None,
    host: HostOpt = None,
    force: ForceOpt = False,
    working_dir: WorkingDirOpt = None,
    ralph_version: RalphVersionOpt = None,
) -> None:
    """Tackle an ambitious task (research \u2192 plan \u2192 build \u2192 review \u2192 fix \u2192 verify)."""
    from ralphkit.prompts import make_big_swing_config

    _pipe_workflow(
        "big-swing",
        task,
        make_big_swing_config,
        default_model=default_model,
        state_dir=state_dir,
        host=host,
        force=force,
        working_dir=working_dir,
        ralph_version=ralph_version,
    )


# -- Generic primitives --


@app.command()
def pipe(
    task: Annotated[
        Optional[str],
        typer.Argument(help="Task description (string or path to .md file)"),
    ] = None,
    config: Annotated[
        Path,
        typer.Option(
            "--config",
            "-c",
            help="Path to YAML config file (required)",
            exists=True,
            dir_okay=False,
        ),
    ] = ...,
    default_model: ModelOpt = None,
    state_dir: StateDirOpt = None,
    host: HostOpt = None,
    force: ForceOpt = False,
    working_dir: WorkingDirOpt = None,
    ralph_version: RalphVersionOpt = None,
) -> None:
    """Run a custom pipe from a YAML config file."""
    _dispatch(
        subcommand="pipe",
        task=task,
        host=host,
        force=force,
        config_file=config,
        default_model=default_model,
        state_dir=state_dir,
        working_dir=working_dir,
        ralph_version=ralph_version,
    )


@app.command()
def loop(
    task: Annotated[
        Optional[str],
        typer.Argument(help="Task description (string or path to .md file)"),
    ] = None,
    config: Annotated[
        Path,
        typer.Option(
            "--config",
            "-c",
            help="Path to YAML config file (required)",
            exists=True,
            dir_okay=False,
        ),
    ] = ...,
    default_model: ModelOpt = None,
    state_dir: StateDirOpt = None,
    host: HostOpt = None,
    force: ForceOpt = False,
    max_iterations: MaxIterOpt = None,
    plan_model: Annotated[
        Optional[str],
        typer.Option("--plan-model", help="Override model for planning step"),
    ] = None,
    plan: Annotated[
        Optional[Path],
        typer.Option("--plan", help="Path to pre-made tickets.json (skips planning)"),
    ] = None,
    plan_only: Annotated[
        bool,
        typer.Option("--plan-only", help="Generate plan and exit"),
    ] = False,
    working_dir: WorkingDirOpt = None,
    ralph_version: RalphVersionOpt = None,
) -> None:
    """Run a custom loop from a YAML config file."""
    _dispatch(
        subcommand="loop",
        task=task,
        host=host,
        force=force,
        config_file=config,
        default_model=default_model,
        state_dir=state_dir,
        max_iterations=max_iterations,
        plan_path=str(plan) if plan else None,
        plan_only=plan_only,
        plan_model=plan_model,
        working_dir=working_dir,
        ralph_version=ralph_version,
    )


# -- runs command --


@app.command()
def runs(state_dir: StateDirOpt = None) -> None:
    """List past completed runs."""
    import json

    from ralphkit.state import StateDir

    from ralphkit.config import STATE_DIR

    sd = StateDir(state_dir or STATE_DIR)
    run_list = sd.list_runs()
    if not run_list:
        console.print("No runs found.")
    else:
        for run_dir in run_list:
            task_file = run_dir / "task.md"
            first_line = ""
            if task_file.is_file():
                first_line = task_file.read_text().split("\n", 1)[0]

            plan_info = ""
            plan_path = run_dir / "tickets.json"
            if plan_path.is_file():
                try:
                    plan_data = json.loads(plan_path.read_text())
                    plan_items = plan_data.get("items", [])
                    done = sum(1 for it in plan_items if it.get("done", False))
                    total = len(plan_items)
                    outcome = ""
                    report_path = run_dir / "report.json"
                    if report_path.is_file():
                        report_data = json.loads(report_path.read_text())
                        outcome = report_data.get("outcome", "")
                    if outcome:
                        plan_info = f"  [dim][{outcome} {done}/{total}][/]"
                    else:
                        plan_info = f"  [dim][{done}/{total}][/]"
                except (json.JSONDecodeError, TypeError):
                    pass
            console.print(f"  [label]#{run_dir.name}[/]  {first_line}{plan_info}")


# -- jobs command --


@app.command()
def jobs(host: HostOpt = None) -> None:
    """List active ralphkit jobs."""
    from ralphkit.ui import print_jobs_table

    if _is_remote(host):
        from ralphkit.remote import list_jobs

        items = list_jobs(host)
    else:
        from ralphkit.local import list_local_jobs

        items = list_local_jobs()

    if not items:
        console.print("No active jobs.")
        return

    print_jobs_table(items, host_label=host or "local")


# -- logs command --


@app.command()
def logs(
    job_id: Annotated[str, typer.Argument(help="Job ID")],
    host: HostOpt = None,
    follow: Annotated[
        bool, typer.Option("-F", "--follow", help="Follow log output")
    ] = False,
) -> None:
    """View logs for a running or completed job."""
    if _is_remote(host):
        from ralphkit.remote import tail_logs

        tail_logs(host, job_id, follow)
    else:
        from ralphkit.local import tail_local_logs

        tail_local_logs(job_id, follow)


# -- cancel command --


@app.command()
def cancel(
    job_id: Annotated[str, typer.Argument(help="Job ID")],
    host: HostOpt = None,
) -> None:
    """Cancel a running job."""
    if _is_remote(host):
        from ralphkit.remote import cancel_job

        cancel_job(host, job_id)
    else:
        from ralphkit.local import cancel_local

        cancel_local(job_id)

    console.print(f"  [success]Cancelled[/] {job_id}")


# -- Migration shims for removed commands --


@app.command(hidden=True)
def run(
    args: Annotated[Optional[list[str]], typer.Argument(help="(removed)")] = None,
) -> None:
    """Removed — use 'ralphkit build' instead."""
    from ralphkit.ui import err_console

    err_console.print(
        "[error]Error:[/] 'run' was removed. Use [bold]ralphkit build[/] instead.\n"
        '  Example: ralphkit build "your task"'
    )
    raise typer.Exit(1)


@app.command(hidden=True)
def submit(
    args: Annotated[Optional[list[str]], typer.Argument(help="(removed)")] = None,
) -> None:
    """Removed — use '--host' flag instead."""
    from ralphkit.ui import err_console

    err_console.print(
        "[error]Error:[/] 'submit' was removed. Use [bold]--host[/] on any command instead.\n"
        '  Example: ralphkit build "task" --host mini'
    )
    raise typer.Exit(1)


# -- Entry point --


def main() -> None:
    app()
