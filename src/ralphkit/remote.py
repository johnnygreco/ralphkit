import json
import re
import shlex
import subprocess
from datetime import datetime

from ralphkit.tmux import (
    LOGS_DIR_SHELL,
    TMUX_LIST_FORMAT,
    build_submission_metadata,
    build_job_script,
    current_version,
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


def _resolve_ralph_version(ralph_version: str | None) -> str | None:
    if ralph_version in (None, "", "latest"):
        return None
    if ralph_version == "current":
        resolved = current_version()
        if not resolved:
            raise SystemExit("Could not determine the current ralphkit version.")
        return resolved
    return ralph_version


def _package_spec(ralph_version: str | None) -> str:
    resolved = _resolve_ralph_version(ralph_version)
    return f"ralphkit=={resolved}" if resolved else "ralphkit@latest"


def _ralph_cmd(
    ralph_args: list[str],
    ralph_version: str | None = None,
    *,
    subcommand: str,
) -> str:
    """Build the uvx ralphkit command string."""
    resolved_version = _resolve_ralph_version(ralph_version)
    pkg = f"ralphkit=={resolved_version}" if resolved_version else "ralphkit@latest"
    parts = ["uvx", "--refresh", "--from", shlex.quote(pkg)]
    if resolved_version and _is_prerelease(resolved_version):
        parts += ["--prerelease", "allow"]
    parts += ["ralphkit", subcommand]
    return " ".join(parts) + " " + shlex.join(ralph_args)


def submit_job(
    host: str,
    job_id: str,
    ralph_args: list[str],
    subcommand: str,
    working_dir: str | None = None,
    ralph_version: str | None = None,
    isolation: str | None = None,
    config_content: str | None = None,
    plan_content: str | None = None,
) -> None:
    """Submit a ralphkit job to a remote host via SSH + tmux."""
    caller_version = current_version()
    package_spec = _package_spec(ralph_version)

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

    # Resolve remote home so paths in ralph_args are absolute
    # ($HOME in shlex.join gets single-quoted, preventing shell expansion)
    remote_home = _ssh_run(host, "echo $HOME").stdout.strip()
    logs_dir = f"{remote_home}/.local/share/ralphkit/logs"

    # Ensure logs directory exists (once, before any uploads)
    _ssh_run(host, f"mkdir -p {shlex.quote(logs_dir)}")

    # Upload config file if provided
    if config_content is not None:
        config_path = f"{logs_dir}/{job_id}.config.yaml"
        _ssh_run(
            host,
            f"cat > {shlex.quote(config_path)}",
            input=config_content,
        )
        ralph_args = ralph_args + ["--config", config_path]

    # Upload plan file if provided
    if plan_content is not None:
        plan_path = f"{logs_dir}/{job_id}.tickets.json"
        _ssh_run(
            host,
            f"cat > {shlex.quote(plan_path)}",
            input=plan_content,
        )
        ralph_args = ralph_args + ["--plan", plan_path]

    meta_content = (
        json.dumps(
            build_submission_metadata(
                job_id=job_id,
                subcommand=subcommand,
                ralph_args=ralph_args,
                working_dir=working_dir,
                isolation=isolation,
                scratch_dir=f"{remote_home}/.local/share/ralphkit/jobs/{job_id}",
                package_spec=package_spec,
                caller_version=caller_version,
            )
            | {
                "submitted_at": datetime.now().isoformat(),
            },
            indent=2,
        )
        + "\n"
    )
    meta_path = f"{logs_dir}/{job_id}.meta.json"
    _ssh_run(
        host,
        f"cat > {shlex.quote(meta_path)}",
        input=meta_content,
    )

    # Generate job script
    ralph_cmd = _ralph_cmd(ralph_args, ralph_version, subcommand=subcommand)
    script = build_job_script(
        job_id,
        ralph_cmd,
        working_dir=working_dir,
        isolation=isolation,
        package_spec=package_spec,
        caller_version=caller_version,
    )

    # Upload script via ssh stdin pipe
    script_path = f"{LOGS_DIR_SHELL}/{job_id}.sh"
    _ssh_run(
        host,
        f"cat > {script_path} && chmod +x {script_path}",
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
