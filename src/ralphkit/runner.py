import os
import subprocess

TIMEOUT_SECONDS = 900  # 15 minutes


def run_claude(prompt: str, model: str, system_prompt: str) -> None:
    env = {**os.environ, "CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1"}
    try:
        subprocess.run(
            [
                "claude",
                "-p",
                prompt,
                "--model",
                model,
                "--append-system-prompt",
                system_prompt,
                "--dangerously-skip-permissions",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=env,
            timeout=TIMEOUT_SECONDS,
            check=True,
        )
    except FileNotFoundError:
        raise RuntimeError("'claude' command not found. Is Claude Code CLI installed?")
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"claude process timed out after {TIMEOUT_SECONDS}s.")
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"claude exited with code {e.returncode}.")
