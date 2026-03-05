import argparse
import sys
from dataclasses import fields, replace
from pathlib import Path

from ralphkit.config import VERDICT_REVISE, VERDICT_SHIP, RalphConfig, load_config
from ralphkit.prompts import (
    REVIEWER_SYSTEM_PROMPT,
    WORKER_SYSTEM_PROMPT,
    reviewer_user_prompt,
    worker_user_prompt,
)
from ralphkit.runner import run_claude
from ralphkit.state import StateDir

# ── Colors ──────────────────────────────────────────────────────────
RED = "\033[0;31m"
GREEN = "\033[0;32m"
YELLOW = "\033[1;33m"
BLUE = "\033[0;34m"
NC = "\033[0m"


def resolve_task(raw: str) -> str:
    """If the string ends with .md and the file exists, read it. Otherwise return as-is."""
    if raw.endswith(".md"):
        p = Path(raw)
        try:
            return p.read_text()
        except (FileNotFoundError, OSError):
            pass
    return raw


def merge_config(config: RalphConfig, args: argparse.Namespace) -> RalphConfig:
    """Overlay explicit CLI args on top of config values."""
    overrides = {}
    for f in fields(RalphConfig):
        value = getattr(args, f.name, None)
        if value is not None:
            overrides[f.name] = value
    merged = replace(config, **overrides) if overrides else config
    if merged.max_iterations < 1:
        raise ValueError(f"max_iterations must be >= 1, got {merged.max_iterations}")
    return merged


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Iterative work/review loop for Claude Code",
    )
    parser.add_argument(
        "task",
        help="Task description (string or path to .md file)",
    )
    parser.add_argument(
        "--config",
        default=None,
        help="Path to YAML config file (only loaded when explicitly provided)",
    )
    parser.add_argument(
        "--worker-model",
        default=None,
        help="Model for work phase (default: opus)",
    )
    parser.add_argument(
        "--reviewer-model",
        default=None,
        help="Model for review phase (default: sonnet)",
    )
    parser.add_argument(
        "--max-iterations",
        type=int,
        default=None,
        help="Max work/review cycles (default: 10)",
    )
    parser.add_argument(
        "--worker-system-prompt",
        default=None,
        help="Override the worker system prompt entirely",
    )
    parser.add_argument(
        "--reviewer-system-prompt",
        default=None,
        help="Override the reviewer system prompt entirely",
    )
    parser.add_argument(
        "--worker-user-prompt",
        default=None,
        help="Override the worker user prompt (use {iteration} for iteration number)",
    )
    parser.add_argument(
        "--reviewer-user-prompt",
        default=None,
        help="Override the reviewer user prompt",
    )
    parser.add_argument(
        "--append-system-prompt",
        default=None,
        help="Extra text appended to both worker and reviewer system prompts",
    )
    parser.add_argument(
        "-y",
        "--yes",
        action="store_true",
        help="Skip confirmation prompt",
    )
    args = parser.parse_args()

    try:
        config = load_config(args.config)
        config = merge_config(config, args)
    except ValueError as e:
        print(f"{RED}Config error: {e}{NC}", file=sys.stderr)
        sys.exit(1)
    task_content = resolve_task(args.task)

    state = StateDir()
    state.setup()
    state.clean()
    state.write_task(task_content)

    # ── Banner ──────────────────────────────────────────────────────
    first_line = task_content.split("\n", 1)[0]
    print()
    print(f"{BLUE}{'=' * 59}{NC}")
    print(f"{BLUE}  RALPH LOOP{NC}")
    print(f"{BLUE}{'=' * 59}{NC}")
    print()
    print(f"  {YELLOW}Task:{NC}     {first_line}")
    print(f"  {YELLOW}Worker:{NC}   {config.worker_model}")
    print(f"  {YELLOW}Reviewer:{NC} {config.reviewer_model}")
    print(f"  {YELLOW}Max iter:{NC} {config.max_iterations}")
    print()

    # ── Confirmation ────────────────────────────────────────────────
    if not args.yes:
        print(
            f"{YELLOW}Warning: This will run up to {config.max_iterations} iterations using two AI models.{NC}"
        )
        print(f"{YELLOW}   Each iteration costs API credits.{NC}")
        print()
        confirm = input("Proceed? (y/N) ").strip()
        if confirm.lower() not in ("y", "yes"):
            print(f"{RED}Aborted.{NC}")
            sys.exit(1)
        print()

    # ── Build prompts ──────────────────────────────────────────────────
    worker_sp = config.worker_system_prompt or WORKER_SYSTEM_PROMPT
    reviewer_sp = config.reviewer_system_prompt or REVIEWER_SYSTEM_PROMPT
    if config.append_system_prompt:
        worker_sp += "\n\n" + config.append_system_prompt
        reviewer_sp += "\n\n" + config.append_system_prompt
    worker_up_template = config.worker_user_prompt
    reviewer_up = config.reviewer_user_prompt or reviewer_user_prompt()

    # ── Main loop ───────────────────────────────────────────────────
    for i in range(1, config.max_iterations + 1):
        print(f"{BLUE}{'-' * 59}{NC}")
        print(f"{BLUE}  Iteration {i} / {config.max_iterations}{NC}")
        print(f"{BLUE}{'-' * 59}{NC}")
        print()

        state.write_iteration(i)

        # ── Work phase ──────────────────────────────────────────────
        print(f"  {YELLOW}Work phase ({config.worker_model})...{NC}")
        w_up = (
            worker_up_template.format(iteration=i)
            if worker_up_template
            else worker_user_prompt(i)
        )
        try:
            run_claude(w_up, config.worker_model, worker_sp)
        except RuntimeError as e:
            print(f"\n{RED}Error: {e}{NC}", file=sys.stderr)
            sys.exit(1)
        print(f"  {GREEN}   Done.{NC}")

        # Check for blocked state
        blocked = state.is_blocked()
        if blocked:
            print()
            print(f"{RED}Worker is BLOCKED:{NC}")
            print(blocked)
            sys.exit(1)

        # Show work summary
        summary = state.read_work_summary()
        if summary:
            print()
            print(f"  {YELLOW}   Summary:{NC}")
            for line in summary.splitlines():
                print(f"     {line}")
            print()

        # ── Review phase ────────────────────────────────────────────
        print(f"  {YELLOW}Review phase ({config.reviewer_model})...{NC}")
        try:
            run_claude(reviewer_up, config.reviewer_model, reviewer_sp)
        except RuntimeError as e:
            print(f"\n{RED}Error: {e}{NC}", file=sys.stderr)
            sys.exit(1)
        print(f"  {GREEN}   Done.{NC}")
        print()

        # ── Check review result ─────────────────────────────────────
        result = state.read_review_result()
        if result is None:
            print(f"{RED}Review failed: no review-result.md produced.{NC}")
            sys.exit(1)

        if result == VERDICT_SHIP:
            print(f"{GREEN}{'=' * 59}{NC}")
            print(f"{GREEN}  SHIP — Task completed in {i} iteration(s)!{NC}")
            print(f"{GREEN}{'=' * 59}{NC}")
            print()
            sys.exit(0)
        elif result == VERDICT_REVISE:
            print(f"  {YELLOW}REVISE — Reviewer wants changes.{NC}")
            feedback = state.read_review_feedback()
            if feedback:
                print()
                print(f"  {YELLOW}   Feedback:{NC}")
                for line in feedback.splitlines():
                    print(f"     {line}")
                print()
            state.clean_for_next_iteration()
        else:
            print(f"{RED}Unexpected review result: '{result}'{NC}")
            sys.exit(1)

    # ── Max iterations reached ──────────────────────────────────────
    print()
    print(f"{RED}{'=' * 59}{NC}")
    print(f"{RED}  Max iterations ({config.max_iterations}) reached without SHIP.{NC}")
    print(f"{RED}{'=' * 59}{NC}")
    print()
    sys.exit(1)
