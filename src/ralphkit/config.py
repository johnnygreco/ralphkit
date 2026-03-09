from dataclasses import dataclass, field
from pathlib import Path

import yaml

STATE_DIR = ".ralphkit"

DEFAULT_MAX_ITERATIONS = 10
DEFAULT_MODEL = "opus"


def _default_cleanup() -> list["StepConfig"]:
    from ralphkit.prompts import DEFAULT_CLEANUP_SYSTEM_PROMPT, DEFAULT_CLEANUP_TASK_PROMPT

    return [
        StepConfig(
            step_name="review",
            task_prompt=DEFAULT_CLEANUP_TASK_PROMPT,
            system_prompt=DEFAULT_CLEANUP_SYSTEM_PROMPT,
        ),
    ]


def _default_loop() -> list["StepConfig"]:
    from ralphkit.prompts import DEFAULT_WORKER_SYSTEM_PROMPT, DEFAULT_WORKER_TASK_PROMPT

    return [
        StepConfig(
            step_name="worker",
            task_prompt=DEFAULT_WORKER_TASK_PROMPT,
            system_prompt=DEFAULT_WORKER_SYSTEM_PROMPT,
        ),
    ]


@dataclass
class StepConfig:
    step_name: str
    task_prompt: str
    system_prompt: str
    model: str | None = None  # falls back to default_model
    handoff_prompt: str | None = None  # per-step override (pipe only)


@dataclass
class RalphConfig:
    max_iterations: int
    default_model: str
    state_dir: str
    loop: list[StepConfig]
    setup: list[StepConfig] = field(default_factory=list)
    cleanup: list[StepConfig] = field(default_factory=list)
    pipe: list[StepConfig] = field(default_factory=list)
    handoff_prompt: str | None = None  # config-level handoff override (pipe only)
    plan_model: str | None = None


def resolve_model(step: StepConfig, default: str) -> str:
    return step.model if step.model is not None else default


def _parse_steps(raw: list[dict], section: str) -> list[StepConfig]:
    steps = []
    for i, entry in enumerate(raw):
        for key in ("step_name", "task_prompt", "system_prompt"):
            if key not in entry:
                raise ValueError(f"{section}[{i}] is missing required field '{key}'")
        steps.append(
            StepConfig(
                step_name=entry["step_name"],
                task_prompt=entry["task_prompt"],
                system_prompt=entry["system_prompt"],
                model=entry.get("model"),
                handoff_prompt=entry.get("handoff_prompt"),
            )
        )
    return steps


def load_config(path: str | Path | None = None) -> RalphConfig:
    """Load config from a YAML file, or return defaults if no path given."""
    if path is None:
        return RalphConfig(
            max_iterations=DEFAULT_MAX_ITERATIONS,
            default_model=DEFAULT_MODEL,
            state_dir=STATE_DIR,
            loop=_default_loop(),
            cleanup=_default_cleanup(),
        )

    path = Path(path)
    with open(path) as f:
        data = yaml.safe_load(f) or {}

    valid_keys = {
        "max_iterations",
        "default_model",
        "state_dir",
        "loop",
        "setup",
        "cleanup",
        "pipe",
        "handoff_prompt",
        "plan_model",
    }
    unknown = set(data) - valid_keys
    if unknown:
        from ralphkit.ui import err_console

        err_console.print(
            f"[warning]Warning: unknown config keys ignored: {', '.join(sorted(unknown))}[/]"
        )

    try:
        max_iterations = int(data.get("max_iterations", DEFAULT_MAX_ITERATIONS))
    except (ValueError, TypeError) as e:
        raise ValueError(f"max_iterations must be an integer: {e}") from e
    if max_iterations < 1:
        raise ValueError(f"max_iterations must be >= 1, got {max_iterations}")

    default_model = data.get("default_model", DEFAULT_MODEL)
    state_dir = data.get("state_dir", STATE_DIR)
    plan_model = data.get("plan_model")

    # ── Pipe vs loop mutual exclusivity ──────────────────────────
    has_pipe = "pipe" in data
    has_loop = "loop" in data

    if has_pipe and has_loop:
        raise ValueError("config cannot have both 'pipe' and 'loop' sections")

    if has_pipe and ("setup" in data or "cleanup" in data):
        raise ValueError("pipe configs cannot have 'setup' or 'cleanup' sections")

    # ── Parse pipe or loop ─────────────────────────────────────
    if has_pipe:
        pipe_steps = _parse_steps(data["pipe"], "pipe")
        if not pipe_steps:
            raise ValueError("pipe must have at least 1 step")
        loop_steps = _default_loop()
        setup_steps: list[StepConfig] = []
        cleanup_steps: list[StepConfig] = []
    else:
        pipe_steps: list[StepConfig] = []
        if has_loop:
            loop_steps = _parse_steps(data["loop"], "loop")
            if not loop_steps:
                raise ValueError("loop must have at least 1 step")
        else:
            loop_steps = _default_loop()
        setup_steps = _parse_steps(data.get("setup", []), "setup")
        cleanup_steps = _parse_steps(data.get("cleanup", []), "cleanup")
        if "cleanup" not in data:
            cleanup_steps = _default_cleanup()

    handoff_prompt = data.get("handoff_prompt")

    return RalphConfig(
        max_iterations=max_iterations,
        default_model=default_model,
        state_dir=state_dir,
        loop=loop_steps,
        setup=setup_steps,
        cleanup=cleanup_steps,
        pipe=pipe_steps,
        handoff_prompt=handoff_prompt,
        plan_model=plan_model,
    )
