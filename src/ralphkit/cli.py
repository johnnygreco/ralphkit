from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Optional

import typer

from ralphkit.ui import console

if TYPE_CHECKING:
    from ralphkit.config import RalphConfig


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
TimeoutOpt = Annotated[
    Optional[int], typer.Option("--timeout-seconds", help="Override hard timeout")
]
IdleTimeoutOpt = Annotated[
    Optional[int],
    typer.Option(
        "--idle-timeout-seconds", help="Override idle timeout (disabled by default)"
    ),
]
CleanupOnErrorOpt = Annotated[
    Optional[str],
    typer.Option(
        "--cleanup-on-error",
        help="Cleanup policy after a failure: full, light, or skip",
    ),
]
IsolationOpt = Annotated[
    Optional[str],
    typer.Option("--isolation", help="Isolation mode for submitted jobs"),
]
ResumeRunOpt = Annotated[
    Optional[str],
    typer.Option("--resume-run", help="Reuse an existing run directory"),
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
    timeout_seconds: int | None = None,
    idle_timeout_seconds: int | None = None,
    cleanup_on_error: str | None = None,
    isolation: str | None = None,
    plan_path: str | None = None,
    plan_only: bool = False,
    plan_model: str | None = None,
    max_cost: float | None = None,
    max_duration_seconds: int | None = None,
    completion_consensus: int | None = None,
    verify_command: str | None = None,
    verify_timeout: int | None = None,
    resume_run: str | None = None,
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
            timeout_seconds=timeout_seconds,
            idle_timeout_seconds=idle_timeout_seconds,
            cleanup_on_error=cleanup_on_error,
            force=force,
            plan_path=plan_path,
            plan_only=plan_only,
            plan_model=plan_model,
            max_cost=max_cost,
            max_duration_seconds=max_duration_seconds,
            completion_consensus=completion_consensus,
            verify_command=verify_command,
            verify_timeout=verify_timeout,
            resume_run=resume_run,
            ralph_config=ralph_config,
        )
        return

    # -- Background submission --
    from ralphkit.engine import resolve_task
    from ralphkit.jobs import make_job_id

    resolved_task = resolve_task(task) if task else None
    job_id = make_job_id(resolved_task or "job")
    is_remote = _is_remote(host)
    effective_working_dir = working_dir or str(Path.cwd())

    # Build CLI args for the background subcommand
    args: list[str] = []
    if resolved_task:
        args.append(resolved_task)
    if config_file and not is_remote:
        args += ["--config", str(config_file.resolve())]
    if max_iterations is not None:
        args += ["--max-iterations", str(max_iterations)]
    if timeout_seconds is not None:
        args += ["--timeout-seconds", str(timeout_seconds)]
    if idle_timeout_seconds is not None:
        args += ["--idle-timeout-seconds", str(idle_timeout_seconds)]
    if default_model:
        args += ["--default-model", default_model]
    if state_dir:
        args += ["--state-dir", state_dir]
    if cleanup_on_error:
        args += ["--cleanup-on-error", cleanup_on_error]
    if isolation:
        args += ["--isolation", isolation]
    if plan_model:
        args += ["--plan-model", plan_model]
    if plan_path and not is_remote:
        args += ["--plan", plan_path]
    if plan_only:
        args.append("--plan-only")
    if max_cost is not None:
        args += ["--max-cost", str(max_cost)]
    if max_duration_seconds is not None:
        args += ["--max-duration", str(max_duration_seconds)]
    if completion_consensus is not None:
        args += ["--completion-consensus", str(completion_consensus)]
    if verify_command:
        args += ["--verify", verify_command]
    if verify_timeout is not None:
        args += ["--verify-timeout", str(verify_timeout)]
    if resume_run:
        args += ["--resume-run", resume_run]
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
            working_dir=effective_working_dir,
            ralph_version=ralph_version,
            isolation=isolation,
            config_content=config_content,
            plan_content=plan_content,
        )
    else:
        from ralphkit.local import submit_local

        submit_local(
            job_id,
            args,
            subcommand=subcommand,
            working_dir=effective_working_dir,
            isolation=isolation,
        )

    _print_submit_info(job_id, host=host, working_dir=effective_working_dir)


# -- Workflow commands --


MaxCostOpt = Annotated[
    Optional[float],
    typer.Option("--max-cost", help="Stop when estimated cost exceeds this (USD)"),
]
MaxDurationOpt = Annotated[
    Optional[int],
    typer.Option("--max-duration", help="Stop after this many seconds of wall time"),
]
CompletionConsensusOpt = Annotated[
    Optional[int],
    typer.Option(
        "--completion-consensus",
        help="Consecutive completion signals needed to stop (default: 2)",
    ),
]
VerifyOpt = Annotated[
    Optional[str],
    typer.Option(
        "--verify", help="Command to run after each iteration (e.g. 'pytest tests/')"
    ),
]
VerifyTimeoutOpt = Annotated[
    Optional[int],
    typer.Option(
        "--verify-timeout", help="Timeout for verify command in seconds (default: 300)"
    ),
]


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
    timeout_seconds: TimeoutOpt = None,
    idle_timeout_seconds: IdleTimeoutOpt = None,
    cleanup_on_error: CleanupOnErrorOpt = None,
    isolation: IsolationOpt = None,
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
    max_cost: MaxCostOpt = None,
    max_duration: MaxDurationOpt = None,
    completion_consensus: CompletionConsensusOpt = None,
    verify: VerifyOpt = None,
    verify_timeout: VerifyTimeoutOpt = None,
    resume_run: ResumeRunOpt = None,
    working_dir: WorkingDirOpt = None,
    ralph_version: RalphVersionOpt = None,
) -> None:
    """Build a feature using a plan-driven loop (plan -> build -> review)."""
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
        timeout_seconds=timeout_seconds,
        idle_timeout_seconds=idle_timeout_seconds,
        cleanup_on_error=cleanup_on_error,
        isolation=isolation,
        plan_path=str(plan) if plan else None,
        plan_only=plan_only,
        plan_model=plan_model,
        max_cost=max_cost,
        max_duration_seconds=max_duration,
        completion_consensus=completion_consensus,
        verify_command=verify,
        verify_timeout=verify_timeout,
        resume_run=resume_run,
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
    timeout_seconds: TimeoutOpt = None,
    idle_timeout_seconds: IdleTimeoutOpt = None,
    cleanup_on_error: CleanupOnErrorOpt = None,
    isolation: IsolationOpt = None,
    resume_run: ResumeRunOpt = None,
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
        timeout_seconds=timeout_seconds,
        idle_timeout_seconds=idle_timeout_seconds,
        cleanup_on_error=cleanup_on_error,
        isolation=isolation,
        resume_run=resume_run,
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
    timeout_seconds: TimeoutOpt = None,
    idle_timeout_seconds: IdleTimeoutOpt = None,
    cleanup_on_error: CleanupOnErrorOpt = None,
    isolation: IsolationOpt = None,
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
    max_cost: MaxCostOpt = None,
    max_duration: MaxDurationOpt = None,
    completion_consensus: CompletionConsensusOpt = None,
    verify: VerifyOpt = None,
    verify_timeout: VerifyTimeoutOpt = None,
    resume_run: ResumeRunOpt = None,
    working_dir: WorkingDirOpt = None,
    ralph_version: RalphVersionOpt = None,
) -> None:
    """Run a custom loop from a YAML config file."""
    if task is None and resume_run is None:
        from ralphkit.ui import print_error

        print_error("task is required for loop mode (or use --resume-run)")
        raise typer.Exit(1)

    _dispatch(
        subcommand="loop",
        task=task,
        host=host,
        force=force,
        config_file=config,
        default_model=default_model,
        state_dir=state_dir,
        max_iterations=max_iterations,
        timeout_seconds=timeout_seconds,
        idle_timeout_seconds=idle_timeout_seconds,
        cleanup_on_error=cleanup_on_error,
        isolation=isolation,
        plan_path=str(plan) if plan else None,
        plan_only=plan_only,
        plan_model=plan_model,
        max_cost=max_cost,
        max_duration_seconds=max_duration,
        completion_consensus=completion_consensus,
        verify_command=verify,
        verify_timeout=verify_timeout,
        resume_run=resume_run,
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
