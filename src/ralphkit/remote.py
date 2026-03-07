import shlex
import subprocess

from ralphkit.hosts import HostConfig
from ralphkit.tmux import (
    LOGS_DIR_SHELL,
    TMUX_LIST_FORMAT,
    build_job_script,
    parse_session_list,
)


def _ssh_target(host: HostConfig) -> str:
    return f"{host.user}@{host.hostname}" if host.user else host.hostname


def _ssh_run(
    host: HostConfig,
    cmd: str,
    *,
    check: bool = True,
    capture: bool = True,
    input: str | None = None,
) -> subprocess.CompletedProcess:
    """Run a command on the remote host via SSH."""
    ssh_args = ["ssh", _ssh_target(host), cmd]
    try:
        return subprocess.run(
            ssh_args,
            capture_output=capture,
            text=True,
            check=check,
            input=input,
        )
    except subprocess.CalledProcessError as e:
        if "Connection refused" in (e.stderr or "") or e.returncode == 255:
            raise SystemExit(
                f"SSH connection to '{host.hostname}' failed.\n"
                f"  Verify with: ssh {_ssh_target(host)}"
            )
        raise


def submit_job(
    host: HostConfig, job_id: str, ralph_args: list[str]
) -> None:
    """Submit a ralph job to a remote host via SSH + tmux."""
    target = _ssh_target(host)

    # Pre-flight: tmux available?
    result = _ssh_run(host, "command -v tmux", check=False)
    if result.returncode != 0:
        raise SystemExit(
            f"tmux is not installed on '{host.hostname}'.\n"
            f"  Install: ssh {target} 'brew install tmux'"
        )

    # Pre-flight: working dir exists?
    if host.working_dir:
        result = _ssh_run(
            host, f"test -d {shlex.quote(host.working_dir)}", check=False
        )
        if result.returncode != 0:
            raise SystemExit(
                f"Working directory does not exist on '{host.hostname}': "
                f"{host.working_dir}"
            )

    # Generate job script
    ralph_cmd = shlex.quote(host.ralph_command) + " run " + shlex.join(ralph_args)
    script = build_job_script(
        job_id, ralph_cmd,
        working_dir=host.working_dir,
        env=host.env,
    )

    # Upload script via ssh stdin pipe
    script_path = f"{LOGS_DIR_SHELL}/{job_id}.sh"
    _ssh_run(
        host,
        f"mkdir -p {LOGS_DIR_SHELL} && cat > {script_path} && chmod +x {script_path}",
        input=script,
    )

    # Launch in tmux
    _ssh_run(host, f"tmux new-session -d -s {job_id} {script_path}")
    _ssh_run(host, f"tmux set-option -t {job_id} remain-on-exit on")


def list_jobs(host: HostConfig) -> list[dict]:
    """List active ralphkit jobs on a remote host."""
    result = _ssh_run(
        host,
        f"tmux list-sessions -F '{TMUX_LIST_FORMAT}' 2>/dev/null || true",
        check=False,
    )
    return parse_session_list(result.stdout or "")


def tail_logs(host: HostConfig, job_id: str, follow: bool = False) -> None:
    """Tail a remote job's log file. Streams to stdout."""
    log_file = f"{LOGS_DIR_SHELL}/{job_id}.log"
    flag = "-f" if follow else "-100"
    subprocess.run(
        ["ssh", "-t", _ssh_target(host), f"tail {flag} {shlex.quote(log_file)}"],
    )


def cancel_job(host: HostConfig, job_id: str) -> None:
    result = _ssh_run(host, f"tmux kill-session -t {job_id}", check=False)
    if result.returncode != 0:
        raise SystemExit(
            f"No job '{job_id}' found on '{host.hostname}'.\n"
            f"  Run 'ralph jobs --host {host.name}' to list active jobs."
        )


def get_attach_command(host: HostConfig, job_id: str) -> list[str]:
    """Return the ssh command to attach to a remote tmux session."""
    return ["ssh", "-t", _ssh_target(host), "tmux", "attach", "-t", job_id]
