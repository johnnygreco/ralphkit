import os
from pathlib import Path
from typing import Annotated, Optional

import typer
from typer.core import TyperGroup

from ralphkit.ui import console


class RalphGroup(TyperGroup):
    """Custom group that routes bare `ralph "task"` to `ralph run "task"`."""

    def parse_args(self, ctx, args):
        if args and args[0] not in self.commands and not args[0].startswith("-"):
            args = ["run"] + args
        return super().parse_args(ctx, args)


app = typer.Typer(
    cls=RalphGroup,
    help="ralphkit \u2014 agent pipes and loops for Claude Code.",
    rich_markup_mode="rich",
    no_args_is_help=True,
    add_completion=False,
)


# -- Shared option types --

ConfigOpt = Annotated[
    Optional[Path],
    typer.Option(
        "--config", "-c", help="Path to YAML config file", exists=True, dir_okay=False
    ),
]
MaxIterOpt = Annotated[
    Optional[int], typer.Option("--max-iterations", help="Override max iterations")
]
ModelOpt = Annotated[
    Optional[str], typer.Option("--default-model", help="Override default model")
]
StateDirOpt = Annotated[
    Optional[str], typer.Option("--state-dir", help="Override state directory")
]
HostOpt = Annotated[
    Optional[str],
    typer.Option("--host", "-H", help="Remote SSH host (from ~/.ssh/config)"),
]


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


# -- run command --


@app.command()
def run(
    task: Annotated[
        Optional[str],
        typer.Argument(help="Task description (string or path to .md file)"),
    ] = None,
    config: ConfigOpt = None,
    max_iterations: MaxIterOpt = None,
    default_model: ModelOpt = None,
    state_dir: StateDirOpt = None,
    force: Annotated[
        bool, typer.Option("-f", "--force", help="Skip confirmation")
    ] = False,
    plan: Annotated[
        Optional[Path],
        typer.Option("--plan", help="Path to pre-made plan.json (skips planning step)"),
    ] = None,
    plan_only: Annotated[
        bool,
        typer.Option("--plan-only", help="Generate plan and exit"),
    ] = False,
    plan_model: Annotated[
        Optional[str],
        typer.Option("--plan-model", help="Override model for planning step"),
    ] = None,
) -> None:
    """Run a task locally in the foreground."""
    from ralphkit.engine import run_foreground

    run_foreground(
        task=task,
        config_path=str(config) if config else None,
        max_iterations=max_iterations,
        default_model=default_model,
        state_dir=state_dir,
        force=force,
        plan_path=str(plan) if plan else None,
        plan_only=plan_only,
        plan_model=plan_model,
    )


# -- runs command --


@app.command()
def runs(state_dir: StateDirOpt = None) -> None:
    """List past completed runs."""
    import json

    from ralphkit.state import StateDir

    sd = StateDir(state_dir or ".ralphkit")
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
            plan_path = run_dir / "plan.json"
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


# -- submit command --


def _build_ralph_args(
    task: str | None,
    config: Path | None,
    max_iterations: int | None,
    default_model: str | None,
    state_dir: str | None,
    *,
    remote: bool = False,
) -> list[str]:
    """Build argument list for ralph run."""
    args = [task] if task else []
    if config:
        args += ["--config", str(config) if remote else str(config.resolve())]
    if max_iterations is not None:
        args += ["--max-iterations", str(max_iterations)]
    if default_model:
        args += ["--default-model", default_model]
    if state_dir:
        args += ["--state-dir", state_dir]
    return args


def _print_submit_info(
    job_id: str,
    host: str | None,
    working_dir: str | None,
) -> None:
    host_flag = f" --host {host}" if host else ""
    console.print()
    console.print(f"  [success]Submitted[/] {job_id}")
    console.print(f"  [dim]Host:[/]    {host or 'localhost'}")
    if working_dir:
        console.print(f"  [dim]Dir:[/]     {working_dir}")
    console.print(f"  [dim]Attach:[/]  ralph attach {job_id}{host_flag}")
    console.print(f"  [dim]Logs:[/]    ralph logs {job_id}{host_flag}")
    console.print()


def _do_attach(job_id: str, host: str | None) -> None:
    if host:
        from ralphkit.remote import get_attach_command

        cmd = get_attach_command(host, job_id)
    else:
        cmd = ["tmux", "attach", "-t", job_id]
    os.execvp(cmd[0], cmd)


@app.command()
def submit(
    task: Annotated[
        Optional[str],
        typer.Argument(help="Task description (string or path to .md file)"),
    ] = None,
    config: ConfigOpt = None,
    max_iterations: MaxIterOpt = None,
    default_model: ModelOpt = None,
    state_dir: StateDirOpt = None,
    host: HostOpt = None,
    attach: Annotated[
        bool, typer.Option("--attach", help="Attach to tmux session after submit")
    ] = False,
    working_dir: Annotated[
        Optional[str], typer.Option("--working-dir", help="Working directory for job")
    ] = None,
    ralph_version: Annotated[
        Optional[str],
        typer.Option(
            "--ralph-version", help="ralphkit version for remote (default: latest)"
        ),
    ] = None,
) -> None:
    """Submit a task to run in the background (local tmux or remote)."""
    from ralphkit.jobs import make_job_id

    job_id = make_job_id(task or "job")
    ralph_args = _build_ralph_args(
        task, config, max_iterations, default_model, state_dir, remote=bool(host)
    )
    ralph_args.append("--force")

    if host:
        from ralphkit.remote import submit_job

        submit_job(
            host,
            job_id,
            ralph_args,
            working_dir=working_dir,
            ralph_version=ralph_version,
        )
        _print_submit_info(job_id, host=host, working_dir=working_dir)
    else:
        from ralphkit.local import submit_local

        submit_local(job_id, ralph_args, working_dir)
        _print_submit_info(job_id, host=None, working_dir=working_dir)

    if attach:
        _do_attach(job_id, host)


# -- jobs command --


@app.command()
def jobs(host: HostOpt = None) -> None:
    """List active ralphkit jobs."""
    from ralphkit.ui import print_jobs_table

    if host:
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
    if host:
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
    if host:
        from ralphkit.remote import cancel_job

        cancel_job(host, job_id)
    else:
        from ralphkit.local import cancel_local

        cancel_local(job_id)

    console.print(f"  [success]Cancelled[/] {job_id}")


# -- attach command --


@app.command()
def attach(
    job_id: Annotated[str, typer.Argument(help="Job ID")],
    host: HostOpt = None,
) -> None:
    """Attach to a job's tmux session."""
    _do_attach(job_id, host)


# -- Entry point --


def main() -> None:
    app()
