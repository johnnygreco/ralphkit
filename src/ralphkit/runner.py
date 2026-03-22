import json
import os
import signal
import subprocess
import time
from pathlib import Path

TIMEOUT_SECONDS = 1800  # 30 minutes
TAIL_LIMIT = 16_384
POLL_SECONDS = 1.0
TERMINATE_GRACE_SECONDS = 5.0


class ClaudeRunError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        kind: str,
        elapsed_s: float,
        timeout_seconds: int | None = None,
        idle_timeout_seconds: int | None = None,
        stdout_tail: str = "",
        stderr_tail: str = "",
        transcript_path: str | None = None,
        returncode: int | None = None,
    ) -> None:
        super().__init__(message)
        self.kind = kind
        self.elapsed_s = elapsed_s
        self.timeout_seconds = timeout_seconds
        self.idle_timeout_seconds = idle_timeout_seconds
        self.stdout_tail = stdout_tail
        self.stderr_tail = stderr_tail
        self.transcript_path = transcript_path
        self.returncode = returncode

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "message": str(self),
            "elapsed_s": self.elapsed_s,
            "timeout_seconds": self.timeout_seconds,
            "idle_timeout_seconds": self.idle_timeout_seconds,
            "stdout_tail": self.stdout_tail,
            "stderr_tail": self.stderr_tail,
            "transcript_path": self.transcript_path,
            "returncode": self.returncode,
        }


def _tail_text(text: str | None) -> str:
    if not text:
        return ""
    if len(text) <= TAIL_LIMIT:
        return text
    return text[-TAIL_LIMIT:]


def _claude_project_dir(cwd: str | Path | None) -> Path:
    resolved = Path(cwd or os.getcwd()).expanduser().resolve()
    parts = [part for part in resolved.parts if part not in (os.sep, "")]
    slug = "-" + "-".join(parts) if parts else "-"
    return Path.home() / ".claude" / "projects" / slug


def _latest_transcript(
    project_dir: Path, started_at_wall_s: float
) -> tuple[str | None, float | None]:
    try:
        entries = [
            entry
            for entry in project_dir.iterdir()
            if entry.is_file()
            and entry.suffix == ".jsonl"
            and entry.stat().st_mtime >= started_at_wall_s - 1.0
        ]
    except FileNotFoundError:
        return None, None
    except OSError:
        return None, None
    if not entries:
        return None, None
    newest = max(entries, key=lambda entry: entry.stat().st_mtime)
    return str(newest), newest.stat().st_mtime


def _stop_process(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    try:
        proc.send_signal(signal.SIGTERM)
    except OSError:
        return
    try:
        proc.wait(timeout=TERMINATE_GRACE_SECONDS)
        return
    except subprocess.TimeoutExpired:
        pass
    try:
        proc.kill()
    except OSError:
        return
    try:
        proc.wait(timeout=TERMINATE_GRACE_SECONDS)
    except subprocess.TimeoutExpired:
        pass


def run_claude(
    prompt: str,
    model: str,
    system_prompt: str,
    *,
    timeout_seconds: int = TIMEOUT_SECONDS,
    idle_timeout_seconds: int | None = None,
    cwd: str | Path | None = None,
) -> dict | None:
    env = {**os.environ, "CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1"}
    start_monotonic = time.monotonic()
    started_at_wall_s = time.time()
    project_dir = _claude_project_dir(cwd)
    transcript_path: str | None = None
    transcript_mtime: float | None = None
    last_progress = start_monotonic
    last_output_size = 0
    stdout_data = ""
    stderr_data = ""

    try:
        proc = subprocess.Popen(
            [
                "claude",
                "-p",
                prompt,
                "--model",
                model,
                "--append-system-prompt",
                system_prompt,
                "--dangerously-skip-permissions",
                "--output-format",
                "json",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            cwd=str(cwd) if cwd is not None else None,
        )
    except FileNotFoundError as e:
        raise ClaudeRunError(
            "'claude' command not found. Is Claude Code CLI installed?",
            kind="not_found",
            elapsed_s=0.0,
        ) from e

    while True:
        try:
            stdout_data, stderr_data = proc.communicate(timeout=POLL_SECONDS)
            break
        except subprocess.TimeoutExpired as e:
            if e.output is not None:
                stdout_data = e.output
            if e.stderr is not None:
                stderr_data = e.stderr

            now = time.monotonic()
            transcript_candidate, transcript_candidate_mtime = _latest_transcript(
                project_dir, started_at_wall_s
            )
            if transcript_candidate:
                transcript_path = transcript_candidate
                if transcript_candidate_mtime != transcript_mtime:
                    transcript_mtime = transcript_candidate_mtime
                    last_progress = now

            output_size = len(stdout_data) + len(stderr_data)
            if output_size != last_output_size:
                last_output_size = output_size
                last_progress = now

            elapsed_s = now - start_monotonic
            if elapsed_s >= timeout_seconds:
                _stop_process(proc)
                raise ClaudeRunError(
                    f"claude process timed out after {timeout_seconds}s.",
                    kind="hard_timeout",
                    elapsed_s=elapsed_s,
                    timeout_seconds=timeout_seconds,
                    idle_timeout_seconds=idle_timeout_seconds,
                    stdout_tail=_tail_text(stdout_data),
                    stderr_tail=_tail_text(stderr_data),
                    transcript_path=transcript_path,
                )
            if (
                idle_timeout_seconds is not None
                and now - last_progress >= idle_timeout_seconds
            ):
                _stop_process(proc)
                raise ClaudeRunError(
                    f"claude process hit idle timeout after {idle_timeout_seconds}s.",
                    kind="idle_timeout",
                    elapsed_s=elapsed_s,
                    timeout_seconds=timeout_seconds,
                    idle_timeout_seconds=idle_timeout_seconds,
                    stdout_tail=_tail_text(stdout_data),
                    stderr_tail=_tail_text(stderr_data),
                    transcript_path=transcript_path,
                )

    elapsed_s = time.monotonic() - start_monotonic
    transcript_candidate, _ = _latest_transcript(project_dir, started_at_wall_s)
    if transcript_candidate:
        transcript_path = transcript_candidate

    if proc.returncode != 0:
        raise ClaudeRunError(
            f"claude exited with code {proc.returncode}.",
            kind="process_error",
            elapsed_s=elapsed_s,
            timeout_seconds=timeout_seconds,
            idle_timeout_seconds=idle_timeout_seconds,
            stdout_tail=_tail_text(stdout_data),
            stderr_tail=_tail_text(stderr_data),
            transcript_path=transcript_path,
            returncode=proc.returncode,
        )

    try:
        parsed = json.loads(stdout_data)
    except (json.JSONDecodeError, TypeError) as e:
        raise ClaudeRunError(
            "claude exited successfully but did not emit valid JSON.",
            kind="invalid_json_output",
            elapsed_s=elapsed_s,
            timeout_seconds=timeout_seconds,
            idle_timeout_seconds=idle_timeout_seconds,
            stdout_tail=_tail_text(stdout_data),
            stderr_tail=_tail_text(stderr_data),
            transcript_path=transcript_path,
        ) from e
    if isinstance(parsed, dict) and transcript_path:
        parsed["_ralphkit_transcript_path"] = transcript_path
    return parsed
