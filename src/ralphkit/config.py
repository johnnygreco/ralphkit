import sys
from dataclasses import dataclass, field
from pathlib import Path

import yaml

STATE_DIR = ".ralphkit"

VERDICT_SHIP = "SHIP"
VERDICT_REVISE = "REVISE"


@dataclass
class StepConfig:
    step_name: str
    task_prompt: str
    system_prompt: str
    model: str | None = None  # falls back to default_model


@dataclass
class RalphConfig:
    max_iterations: int
    default_model: str
    loop: list[StepConfig]
    setup: list[StepConfig] = field(default_factory=list)
    cleanup: list[StepConfig] = field(default_factory=list)


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
            )
        )
    return steps


def load_config(path: str | Path | None) -> RalphConfig:
    """Load config from a YAML file. path is required."""
    if path is None:
        raise ValueError("A config file is required (use --config)")
    path = Path(path)
    with open(path) as f:
        data = yaml.safe_load(f) or {}

    valid_keys = {
        "max_iterations",
        "default_model",
        "loop",
        "setup",
        "cleanup",
    }
    unknown = set(data) - valid_keys
    if unknown:
        print(
            f"Warning: unknown config keys ignored: {', '.join(sorted(unknown))}",
            file=sys.stderr,
        )

    for key in ("max_iterations", "default_model", "loop"):
        if key not in data:
            raise ValueError(f"Config is missing required key '{key}'")

    max_iterations = int(data["max_iterations"])
    if max_iterations < 1:
        raise ValueError(f"max_iterations must be >= 1, got {max_iterations}")

    loop_steps = _parse_steps(data["loop"], "loop")
    if not loop_steps:
        raise ValueError("loop must have at least 1 step")

    setup_steps = _parse_steps(data.get("setup", []), "setup")
    cleanup_steps = _parse_steps(data.get("cleanup", []), "cleanup")

    return RalphConfig(
        max_iterations=max_iterations,
        default_model=data["default_model"],
        loop=loop_steps,
        setup=setup_steps,
        cleanup=cleanup_steps,
    )
