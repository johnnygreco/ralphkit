import shlex
from pathlib import Path

from ralphkit.jobs import JOB_ID_PREFIX

# For shell commands (scripts), use $HOME for portability across local/remote.
# For Python-level file access, use Path.home().
LOGS_DIR_SHELL = "$HOME/.local/share/ralphkit/logs"
LOGS_DIR_LOCAL = Path.home() / ".local" / "share" / "ralphkit" / "logs"
JOBS_DIR_SHELL = "$HOME/.local/share/ralphkit/jobs"
JOBS_DIR_LOCAL = Path.home() / ".local" / "share" / "ralphkit" / "jobs"


def log_path_local(job_id: str) -> Path:
    """Local Python path to a job's log file."""
    return LOGS_DIR_LOCAL / f"{job_id}.log"


def script_path_local(job_id: str) -> Path:
    """Local Python path to a job's script file."""
    return LOGS_DIR_LOCAL / f"{job_id}.sh"


def meta_path_local(job_id: str) -> Path:
    """Local Python path to a job's metadata file."""
    return LOGS_DIR_LOCAL / f"{job_id}.meta.json"


def current_version() -> str | None:
    """Best-effort version for the currently running ralphkit CLI."""
    try:
        from ralphkit._version import version
    except Exception:
        return None
    return version or None


def job_path_local(job_id: str) -> Path:
    """Local Python path to a job scratch directory."""
    return JOBS_DIR_LOCAL / job_id


def _arg_value(args: list[str], flag: str) -> str | None:
    try:
        idx = args.index(flag)
    except ValueError:
        return None
    next_idx = idx + 1
    if next_idx >= len(args):
        return None
    return args[next_idx]


def _arg_int_value(args: list[str], flag: str) -> int | None:
    value = _arg_value(args, flag)
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def build_submission_metadata(
    *,
    job_id: str,
    subcommand: str,
    ralph_args: list[str],
    working_dir: str | None,
    isolation: str | None,
    scratch_dir: str,
    package_spec: str | None = None,
    caller_version: str | None = None,
) -> dict:
    return {
        "job_id": job_id,
        "subcommand": subcommand,
        "args": ralph_args,
        "working_dir": working_dir,
        "isolation": isolation or "shared",
        "scratch_dir": scratch_dir,
        "state_dir": _arg_value(ralph_args, "--state-dir"),
        "config_path": _arg_value(ralph_args, "--config"),
        "plan_path": _arg_value(ralph_args, "--plan"),
        "timeout_seconds": _arg_int_value(ralph_args, "--timeout-seconds"),
        "idle_timeout_seconds": _arg_int_value(ralph_args, "--idle-timeout-seconds"),
        "cleanup_on_error": _arg_value(ralph_args, "--cleanup-on-error"),
        "resume_run": _arg_value(ralph_args, "--resume-run"),
        "package_spec": package_spec,
        "caller_version": caller_version,
    }


def build_job_script(
    job_id: str,
    ralph_cmd: str,
    working_dir: str | None = None,
    isolation: str | None = None,
    *,
    package_spec: str | None = None,
    caller_version: str | None = None,
) -> str:
    """Generate a bash script for a ralphkit job."""
    lines = [
        "#!/usr/bin/env bash",
        "set -uo pipefail",
        "",
        "# Ensure common tool locations are in PATH (tmux may not inherit login PATH)",
        'export PATH="$HOME/.local/bin:$HOME/.cargo/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"',
        "export FORCE_COLOR=1",  # Rich respects this even through tee/tmux
        "export CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1",
        "",
        f'LOG_DIR="{LOGS_DIR_SHELL}"',
        f'LOG_FILE="$LOG_DIR/{job_id}.log"',
        f'JOB_DIR="{JOBS_DIR_SHELL}/{job_id}"',
        'TMP_DIR="$JOB_DIR/tmp"',
        'mkdir -p "$LOG_DIR" "$JOB_DIR" "$TMP_DIR"',
        f'export RALPHKIT_JOB_ID="{job_id}"',
        'export RALPHKIT_SCRATCH_DIR="$JOB_DIR"',
        'export TMPDIR="$TMP_DIR"',
    ]
    if working_dir:
        lines.append(f"ORIG_DIR={shlex.quote(working_dir)}")
    else:
        lines.append('ORIG_DIR="$PWD"')
    if isolation == "worktree":
        lines += [
            'WORKTREE_DIR="$JOB_DIR/worktree"',
            'git -C "$ORIG_DIR" rev-parse --is-inside-work-tree >/dev/null 2>&1 || { echo "[ralphkit] isolation=worktree requires a git repo" >> "$LOG_FILE"; exit 1; }',
            'git -C "$ORIG_DIR" worktree add --force --detach "$WORKTREE_DIR" HEAD >/dev/null 2>&1 || { echo "[ralphkit] failed to create worktree" >> "$LOG_FILE"; exit 1; }',
            'export RALPHKIT_WORKING_DIR="$WORKTREE_DIR"',
            'cd "$WORKTREE_DIR" || exit 1',
        ]
    else:
        lines += [
            'export RALPHKIT_WORKING_DIR="$ORIG_DIR"',
            'cd "$ORIG_DIR" || exit 1',
        ]
    lines.append('echo "[ralphkit] started_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "$LOG_FILE"')
    if package_spec:
        lines.append(
            f"echo {shlex.quote(f'[ralphkit] package={package_spec}')} >> \"$LOG_FILE\""
        )
    if caller_version:
        lines.append(
            f"echo {shlex.quote(f'[ralphkit] caller_version={caller_version}')} >> \"$LOG_FILE\""
        )
    lines += [
        'echo "[ralphkit] scratch_dir=$JOB_DIR" >> "$LOG_FILE"',
        'echo "[ralphkit] working_dir=$PWD" >> "$LOG_FILE"',
        "",
        f'{ralph_cmd} 2>&1 | tee -a "$LOG_FILE"',
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
