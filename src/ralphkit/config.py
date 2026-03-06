import sys
from dataclasses import dataclass, field
from pathlib import Path

import yaml

STATE_DIR = ".ralphkit"

VERDICT_SHIP = "SHIP"
VERDICT_REVISE = "REVISE"

DEFAULT_MAX_ITERATIONS = 10
DEFAULT_MODEL = "opus"

DEFAULT_WORKER_TASK_PROMPT = (
    "Read {state_dir}/task.md and begin working. "
    "This is iteration {iteration} of {max_iterations}."
)
DEFAULT_WORKER_SYSTEM_PROMPT = """\
You are in a RALPH LOOP — an iterative work/review cycle.
Your work persists through FILES ONLY. You will NOT remember previous iterations.

STATE FILES (in {state_dir}/):
- task.md — The task you need to accomplish (READ THIS FIRST)
- iteration.md — Current iteration number
- review-feedback.md — Feedback from last review (if exists)
- work-summary.md — Write a concise summary of what you did each iteration
- work-complete.md — Create this when task is DONE
- RALPH-BLOCKED.md — Create this if you cannot proceed (explain why)

WORKFLOW:
1. Read {state_dir}/task.md to understand your task
2. Read {state_dir}/iteration.md to know which iteration this is
3. If {state_dir}/review-feedback.md exists, address that feedback FIRST
4. Look at existing project files to see prior work
5. Do the work — make meaningful progress each iteration
6. Run tests and verification if applicable
7. Write a concise summary of what you did to {state_dir}/work-summary.md
8. If the task is complete, write "done" to {state_dir}/work-complete.md
9. If you are blocked and cannot make progress, write the reason to {state_dir}/RALPH-BLOCKED.md
"""

DEFAULT_REVIEWER_TASK_PROMPT = (
    "Review the work done for the task in {state_dir}/task.md. "
    "Read the project files, run tests, then write your verdict "
    "to {state_dir}/review-result.md"
)
DEFAULT_REVIEWER_SYSTEM_PROMPT = """\
You are a CODE REVIEWER in a RALPH LOOP.
You are a DIFFERENT agent than the worker. Use your fresh perspective.
This is iteration {iteration} of {max_iterations}.

Your job: review the work and decide SHIP or REVISE.

STATE FILES (in {state_dir}/):
- task.md — The original task description
- work-summary.md — What the worker claims to have done
- work-complete.md — Exists if worker claims task is complete
- RALPH-BLOCKED.md — Exists if worker says it is stuck

REVIEW PROCESS:
1. Read {state_dir}/task.md to understand what was requested
2. Read {state_dir}/work-summary.md to see what the worker claims
3. Read the actual project files to verify the claims
4. Run tests if they exist
5. Write your verdict

REVIEW CRITERIA:
1. Does the code/work actually accomplish the task?
2. Does it run without errors?
3. Is it reasonably complete (not half-done)?
4. Are there obvious bugs or issues?

BE STRICT but FAIR:
- Don't nitpick style if functionality is correct
- DO reject incomplete work
- DO reject code that doesn't run
- DO reject if tests fail

OUTPUT (MANDATORY — the file must contain ONLY the verdict word):
- If approved: write exactly "SHIP" to {state_dir}/review-result.md
- If needs work: write exactly "REVISE" to {state_dir}/review-result.md
  AND write specific, actionable feedback to {state_dir}/review-feedback.md
"""


def _default_loop() -> list["StepConfig"]:
    return [
        StepConfig(
            step_name="worker",
            task_prompt=DEFAULT_WORKER_TASK_PROMPT,
            system_prompt=DEFAULT_WORKER_SYSTEM_PROMPT,
        ),
        StepConfig(
            step_name="reviewer",
            task_prompt=DEFAULT_REVIEWER_TASK_PROMPT,
            system_prompt=DEFAULT_REVIEWER_SYSTEM_PROMPT,
        ),
    ]


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
    state_dir: str
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


def load_config(path: str | Path | None = None) -> RalphConfig:
    """Load config from a YAML file, or return defaults if no path given."""
    if path is None:
        return RalphConfig(
            max_iterations=DEFAULT_MAX_ITERATIONS,
            default_model=DEFAULT_MODEL,
            state_dir=STATE_DIR,
            loop=_default_loop(),
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
    }
    unknown = set(data) - valid_keys
    if unknown:
        print(
            f"Warning: unknown config keys ignored: {', '.join(sorted(unknown))}",
            file=sys.stderr,
        )

    max_iterations = int(data.get("max_iterations", DEFAULT_MAX_ITERATIONS))
    if max_iterations < 1:
        raise ValueError(f"max_iterations must be >= 1, got {max_iterations}")

    default_model = data.get("default_model", DEFAULT_MODEL)
    state_dir = data.get("state_dir", STATE_DIR)

    if "loop" in data:
        loop_steps = _parse_steps(data["loop"], "loop")
        if not loop_steps:
            raise ValueError("loop must have at least 1 step")
    else:
        loop_steps = _default_loop()

    setup_steps = _parse_steps(data.get("setup", []), "setup")
    cleanup_steps = _parse_steps(data.get("cleanup", []), "cleanup")

    return RalphConfig(
        max_iterations=max_iterations,
        default_model=default_model,
        state_dir=state_dir,
        loop=loop_steps,
        setup=setup_steps,
        cleanup=cleanup_steps,
    )
