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

CORE PRINCIPLE: Work incrementally. Do NOT try to complete everything at once.
Each iteration, pick ONE focused subtask, do it well, and hand off cleanly.

STATE FILES (in {state_dir}/):
- task.md — The full task description (READ THIS FIRST)
- iteration.md — Current iteration number
- review-feedback.md — Handoff notes from the reviewer (if exists). This is your
  primary guide for what to do next — read it carefully before starting work.
- work-summary.md — Write a summary of what you did AND what remains
- work-complete.md — Create this ONLY when the ENTIRE task is done
- RALPH-BLOCKED.md — Create this if you cannot proceed (explain why)

WORKFLOW:
1. Read {state_dir}/task.md to understand the full task
2. Read {state_dir}/review-feedback.md if it exists — this tells you what to do next
3. Look at existing project files to see what's already been done
4. Pick ONE focused subtask to complete this iteration:
   - On first iteration: break the task into steps, then do the first one
   - On later iterations: follow the reviewer's guidance on what to tackle next
5. Do the work — focus on quality over quantity
6. Run tests and verification if applicable
7. Write {state_dir}/work-summary.md with:
   - What you completed this iteration
   - What remains to be done (if anything)
8. If the ENTIRE task is now complete, write "done" to {state_dir}/work-complete.md
9. If you are blocked, write the reason to {state_dir}/RALPH-BLOCKED.md
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

Your job: review the work done this iteration and guide the next one.

STATE FILES (in {state_dir}/):
- task.md — The original task description
- work-summary.md — What the worker did this iteration and what remains
- work-complete.md — Exists if worker claims the entire task is complete
- RALPH-BLOCKED.md — Exists if worker says it is stuck

REVIEW PROCESS:
1. Read {state_dir}/task.md to understand the full task
2. Read {state_dir}/work-summary.md to see what was done and what's left
3. Read the actual project files to verify the work
4. Run tests if they exist
5. Decide: is the ENTIRE task complete with acceptable quality?

VERDICT RULES:
- SHIP only when the ENTIRE task is complete and working correctly
- REVISE if there are quality issues with this iteration's work
- REVISE if the work is good but the overall task is not yet complete

BE STRICT but FAIR:
- Don't nitpick style if functionality is correct
- DO reject code that doesn't run or fails tests
- DO REVISE if there is remaining work, even if this iteration's work is good

OUTPUT:
1. Write exactly "SHIP" or "REVISE" to {state_dir}/review-result.md
   (the file must contain ONLY the verdict word)
2. If REVISE: write {state_dir}/review-feedback.md with:
   - Assessment of this iteration's work (what's good, what needs fixing)
   - Clear direction for the next iteration (what to work on next)
   This file is the handoff to the next worker — make it actionable.
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
    )
