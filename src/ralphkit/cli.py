import argparse
import sys
import time
from dataclasses import replace
from pathlib import Path

from ralphkit.config import (
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


def _build_default_handoff(
    step_index: int,
    total_steps: int,
    steps: list[StepConfig],
    state_dir: str,
) -> str:
    """Build position-aware default handoff instructions for a pipe step."""
    step_name = steps[step_index - 1].step_name
    parts = []

    # Read from previous step's handoff
    if step_index > 1:
        prev_name = steps[step_index - 2].step_name
        parts.append(
            f"Read {state_dir}/handoff__{prev_name}__to__{step_name}.md "
            f"for context from the previous step."
        )

    # Write handoff for next step
    if step_index < total_steps:
        next_name = steps[step_index].step_name
        parts.append(
            f"When you finish, write your output and handoff notes to "
            f"{state_dir}/handoff__{step_name}__to__{next_name}.md"
        )

    # Always suggest reading task.md
    parts.append(
        f"If {state_dir}/task.md exists, read it for the overall task context."
    )

    return "\n\n".join(parts)


def _resolve_handoff(
    step: StepConfig,
    config_handoff: str | None,
    step_index: int,
    total_steps: int,
    steps: list[StepConfig],
    state_dir: str,
) -> str:
    """Resolve handoff prompt using 3-tier override: step → config → built-in default."""
    if step.handoff_prompt is not None:
        return step.handoff_prompt
    if config_handoff is not None:
        return config_handoff
    return _build_default_handoff(step_index, total_steps, steps, state_dir)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Agent pipes and loops for Claude Code",
    )
    parser.add_argument(
        "task",
        nargs="?",
        default=None,
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
        "--default-model",
        default=None,
        help="Override default model from config",
    )
    parser.add_argument(
        "--state-dir",
        default=None,
        help="Override state directory (default: .ralphkit)",
    )
    parser.add_argument(
        "-f",
        "--force",
        action="store_true",
        help="Skip confirmation prompt",
    )
    parser.add_argument(
        "--list-runs",
        action="store_true",
        help="List previous runs and exit",
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

    if args.default_model is not None:
        config = replace(config, default_model=args.default_model)

    if args.state_dir is not None:
        config = replace(config, state_dir=args.state_dir)

    state = StateDir(config.state_dir)

    # ── --list-runs early exit ─────────────────────────────────────
    if args.list_runs:
        runs = state.list_runs()
        if not runs:
            print("No runs found.")
        else:
            for run_dir in runs:
                task_file = run_dir / "task.md"
                first_line = ""
                if task_file.is_file():
                    first_line = task_file.read_text().split("\n", 1)[0]
                print(f"  #{run_dir.name}  {first_line}")
        sys.exit(0)

    if config.pipe:
        task_content = resolve_task(args.task) if args.task else None
    elif args.task is None:
        parser.error("the following arguments are required: task")
    else:
        task_content = resolve_task(args.task)

    start_time = time.time()

    state.setup()
    if task_content is not None:
        state.write_task(task_content)

    # ── Banner ──────────────────────────────────────────────────────
    is_pipe = bool(config.pipe)
    print()
    print(f"{BLUE}{'=' * 59}{NC}")
    print(f"{BLUE}  RALPH {'PIPE' if is_pipe else 'LOOP'}{NC}")
    print(f"{BLUE}{'=' * 59}{NC}")
    print()
    if task_content is not None:
        first_line = task_content.split("\n", 1)[0]
        print(f"  {YELLOW}Task:{NC}      {first_line}")
    print(f"  {YELLOW}Run:{NC}       #{state.path.name}")
    print(f"  {YELLOW}Model:{NC}     {config.default_model}")
    if is_pipe:
        print(f"  {YELLOW}Steps:{NC}     {len(config.pipe)}")
        print(f"  {YELLOW}Pipe:{NC}      {_step_names(config.pipe)}")
    else:
        print(f"  {YELLOW}Max iter:{NC}  {config.max_iterations}")
        print(f"  {YELLOW}Setup:{NC}     {_step_names(config.setup)}")
        print(f"  {YELLOW}Loop:{NC}      {_step_names(config.loop)}")
        print(f"  {YELLOW}Cleanup:{NC}   {_step_names(config.cleanup)}")
    print()

    # ── Confirmation ────────────────────────────────────────────────
    if not args.force:
        if is_pipe:
            print(
                f"{YELLOW}This will run {len(config.pipe)} steps. Each step costs API credits.{NC}"
            )
        else:
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
            "state_dir": str(state.active_path),
        }

    def _run_step(
        step: StepConfig,
        extra_vars: dict[str, str] | None = None,
        system_suffix: str = "",
    ) -> str:
        """Run a step and return the resolved model name."""
        variables = _base_vars(step)
        if extra_vars:
            variables.update(extra_vars)
        prompt = _render_prompt(step.task_prompt, variables)
        system = _render_prompt(step.system_prompt, variables)
        if system_suffix:
            system = system + "\n\n" + system_suffix
        model = variables["model"]
        _run_phase(prompt, model, system)
        return model

    def _fmt_elapsed(elapsed: float) -> str:
        return f"{elapsed:.1f}s"

    def _print_total_elapsed() -> None:
        print(f"\n  Total elapsed: {_fmt_elapsed(time.time() - start_time)}")

    def _check_blocked() -> None:
        blocked = state.is_blocked()
        if blocked:
            print()
            print(f"{RED}Blocked:{NC}")
            print(blocked)
            _print_total_elapsed()
            sys.exit(1)

    if is_pipe:
        # ── PIPE execution ─────────────────────────────────────────
        total_steps = len(config.pipe)
        task_str = task_content if task_content is not None else ""
        state_dir_str = str(state.active_path)

        for idx, step in enumerate(config.pipe, 1):
            step_model = resolve_model(step, config.default_model)
            print(
                f"  {YELLOW}[{idx}/{total_steps}] {step.step_name} ({step_model})...{NC}"
            )
            t0 = time.time()

            prev_step_name = config.pipe[idx - 2].step_name if idx > 1 else ""
            next_step_name = config.pipe[idx].step_name if idx < total_steps else ""

            pipe_vars: dict[str, str] = {
                "step_index": str(idx),
                "total_steps": str(total_steps),
                "prev_step_name": prev_step_name,
                "next_step_name": next_step_name,
                "task": task_str,
            }

            # Resolve and render handoff prompt
            raw_handoff = _resolve_handoff(
                step,
                config.handoff_prompt,
                idx,
                total_steps,
                config.pipe,
                state_dir_str,
            )
            handoff = (
                _render_prompt(raw_handoff, pipe_vars | _base_vars(step))
                if raw_handoff
                else ""
            )

            _run_step(step, extra_vars=pipe_vars, system_suffix=handoff)
            print(f"  {GREEN}   Done. ({_fmt_elapsed(time.time() - t0)}){NC}")

            _check_blocked()

        print()
        print(f"{GREEN}{'=' * 59}{NC}")
        print(f"{GREEN}  PIPE COMPLETE — {total_steps} steps finished{NC}")
        print(f"{GREEN}{'=' * 59}{NC}")
        _print_total_elapsed()
        sys.exit(0)

    # ── SETUP phase ─────────────────────────────────────────────────
    if config.setup:
        print(f"{BLUE}── Setup ──{NC}")
        total_setup = len(config.setup)
        for idx, step in enumerate(config.setup, 1):
            print(f"  {YELLOW}[{idx}/{total_setup}] {step.step_name}...{NC}")
            t0 = time.time()
            _run_step(step)
            print(f"  {GREEN}   Done. ({_fmt_elapsed(time.time() - t0)}){NC}")
        print()

    # ── LOOP phase (with cleanup in finally) ────────────────────────
    total_loop_steps = len(config.loop)
    try:
        for i in range(1, config.max_iterations + 1):
            print(f"{BLUE}{'-' * 59}{NC}")
            print(f"{BLUE}  Iteration {i} / {config.max_iterations}{NC}")
            print(f"{BLUE}{'-' * 59}{NC}")
            print()

            state.write_iteration(i)
            iter_start = time.time()

            loop_vars = {"iteration": str(i)}

            for idx, step in enumerate(config.loop, 1):
                step_model = resolve_model(step, config.default_model)
                print(
                    f"  {YELLOW}[{idx}/{total_loop_steps}] {step.step_name} ({step_model})...{NC}"
                )
                t0 = time.time()
                _run_step(step, loop_vars)
                print(f"  {GREEN}   Done. ({_fmt_elapsed(time.time() - t0)}){NC}")

                _check_blocked()

            # Show work summary if present
            summary = state.read_work_summary()
            if summary:
                print()
                print(f"  {YELLOW}   Summary:{NC}")
                for line in summary.splitlines():
                    print(f"     {line}")
                print()

            print(
                f"  Iteration {i} completed in {_fmt_elapsed(time.time() - iter_start)}"
            )

            # ── Check review result ─────────────────────────────────
            result = state.read_review_result()
            if result is None:
                print(f"{RED}Review failed: no review-result.md produced.{NC}")
                _print_total_elapsed()
                sys.exit(1)

            if result == VERDICT_SHIP:
                print(f"{GREEN}{'=' * 59}{NC}")
                print(f"{GREEN}  SHIP — Task completed in {i} iteration(s)!{NC}")
                print(f"{GREEN}{'=' * 59}{NC}")
                _print_total_elapsed()
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
                _print_total_elapsed()
                sys.exit(1)

        # ── Max iterations reached ──────────────────────────────────
        print()
        print(f"{RED}{'=' * 59}{NC}")
        print(
            f"{RED}  Max iterations ({config.max_iterations}) reached without SHIP.{NC}"
        )
        print(f"{RED}{'=' * 59}{NC}")
        _print_total_elapsed()
        sys.exit(1)
    finally:
        # ── CLEANUP phase (always runs) ─────────────────────────────
        if config.cleanup:
            print()
            print(f"{BLUE}── Cleanup ──{NC}")
            total_cleanup = len(config.cleanup)
            for idx, step in enumerate(config.cleanup, 1):
                print(f"  {YELLOW}[{idx}/{total_cleanup}] {step.step_name}...{NC}")
                t0 = time.time()
                _run_step(step)
                print(f"  {GREEN}   Done. ({_fmt_elapsed(time.time() - t0)}){NC}")
            print()
