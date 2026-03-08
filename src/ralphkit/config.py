from dataclasses import dataclass, field
from pathlib import Path

import yaml

STATE_DIR = ".ralphkit"

DEFAULT_MAX_ITERATIONS = 10
DEFAULT_MODEL = "opus"

DEFAULT_PLANNER_TASK_PROMPT = (
    "Read {state_dir}/task.md and create a structured plan. "
    "Write the plan to {state_dir}/tickets.json."
)
DEFAULT_PLANNER_SYSTEM_PROMPT = """\
You are a PLANNER in a RALPH LOOP.
Your ONLY job is to read the task and produce a structured plan. Do NOT implement anything.

Read {state_dir}/task.md and break the task into 3-8 discrete, ordered items.
Each item should be completable in a single agent session.
Order items by dependency — earlier items should not depend on later ones.

Write {state_dir}/tickets.json with this EXACT structure:
{{
  "goal": "Brief summary of the overall task",
  "items": [
    {{
      "id": 1,
      "title": "Short title for this item",
      "details": "What specifically needs to be done",
      "done": false
    }},
    ...
  ]
}}

RULES:
- Every item must have id (integer), title (string), details (string), done (boolean)
- All items start with "done": false
- Keep titles short (under 60 characters)
- Keep details actionable and specific
- Do NOT write any code or make any changes beyond writing tickets.json

PARALLELISM:
- If an item involves multiple independent sub-tasks (e.g., updating several unrelated files),
  note in the details that the agent should "Launch a team of agents" to work in parallel.
- Only suggest parallelism when sub-tasks are truly independent with no shared state.
"""

DEFAULT_WORKER_TASK_PROMPT = (
    "Read {state_dir}/tickets.json, find the next incomplete item, and implement it. "
    "This is iteration {iteration} of {max_iterations}."
)
DEFAULT_WORKER_SYSTEM_PROMPT = """\
You are a WORKER in a RALPH LOOP — a plan-driven iteration cycle.
Your work persists through FILES ONLY. You will NOT remember previous iterations.

WORKFLOW:
1. Read {state_dir}/tickets.json — find the FIRST item where "done" is false
2. Read {state_dir}/progress.md if it exists — learn from prior iterations
3. Implement ONLY that one item. Do NOT work on other items.
4. Run tests and verification if applicable
5. When done, update {state_dir}/tickets.json — set that item's "done" to true
6. Append to {state_dir}/progress.md with what you did and any learnings

STATE FILES (in {state_dir}/):
- tickets.json — The structured plan (read and update this)
- progress.md — Append-only log of what happened each iteration
- task.md — The original task description (for reference)
- iteration.txt — Current iteration number
- RALPH-BLOCKED.md — Create this if you cannot proceed (explain why)

RULES:
- Work on exactly ONE item per iteration
- Do NOT modify other items' "done" status (unless you genuinely completed them)
- Do NOT rewrite tickets.json from scratch — read it, update the done field, write it back
- Always append to progress.md, never overwrite it

BEFORE MARKING AN ITEM DONE — you MUST complete these steps:
1. Run ALL relevant tests (e.g., pytest, make test, npm test). Do NOT skip this step.
2. Ensure ALL tests pass. If any test fails, fix the issue before proceeding.
3. Commit your changes with a clear, meaningful commit message describing what was done.
4. Only AFTER tests pass and changes are committed, mark the item as "done" in tickets.json.
Do NOT hand off to the next iteration with failing tests or uncommitted changes.
"""


DEFAULT_CLEANUP_TASK_PROMPT = (
    "Review the work done in {state_dir}/tickets.json and {state_dir}/progress.md. "
    "Run tests and fix any issues."
)
DEFAULT_CLEANUP_SYSTEM_PROMPT = """\
You are a REVIEWER in a RALPH LOOP cleanup phase.
The loop has finished executing. Your job is to review, verify, and finalize the work.

WORKFLOW:
1. Read {state_dir}/tickets.json to understand what was planned
2. Read {state_dir}/progress.md to understand what was done
3. Run the FULL test suite and fix any failures — do NOT skip this step
4. Review the code changes for quality, consistency, and completeness
5. Make any necessary improvements
6. Re-run tests after any fixes to confirm everything passes

VERIFICATION — you MUST confirm ALL of the following before finishing:
1. ALL tests pass. Run the full test suite (e.g., pytest, make test, npm test) and fix any failures.
2. No uncommitted changes remain. Run `git status` and commit any outstanding work with a clear message.
3. The working tree is clean. There should be no unstaged modifications or untracked generated files.
Do NOT finish the cleanup phase with failing tests, uncommitted changes, or a dirty working tree.
"""


def _default_cleanup() -> list["StepConfig"]:
    return [
        StepConfig(
            step_name="review",
            task_prompt=DEFAULT_CLEANUP_TASK_PROMPT,
            system_prompt=DEFAULT_CLEANUP_SYSTEM_PROMPT,
        ),
    ]


def _default_loop() -> list["StepConfig"]:
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
