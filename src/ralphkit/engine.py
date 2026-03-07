import json
import sys
import time
from dataclasses import replace
from pathlib import Path

from ralphkit.config import (
    DEFAULT_PLANNER_SYSTEM_PROMPT,
    DEFAULT_PLANNER_TASK_PROMPT,
    StepConfig,
    load_config,
    resolve_model,
)
from ralphkit.report import RunReport, git_diff_stat, print_report
from ralphkit.runner import run_claude
from ralphkit.state import StateDir
from ralphkit.ui import (
    console,
    fmt_duration,
    print_banner,
    print_current_item,
    print_error,
    print_kv,
    print_outcome,
    print_plan_progress,
    print_plan_summary,
    print_rule,
    print_step_done,
    print_step_start,
    print_warning,
)


def _run_phase(prompt: str, model: str, system_prompt: str) -> dict | None:
    """Run a claude phase, exiting on failure."""
    try:
        return run_claude(prompt, model, system_prompt)
    except RuntimeError as e:
        print_error(f"Error: {e}")
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
    """Resolve handoff prompt using 3-tier override: step -> config -> built-in default."""
    if step.handoff_prompt is not None:
        return step.handoff_prompt
    if config_handoff is not None:
        return config_handoff
    return _build_default_handoff(step_index, total_steps, steps, state_dir)


def _validate_plan(plan: dict | None) -> str | None:
    """Validate a plan dict. Returns error message or None if valid."""
    if plan is None:
        return "no valid plan.json produced"
    if not isinstance(plan, dict):
        return "plan.json is not a JSON object"
    items = plan.get("items")
    if not isinstance(items, list) or len(items) == 0:
        return "Plan has no items"
    for i, item in enumerate(items):
        if not isinstance(item, dict):
            return f"plan item {i} is not an object"
        for key in ("id", "title", "done"):
            if key not in item:
                return f"plan item {i} is missing required field '{key}'"
    return None


def run_foreground(
    task: str | None,
    config_path: str | None = None,
    max_iterations: int | None = None,
    default_model: str | None = None,
    state_dir: str | None = None,
    force: bool = False,
    plan_path: str | None = None,
    plan_only: bool = False,
    plan_model: str | None = None,
) -> None:
    """Run a ralph task in the foreground (pipe or loop mode)."""
    try:
        config = load_config(config_path)
    except ValueError as e:
        print_error(f"Config error: {e}")
        sys.exit(1)

    if max_iterations is not None:
        if max_iterations < 1:
            print_error(
                f"Config error: max_iterations must be >= 1, got {max_iterations}"
            )
            sys.exit(1)
        config = replace(config, max_iterations=max_iterations)

    if default_model is not None:
        config = replace(config, default_model=default_model)

    if state_dir is not None:
        config = replace(config, state_dir=state_dir)

    if plan_model is not None:
        config = replace(config, plan_model=plan_model)

    state = StateDir(config.state_dir)

    if config.pipe:
        task_content = resolve_task(task) if task else None
    elif task is None:
        print_error("task is required for loop mode")
        sys.exit(1)
    else:
        task_content = resolve_task(task)

    start_time = time.time()

    state.setup()
    if task_content is not None:
        state.write_task(task_content)

    # -- Banner --
    is_pipe = bool(config.pipe)
    console.print()
    print_banner(f"RALPH {'PIPE' if is_pipe else 'LOOP'}")
    console.print()
    if task_content is not None:
        first_line = task_content.split("\n", 1)[0]
        print_kv("Task", first_line)
    print_kv("Run", f"#{state.path.name}")
    print_kv("Model", config.default_model)
    if is_pipe:
        print_kv("Steps", str(len(config.pipe)))
        print_kv("Pipe", _step_names(config.pipe))
    else:
        print_kv("Max iter", str(config.max_iterations))
        if config.setup:
            print_kv("Setup", _step_names(config.setup))
        print_kv("Loop", _step_names(config.loop))
        if config.cleanup:
            print_kv("Cleanup", _step_names(config.cleanup))
    console.print()

    # -- Confirmation --
    if not force:
        if is_pipe:
            print_warning(
                f"This will run {len(config.pipe)} steps. Each step costs API credits."
            )
        else:
            print_warning(
                f"Warning: This will run up to {config.max_iterations} iterations."
            )
            print_warning("   Each step costs API credits.")
        console.print()
        confirm = input("Proceed? (y/N) ").strip()
        if confirm.lower() not in ("y", "yes"):
            print_error("Aborted.")
            sys.exit(1)
        console.print()

    # -- Common template variables --
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
    ) -> tuple[str, dict | None]:
        """Run a step and return (model, claude_json_output)."""
        variables = _base_vars(step)
        if extra_vars:
            variables.update(extra_vars)
        prompt = _render_prompt(step.task_prompt, variables)
        system = _render_prompt(step.system_prompt, variables)
        if system_suffix:
            system = system + "\n\n" + system_suffix
        model = variables["model"]
        result = _run_phase(prompt, model, system)
        return model, result

    report = RunReport()

    def _finalize_report():
        try:
            report.total_duration_s = time.time() - start_time
            print_report(report)
            report.save(state.path / "report.json")
            console.print(f"  [dim]Saved to {state.path / 'report.json'}[/]")
        except Exception:
            pass

    def _record_step(step, model, claude_out, t0, phase, before_diff, iteration=None):
        before_add, before_del = before_diff
        after_add, after_del = git_diff_stat()
        report.record_step(
            step_name=step.step_name,
            model=model,
            phase=phase,
            duration_s=time.time() - t0,
            iteration=iteration,
            claude_output=claude_out,
            lines_added=max(0, after_add - before_add),
            lines_deleted=max(0, after_del - before_del),
        )

    def _check_blocked() -> None:
        blocked = state.is_blocked()
        if blocked:
            report.outcome = "BLOCKED"
            console.print()
            console.print("[error]Blocked:[/]")
            console.print(blocked)
            sys.exit(1)

    if is_pipe:
        # -- PIPE execution --
        total_steps = len(config.pipe)
        task_str = task_content if task_content is not None else ""
        state_dir_str = str(state.active_path)

        try:
            for idx, step in enumerate(config.pipe, 1):
                step_model = resolve_model(step, config.default_model)
                print_step_start(idx, total_steps, step.step_name, step_model)
                before_diff = git_diff_stat()
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

                model, claude_out = _run_step(
                    step, extra_vars=pipe_vars, system_suffix=handoff
                )
                _record_step(step, model, claude_out, t0, "pipe", before_diff)
                print_step_done(fmt_duration(time.time() - t0))

                _check_blocked()

            report.outcome = "PIPE_COMPLETE"
            console.print()
            print_outcome(
                f"PIPE COMPLETE \u2014 {total_steps} steps finished", success=True
            )
            sys.exit(0)
        finally:
            if report.outcome is None:
                report.outcome = "ERROR"
            _finalize_report()

    # -- SETUP phase --
    if config.setup:
        print_rule("Setup")
        total_setup = len(config.setup)
        for idx, step in enumerate(config.setup, 1):
            print_step_start(idx, total_setup, step.step_name)
            before_diff = git_diff_stat()
            t0 = time.time()
            model, claude_out = _run_step(step)
            _record_step(step, model, claude_out, t0, "setup", before_diff)
            print_step_done(fmt_duration(time.time() - t0))
        console.print()

    # -- PLANNING phase --
    plan = None
    if plan_path:
        # User provided a plan file — validate and copy it
        pp = Path(plan_path)
        if not pp.is_file():
            print_error(f"Plan file not found: {plan_path}")
            sys.exit(1)
        try:
            plan = json.loads(pp.read_text())
        except (json.JSONDecodeError, TypeError) as e:
            print_error(f"Invalid plan file: {e}")
            sys.exit(1)
        err = _validate_plan(plan)
        if err:
            print_error(f"Invalid plan file: {err}")
            sys.exit(1)
        state.copy_plan(pp)
    else:
        # Run the planner agent
        print_rule("Planning")
        planner_model = config.plan_model or config.default_model
        planner_step = StepConfig(
            step_name="planner",
            task_prompt=DEFAULT_PLANNER_TASK_PROMPT,
            system_prompt=DEFAULT_PLANNER_SYSTEM_PROMPT,
        )
        print_step_start(1, 1, "planner", planner_model)
        before_diff = git_diff_stat()
        t0 = time.time()
        planner_vars = _base_vars(planner_step)
        planner_vars["model"] = planner_model
        prompt = _render_prompt(planner_step.task_prompt, planner_vars)
        system = _render_prompt(planner_step.system_prompt, planner_vars)
        claude_out = _run_phase(prompt, planner_model, system)
        _record_step(
            planner_step, planner_model, claude_out, t0, "planning", before_diff
        )
        print_step_done(fmt_duration(time.time() - t0))

        # Validate the plan
        plan = state.read_plan()
        err = _validate_plan(plan)
        if err:
            print_error(
                f"Planning failed: {err}. "
                "Try --plan-only to debug, or provide your own with --plan."
            )
            sys.exit(1)

    # Show plan summary
    items = plan.get("items", [])
    console.print()
    console.print(f"  [label]Plan:[/] {len(items)} items")
    print_plan_summary(plan)
    console.print()

    # --plan-only: exit after showing the plan
    if plan_only:
        console.print(f"  Plan written to {state.path / 'plan.json'}")
        # Ensure plan is written if provided via --plan
        if not (state.path / "plan.json").exists():
            state.write_plan(plan)
        sys.exit(0)

    # -- LOOP phase (with cleanup in finally) --
    total_loop_steps = len(config.loop)

    try:
        for i in range(1, config.max_iterations + 1):
            # Read plan once at iteration start (1 file read)
            plan = state.read_plan()

            print_rule(f"Iteration {i} / {config.max_iterations}")
            console.print()

            if plan:
                for item in plan.get("items", []):
                    if not item.get("done", False):
                        print_current_item(item)
                        console.print()
                        break

            state.write_iteration(i)
            report.iterations_completed = i
            iter_start = time.time()

            loop_vars = {"iteration": str(i)}

            for idx, step in enumerate(config.loop, 1):
                step_model = resolve_model(step, config.default_model)
                print_step_start(idx, total_loop_steps, step.step_name, step_model)
                before_diff = git_diff_stat()
                t0 = time.time()
                model, claude_out = _run_step(step, loop_vars)
                _record_step(
                    step, model, claude_out, t0, "loop", before_diff, iteration=i
                )
                print_step_done(fmt_duration(time.time() - t0))

                _check_blocked()

            # Re-read plan after worker runs (1 file read)
            plan = state.read_plan()
            if plan is None:
                report.outcome = "ERROR"
                print_error("Worker corrupted plan.json (invalid JSON).")
                sys.exit(1)

            plan_items = plan.get("items", [])
            done_count = sum(1 for it in plan_items if it.get("done", False))
            total_count = len(plan_items)
            all_done = done_count == total_count
            report.items_completed = done_count
            report.items_total = total_count

            console.print()
            print_plan_progress(done_count, total_count)
            console.print(
                f"  [dim]Iteration {i} completed in {fmt_duration(time.time() - iter_start)}[/]"
            )

            if all_done:
                report.outcome = "COMPLETE"
                console.print()
                print_outcome(
                    f"COMPLETE \u2014 All {total_count} items done in {i} iteration(s)!",
                    success=True,
                )
                sys.exit(0)

            state.clean_for_next_iteration()

        # -- Max iterations reached --
        # plan was already read at end of last iteration
        report.outcome = "MAX_ITERATIONS"
        console.print()
        print_outcome(
            f"Max iterations ({config.max_iterations}) reached. "
            f"{report.items_completed}/{report.items_total} items completed.",
            success=False,
        )
        sys.exit(1)
    finally:
        if report.outcome is None:
            report.outcome = "ERROR"
        # -- CLEANUP phase (always runs) --
        if config.cleanup:
            console.print()
            print_rule("Cleanup")
            total_cleanup = len(config.cleanup)
            for idx, step in enumerate(config.cleanup, 1):
                print_step_start(idx, total_cleanup, step.step_name)
                before_diff = git_diff_stat()
                t0 = time.time()
                model, claude_out = _run_step(step)
                _record_step(step, model, claude_out, t0, "cleanup", before_diff)
                print_step_done(fmt_duration(time.time() - t0))
            console.print()
        _finalize_report()
