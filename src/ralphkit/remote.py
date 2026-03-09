import re
import shlex
import subprocess

from ralphkit.tmux import (
    LOGS_DIR_SHELL,
    TMUX_LIST_FORMAT,
    build_job_script,
    parse_session_list,
)


def _ssh_run(
    host: str,
    cmd: str,
    *,
    check: bool = True,
    capture: bool = True,
    input: str | None = None,
    login_shell: bool = False,
) -> subprocess.CompletedProcess:
    """Run a command on the remote host via SSH."""
    remote_cmd = cmd
    if login_shell:
        # Wrap in login shell so PATH includes homebrew etc. on macOS
        remote_cmd = f"exec $SHELL -lc {shlex.quote(cmd)}"
    ssh_args = ["ssh", "-o", "ConnectTimeout=10", host, remote_cmd]
    try:
        return subprocess.run(
            ssh_args,
            capture_output=capture,
            text=True,
            check=check,
            input=input,
        )
    except subprocess.CalledProcessError as e:
        if e.returncode == 255:
            detail = ""
            if e.stderr and e.stderr.strip():
                detail = e.stderr.strip().splitlines()[-1]
            msg = f"SSH connection to '{host}' failed."
            if detail:
                msg += f"\n  {detail}"
            msg += f"\n  Verify with: ssh {host}"
            raise SystemExit(msg)
        raise


def _is_prerelease(version: str) -> bool:
    """Check if a version string contains pre-release identifiers."""
    return bool(re.search(r"(a|b|rc|dev|alpha|beta)\d*", version))


def _ralph_cmd(
    ralph_args: list[str],
    ralph_version: str | None = None,
) -> str:
    """Build the uvx ralphkit command string."""
    pkg = f"ralphkit=={ralph_version}" if ralph_version else "ralphkit@latest"
    parts = ["uvx", "--refresh", "--from", shlex.quote(pkg)]
    if ralph_version and _is_prerelease(ralph_version):
        parts += ["--prerelease", "allow"]
    parts += ["ralphkit", "run"]
    return " ".join(parts) + " " + shlex.join(ralph_args)


def submit_job(
    host: str,
    job_id: str,
    ralph_args: list[str],
    working_dir: str | None = None,
    ralph_version: str | None = None,
    config_content: str | None = None,
) -> None:
    """Submit a ralphkit job to a remote host via SSH + tmux."""
    # Pre-flight: tmux available?
    result = _ssh_run(host, "command -v tmux", check=False, login_shell=True)
    if result.returncode != 0:
        raise SystemExit(
            f"tmux is not installed on '{host}'.\n"
            f"  Install: ssh {host} 'brew install tmux'"
        )

    # Pre-flight: working dir exists?
    if working_dir:
        result = _ssh_run(host, f"test -d {shlex.quote(working_dir)}", check=False)
        if result.returncode != 0:
            raise SystemExit(
                f"Working directory does not exist on '{host}': {working_dir}"
            )

    # Upload config file if provided
    if config_content is not None:
        config_path = f"{LOGS_DIR_SHELL}/{job_id}.config.yaml"
        _ssh_run(
            host,
            f"mkdir -p {LOGS_DIR_SHELL} && cat > {config_path}",
            input=config_content,
        )
        ralph_args = ralph_args + ["--config", config_path]

    # Generate job script
    ralph_cmd = _ralph_cmd(ralph_args, ralph_version)
    script = build_job_script(
        job_id,
        ralph_cmd,
        working_dir=working_dir,
    )

    # Upload script via ssh stdin pipe
    script_path = f"{LOGS_DIR_SHELL}/{job_id}.sh"
    _ssh_run(
        host,
        f"mkdir -p {LOGS_DIR_SHELL} && cat > {script_path} && chmod +x {script_path}",
        input=script,
    )

    # Launch in tmux
    _ssh_run(
        host,
        f"tmux new-session -d -s {job_id} {script_path} \\; set-option -t {job_id} remain-on-exit on",
        login_shell=True,
    )


def list_jobs(host: str) -> list[dict]:
    """List active ralphkit jobs on a remote host."""
    result = _ssh_run(
        host,
        f"tmux list-sessions -F '{TMUX_LIST_FORMAT}' 2>/dev/null || true",
        check=False,
        login_shell=True,
    )
    return parse_session_list(result.stdout or "")


def tail_logs(host: str, job_id: str, follow: bool = False) -> None:
    """Tail a remote job's log file. Streams to stdout."""
    log_file = f"{LOGS_DIR_SHELL}/{job_id}.log"
    flag = "-f" if follow else "-100"
    subprocess.run(
        [
            "ssh",
            "-t",
            "-o",
            "ConnectTimeout=10",
            host,
            f'tail {flag} "{log_file}"',
        ],
    )


def cancel_job(host: str, job_id: str) -> None:
    result = _ssh_run(
        host, f"tmux kill-session -t {job_id}", check=False, login_shell=True
    )
    if result.returncode != 0:
        raise SystemExit(
            f"No job '{job_id}' found on '{host}'.\n"
            f"  Run 'ralphkit jobs --host {host}' to list active jobs."
        )
