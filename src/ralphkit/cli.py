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
    typer.Option("--host", "-H", help="Remote host name (from hosts config)"),
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
    force: Annotated[bool, typer.Option("-f", "--force", help="Skip confirmation")] = False,
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
    )


# -- runs command --


@app.command()
def runs(state_dir: StateDirOpt = None) -> None:
    """List past completed runs."""
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
            console.print(f"  [label]#{run_dir.name}[/]  {first_line}")


# -- submit command --


def _build_ralph_args(
    task: str,
    config: Path | None,
    max_iterations: int | None,
    default_model: str | None,
    state_dir: str | None,
) -> list[str]:
    """Build argument list for ralph run."""
    args = [task]
    if config:
        args += ["--config", str(config.resolve())]
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
    hostname: str,
    working_dir: str | None,
) -> None:
    host_flag = f" --host {host}" if host else ""
    console.print()
    console.print(f"  [success]Submitted[/] {job_id}")
    console.print(f"  [dim]Host:[/]    {hostname}")
    if working_dir:
        console.print(f"  [dim]Dir:[/]     {working_dir}")
    console.print(f"  [dim]Attach:[/]  ralph attach {job_id}{host_flag}")
    console.print(f"  [dim]Logs:[/]    ralph logs {job_id}{host_flag}")
    console.print()


def _do_attach(job_id: str, host: str | None) -> None:
    if host:
        from ralphkit.hosts import resolve_host
        from ralphkit.remote import get_attach_command

        cmd = get_attach_command(resolve_host(host), job_id)
    else:
        cmd = ["tmux", "attach", "-t", job_id]
    os.execvp(cmd[0], cmd)


@app.command()
def submit(
    task: Annotated[str, typer.Argument(help="Task description")],
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
) -> None:
    """Submit a task to run in the background (local tmux or remote)."""
    from ralphkit.jobs import make_job_id

    job_id = make_job_id(task)
    ralph_args = _build_ralph_args(task, config, max_iterations, default_model, state_dir)
    ralph_args.append("--force")

    if host:
        from ralphkit.hosts import resolve_host
        from ralphkit.remote import submit_job

        host_cfg = resolve_host(host)
        submit_job(host_cfg, job_id, ralph_args)
        _print_submit_info(
            job_id,
            host=host,
            hostname=host_cfg.hostname,
            working_dir=working_dir or host_cfg.working_dir,
        )
    else:
        from ralphkit.local import submit_local

        submit_local(job_id, ralph_args, working_dir)
        _print_submit_info(job_id, host=None, hostname="localhost", working_dir=working_dir)

    if attach:
        _do_attach(job_id, host)


# -- jobs command --


@app.command()
def jobs(host: HostOpt = None) -> None:
    """List active ralphkit jobs."""
    from ralphkit.ui import print_jobs_table

    if host:
        from ralphkit.hosts import resolve_host
        from ralphkit.remote import list_jobs

        items = list_jobs(resolve_host(host))
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
        from ralphkit.hosts import resolve_host
        from ralphkit.remote import tail_logs

        tail_logs(resolve_host(host), job_id, follow)
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
        from ralphkit.hosts import resolve_host
        from ralphkit.remote import cancel_job

        cancel_job(resolve_host(host), job_id)
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


# -- hosts command --


@app.command()
def hosts() -> None:
    """List configured remote hosts."""
    from ralphkit.hosts import load_hosts_config

    default, host_map = load_hosts_config()
    if not host_map:
        console.print("No hosts configured.")
        console.print("  [dim]Create ~/.config/ralphkit/hosts.yaml[/]")
        return
    for name, cfg in sorted(host_map.items()):
        marker = " [success](default)[/]" if name == default else ""
        user_part = f"{cfg.user}@" if cfg.user else ""
        console.print(f"  [label]{name}[/]{marker}  {user_part}{cfg.hostname}")
        if cfg.working_dir:
            console.print(f"    [dim]dir: {cfg.working_dir}[/]")


# -- Entry point --


def main() -> None:
    app()
