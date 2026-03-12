import json
import shlex
import shutil
import subprocess
from datetime import datetime

from ralphkit.tmux import (
    build_submission_metadata,
    build_job_script,
    job_path_local,
    parse_session_list,
    log_path_local,
    meta_path_local,
    script_path_local,
    TMUX_LIST_FORMAT,
)


def _check_tmux() -> None:
    """Verify tmux is installed."""
    if not shutil.which("tmux"):
        raise SystemExit(
            "tmux is required for job submission.\n  Install: brew install tmux"
        )


def submit_local(
    job_id: str,
    ralph_args: list[str],
    subcommand: str,
    working_dir: str | None = None,
    isolation: str | None = None,
) -> None:
    """Launch a ralphkit job in a local detached tmux session."""
    _check_tmux()

    ralph_cmd = f"ralphkit {subcommand} " + shlex.join(ralph_args)
    script = build_job_script(job_id, ralph_cmd, working_dir, isolation=isolation)
    script_file = script_path_local(job_id)
    meta_file = meta_path_local(job_id)
    job_dir = job_path_local(job_id)
    script_file.parent.mkdir(parents=True, exist_ok=True)
    job_dir.mkdir(parents=True, exist_ok=True)
    script_file.write_text(script)
    script_file.chmod(0o700)
    meta_file.write_text(
        json.dumps(
            build_submission_metadata(
                job_id=job_id,
                subcommand=subcommand,
                ralph_args=ralph_args,
                working_dir=working_dir,
                isolation=isolation,
                scratch_dir=str(job_dir),
            )
            | {
                "submitted_at": datetime.now().isoformat(),
            },
            indent=2,
        )
        + "\n"
    )

    subprocess.run(
        [
            "tmux",
            "new-session",
            "-d",
            "-s",
            job_id,
            str(script_file),
            ";",
            "set-option",
            "-t",
            job_id,
            "remain-on-exit",
            "on",
        ],
        check=True,
    )


def list_local_jobs() -> list[dict]:
    """List local ralphkit tmux sessions with status info."""
    result = subprocess.run(
        ["tmux", "list-sessions", "-F", TMUX_LIST_FORMAT],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return []
    return parse_session_list(result.stdout)


def tail_local_logs(job_id: str, follow: bool = False) -> None:
    """Tail a local job's log file."""
    log_file = log_path_local(job_id)
    if not log_file.exists():
        raise SystemExit(f"No log file for job '{job_id}'.\n  Expected: {log_file}")
    flag = "-f" if follow else "-100"
    subprocess.run(["tail", flag, str(log_file)])


def cancel_local(job_id: str) -> None:
    """Kill a local tmux session."""
    result = subprocess.run(
        ["tmux", "kill-session", "-t", job_id],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise SystemExit(
            f"No job '{job_id}' found.\n  Run 'ralphkit jobs' to list active jobs."
        )
