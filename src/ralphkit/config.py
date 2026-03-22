from dataclasses import dataclass, field
from pathlib import Path

import yaml

STATE_DIR = ".ralphkit"

DEFAULT_MAX_ITERATIONS = 10
DEFAULT_MODEL = "opus"
DEFAULT_TIMEOUT_SECONDS = 1800
DEFAULT_CLEANUP_ON_ERROR = "light"
DEFAULT_ISOLATION = "shared"


def _default_cleanup() -> list["StepConfig"]:
    from ralphkit.prompts import (
        DEFAULT_CLEANUP_SYSTEM_PROMPT,
        DEFAULT_CLEANUP_TASK_PROMPT,
    )

    return [
        StepConfig(
            step_name="review",
            task_prompt=DEFAULT_CLEANUP_TASK_PROMPT,
            system_prompt=DEFAULT_CLEANUP_SYSTEM_PROMPT,
        ),
    ]


def _default_loop() -> list["StepConfig"]:
    from ralphkit.prompts import (
        DEFAULT_WORKER_SYSTEM_PROMPT,
        DEFAULT_WORKER_TASK_PROMPT,
    )

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
    timeout_seconds: int | None = None
    idle_timeout_seconds: int | None = None


@dataclass
class RalphConfig:
    max_iterations: int
    default_model: str
    state_dir: str
    loop: list[StepConfig]
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS
    idle_timeout_seconds: int | None = None
    cleanup_on_error: str = DEFAULT_CLEANUP_ON_ERROR
    isolation: str = DEFAULT_ISOLATION
    setup: list[StepConfig] = field(default_factory=list)
    cleanup: list[StepConfig] = field(default_factory=list)
    pipe: list[StepConfig] = field(default_factory=list)
    plan_model: str | None = None
    max_cost: float | None = None
    max_duration_seconds: int | None = None
    completion_consensus: int = 2
    verify_command: str | None = None
    verify_timeout: int = 300


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
                timeout_seconds=_parse_positive_int(
                    entry.get("timeout_seconds"), f"{section}[{i}].timeout_seconds"
                ),
                idle_timeout_seconds=_parse_positive_int(
                    entry.get("idle_timeout_seconds"),
                    f"{section}[{i}].idle_timeout_seconds",
                ),
            )
        )
    return steps


def _parse_positive_int(value, field_name: str) -> int | None:
    if value is None:
        return None
    try:
        parsed = int(value)
    except (ValueError, TypeError) as e:
        raise ValueError(f"{field_name} must be an integer: {e}") from e
    if parsed < 1:
        raise ValueError(f"{field_name} must be >= 1, got {parsed}")
    return parsed


def _parse_choice(value, field_name: str, choices: set[str], default: str) -> str:
    raw = value if value is not None else default
    parsed = str(raw)
    if parsed not in choices:
        allowed = ", ".join(sorted(choices))
        raise ValueError(f"{field_name} must be one of: {allowed}")
    return parsed


def load_config(path: str | Path | None = None) -> RalphConfig:
    """Load config from a YAML file, or return defaults if no path given."""
    if path is None:
        return RalphConfig(
            max_iterations=DEFAULT_MAX_ITERATIONS,
            default_model=DEFAULT_MODEL,
            state_dir=STATE_DIR,
            loop=_default_loop(),
            timeout_seconds=DEFAULT_TIMEOUT_SECONDS,
            cleanup_on_error=DEFAULT_CLEANUP_ON_ERROR,
            isolation=DEFAULT_ISOLATION,
            cleanup=_default_cleanup(),
        )

    path = Path(path)
    with open(path) as f:
        data = yaml.safe_load(f) or {}

    valid_keys = {
        "max_iterations",
        "default_model",
        "state_dir",
        "timeout_seconds",
        "idle_timeout_seconds",
        "cleanup_on_error",
        "isolation",
        "loop",
        "setup",
        "cleanup",
        "pipe",
        "plan_model",
        "max_cost",
        "max_duration_seconds",
        "completion_consensus",
        "verify_command",
        "verify_timeout",
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
    timeout_seconds = _parse_positive_int(
        data.get("timeout_seconds", DEFAULT_TIMEOUT_SECONDS), "timeout_seconds"
    )
    idle_timeout_seconds = _parse_positive_int(
        data.get("idle_timeout_seconds"), "idle_timeout_seconds"
    )
    cleanup_on_error = _parse_choice(
        data.get("cleanup_on_error"),
        "cleanup_on_error",
        {"full", "light", "skip"},
        DEFAULT_CLEANUP_ON_ERROR,
    )
    isolation = _parse_choice(
        data.get("isolation"),
        "isolation",
        {"shared", "worktree"},
        DEFAULT_ISOLATION,
    )
    plan_model = data.get("plan_model")

    max_cost = None
    if "max_cost" in data:
        try:
            max_cost = float(data["max_cost"])
        except (ValueError, TypeError) as e:
            raise ValueError(f"max_cost must be a number: {e}") from e
        if max_cost <= 0:
            raise ValueError(f"max_cost must be > 0, got {max_cost}")

    max_duration_seconds = _parse_positive_int(
        data.get("max_duration_seconds"), "max_duration_seconds"
    )

    completion_consensus = 2
    if "completion_consensus" in data:
        completion_consensus = (
            _parse_positive_int(data["completion_consensus"], "completion_consensus")
            or 2
        )

    verify_command = data.get("verify_command")
    verify_timeout = (
        _parse_positive_int(data.get("verify_timeout", 300), "verify_timeout") or 300
    )

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

    return RalphConfig(
        max_iterations=max_iterations,
        default_model=default_model,
        state_dir=state_dir,
        loop=loop_steps,
        timeout_seconds=timeout_seconds or DEFAULT_TIMEOUT_SECONDS,
        idle_timeout_seconds=idle_timeout_seconds,
        cleanup_on_error=cleanup_on_error,
        isolation=isolation,
        setup=setup_steps,
        cleanup=cleanup_steps,
        pipe=pipe_steps,
        plan_model=plan_model,
        max_cost=max_cost,
        max_duration_seconds=max_duration_seconds,
        completion_consensus=completion_consensus,
        verify_command=verify_command,
        verify_timeout=verify_timeout,
    )
