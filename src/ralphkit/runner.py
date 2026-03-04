import subprocess


def run_claude(prompt: str, model: str, system_prompt: str) -> None:
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
        check=True,
    )
