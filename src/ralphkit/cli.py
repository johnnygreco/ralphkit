import argparse
import sys
from dataclasses import replace
from pathlib import Path

from ralphkit.config import (
    STATE_DIR,
    VERDICT_REVISE,
    VERDICT_SHIP,
    StepConfig,
    load_config,
    resolve_model,
)
from ralphkit.runner import run_claude
from ralphkit.state import StateDir

# ── Colors ──────────────────────────────────────────────────────────
RED = "\033[0;31m"
GREEN = "\033[0;32m"
YELLOW = "\033[1;33m"
BLUE = "\033[0;34m"
NC = "\033[0m"


def _run_phase(prompt: str, model: str, system_prompt: str) -> None:
    """Run a claude phase, exiting on failure."""
    try:
        run_claude(prompt, model, system_prompt)
    except RuntimeError as e:
        print(f"\n{RED}Error: {e}{NC}", file=sys.stderr)
        sys.exit(1)


def resolve_task(raw: str) -> str:
    """If the string ends with .md and the file exists, read it. Otherwise return as-is."""
    if raw.endswith(".md"):
        p = Path(raw)
        try:
            return p.read_text()
        except (FileNotFoundError, OSError):
            pass
    return raw


def _render_prompt(template: str, variables: dict[str, str]) -> str:
    """Render a prompt template with safe substitution (unrecognized keys left as-is)."""

    class SafeDict(dict):
        def __missing__(self, key):
            return "{" + key + "}"

    return template.format_map(SafeDict(variables))


def _step_names(steps: list[StepConfig]) -> str:
    return ", ".join(s.step_name for s in steps) if steps else "(none)"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Iterative step-based pipeline for Claude Code",
    )
    parser.add_argument(
        "task",
        help="Task description (string or path to .md file)",
    )
    parser.add_argument(
        "--config",
        default=None,
        help="Path to YAML config file (optional; uses built-in defaults if omitted)",
    )
    parser.add_argument(
        "--max-iterations",
        type=int,
        default=None,
        help="Override max iterations from config",
    )
    parser.add_argument(
        "-f",
        "--force",
        action="store_true",
        help="Skip confirmation prompt",
    )
    args = parser.parse_args()

    try:
        config = load_config(args.config)
    except ValueError as e:
        print(f"{RED}Config error: {e}{NC}", file=sys.stderr)
        sys.exit(1)

    if args.max_iterations is not None:
        if args.max_iterations < 1:
            print(
                f"{RED}Config error: max_iterations must be >= 1, got {args.max_iterations}{NC}",
                file=sys.stderr,
            )
            sys.exit(1)
        config = replace(config, max_iterations=args.max_iterations)

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
    print(f"  {YELLOW}Task:{NC}      {first_line}")
    print(f"  {YELLOW}Model:{NC}     {config.default_model}")
    print(f"  {YELLOW}Max iter:{NC}  {config.max_iterations}")
    print(f"  {YELLOW}Setup:{NC}     {_step_names(config.setup)}")
    print(f"  {YELLOW}Loop:{NC}      {_step_names(config.loop)}")
    print(f"  {YELLOW}Cleanup:{NC}   {_step_names(config.cleanup)}")
    print()

    # ── Confirmation ────────────────────────────────────────────────
    if not args.force:
        print(
            f"{YELLOW}Warning: This will run up to {config.max_iterations} iterations.{NC}"
        )
        print(f"{YELLOW}   Each step costs API credits.{NC}")
        print()
        confirm = input("Proceed? (y/N) ").strip()
        if confirm.lower() not in ("y", "yes"):
            print(f"{RED}Aborted.{NC}")
            sys.exit(1)
        print()

    # ── Common template variables ───────────────────────────────────
    def _base_vars(step: StepConfig) -> dict[str, str]:
        return {
            "step_name": step.step_name,
            "max_iterations": str(config.max_iterations),
            "default_model": config.default_model,
            "model": resolve_model(step, config.default_model),
            "state_dir": STATE_DIR,
        }

    def _run_step(step: StepConfig, extra_vars: dict[str, str] | None = None) -> str:
        """Run a step and return the resolved model name."""
        variables = _base_vars(step)
        if extra_vars:
            variables.update(extra_vars)
        prompt = _render_prompt(step.task_prompt, variables)
        system = _render_prompt(step.system_prompt, variables)
        model = variables["model"]
        _run_phase(prompt, model, system)
        return model

    # ── SETUP phase ─────────────────────────────────────────────────
    if config.setup:
        print(f"{BLUE}── Setup ──{NC}")
        for step in config.setup:
            print(f"  {YELLOW}{step.step_name}...{NC}")
            _run_step(step)
            print(f"  {GREEN}   Done.{NC}")
        print()

    # ── LOOP phase (with cleanup in finally) ────────────────────────
    try:
        for i in range(1, config.max_iterations + 1):
            print(f"{BLUE}{'-' * 59}{NC}")
            print(f"{BLUE}  Iteration {i} / {config.max_iterations}{NC}")
            print(f"{BLUE}{'-' * 59}{NC}")
            print()

            state.write_iteration(i)

            loop_vars = {"iteration": str(i)}

            for step in config.loop:
                step_model = resolve_model(step, config.default_model)
                print(f"  {YELLOW}{step.step_name} ({step_model})...{NC}")
                _run_step(step, loop_vars)
                print(f"  {GREEN}   Done.{NC}")

                # Check for blocked state after each step
                blocked = state.is_blocked()
                if blocked:
                    print()
                    print(f"{RED}Blocked:{NC}")
                    print(blocked)
                    sys.exit(1)

            # Show work summary if present
            summary = state.read_work_summary()
            if summary:
                print()
                print(f"  {YELLOW}   Summary:{NC}")
                for line in summary.splitlines():
                    print(f"     {line}")
                print()

            # ── Check review result ─────────────────────────────────
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

        # ── Max iterations reached ──────────────────────────────────
        print()
        print(f"{RED}{'=' * 59}{NC}")
        print(
            f"{RED}  Max iterations ({config.max_iterations}) reached without SHIP.{NC}"
        )
        print(f"{RED}{'=' * 59}{NC}")
        print()
        sys.exit(1)
    finally:
        # ── CLEANUP phase (always runs) ─────────────────────────────
        if config.cleanup:
            print()
            print(f"{BLUE}── Cleanup ──{NC}")
            for step in config.cleanup:
                print(f"  {YELLOW}{step.step_name}...{NC}")
                _run_step(step)
                print(f"  {GREEN}   Done.{NC}")
            print()
