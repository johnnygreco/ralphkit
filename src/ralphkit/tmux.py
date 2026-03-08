import shlex
from pathlib import Path

from ralphkit.jobs import JOB_ID_PREFIX

# For shell commands (scripts), use $HOME for portability across local/remote.
# For Python-level file access, use Path.home().
LOGS_DIR_SHELL = "$HOME/.local/share/ralphkit/logs"
LOGS_DIR_LOCAL = Path.home() / ".local" / "share" / "ralphkit" / "logs"


def log_path_local(job_id: str) -> Path:
    """Local Python path to a job's log file."""
    return LOGS_DIR_LOCAL / f"{job_id}.log"


def script_path_local(job_id: str) -> Path:
    """Local Python path to a job's script file."""
    return LOGS_DIR_LOCAL / f"{job_id}.sh"


def build_job_script(
    job_id: str,
    ralph_cmd: str,
    working_dir: str | None = None,
) -> str:
    """Generate a bash script for a ralph job."""
    lines = [
        "#!/usr/bin/env bash",
        "set -uo pipefail",
        "",
        "# Ensure common tool locations are in PATH (tmux may not inherit login PATH)",
        'export PATH="$HOME/.local/bin:$HOME/.cargo/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"',
        "export FORCE_COLOR=1",  # Rich respects this even through tee/tmux
        "",
        f'LOG_DIR="{LOGS_DIR_SHELL}"',
        f'LOG_FILE="$LOG_DIR/{job_id}.log"',
        'mkdir -p "$LOG_DIR"',
    ]
    if working_dir:
        lines.append(f"cd {shlex.quote(working_dir)} || exit 1")
    lines += [
        "",
        f'{ralph_cmd} 2>&1 | tee "$LOG_FILE"',
        "RC=${PIPESTATUS[0]}",
        'echo "[ralphkit] exit=$RC" >> "$LOG_FILE"',
        "exit $RC",
    ]
    return "\n".join(lines) + "\n"


def parse_session_list(output: str) -> list[dict]:
    """Parse tmux list-sessions output, filtering to rk- sessions."""
    if not output.strip():
        return []
    jobs = []
    for line in output.strip().splitlines():
        parts = line.split("\t")
        if parts and parts[0].startswith(JOB_ID_PREFIX):
            jobs.append(
                {
                    "name": parts[0],
                    "created": parts[1] if len(parts) > 1 else None,
                    "activity": parts[2] if len(parts) > 2 else None,
                    "pane_dead": parts[3] if len(parts) > 3 else None,
                }
            )
    return jobs


TMUX_LIST_FORMAT = (
    "#{session_name}\t#{session_created}\t#{session_activity}\t#{pane_dead}"
)
