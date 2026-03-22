import json
import subprocess
import sys
import time
from dataclasses import replace
from pathlib import Path

from ralphkit.config import (
    RalphConfig,
    StepConfig,
    load_config,
    resolve_model,
)
from ralphkit.prompts import (
    DEFAULT_PLANNER_SYSTEM_PROMPT,
    DEFAULT_PLANNER_TASK_PROMPT,
)
from ralphkit.report import RunReport, git_diff_stat, print_report
from ralphkit.runner import ClaudeRunError, run_claude
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


def _run_phase(
    prompt: str,
    model: str,
    system_prompt: str,
    *,
    timeout_seconds: int,
    idle_timeout_seconds: int | None,
    cwd: str,
    on_error=None,
) -> dict | None:
    """Run a claude phase, exiting on failure."""
    try:
        return run_claude(
            prompt,
            model,
            system_prompt,
            timeout_seconds=timeout_seconds,
            idle_timeout_seconds=idle_timeout_seconds,
            cwd=cwd,
        )
    except RuntimeError as e:
        if on_error is not None:
            on_error(e)
        print_error(f"Error: {e}")
        sys.exit(1)


def resolve_task(raw: str) -> str:
    """If the string ends with .md and the file exists, read it. Otherwise return as-is."""
    if raw.endswith(".md"):
        p = Path(raw).expanduser()
        try:
            return p.read_text()
        except (FileNotFoundError, OSError):
            print_warning(f"File '{raw}' not found, using as literal task string")
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
    step_index: int,
    total_steps: int,
    steps: list[StepConfig],
    state_dir: str,
) -> str:
    """Resolve handoff prompt: step override or built-in default."""
    if step.handoff_prompt is not None:
        return step.handoff_prompt
    return _build_default_handoff(step_index, total_steps, steps, state_dir)


def _validate_plan(plan: dict | None) -> str | None:
    """Validate a plan dict. Returns error message or None if valid."""
    if plan is None:
        return "no valid tickets.json produced"
    if not isinstance(plan, dict):
        return "tickets.json is not a JSON object"
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


def _checkpoint_suffix(state_dir: str, step_name: str) -> str:
    return (
        "CHECKPOINTING REQUIREMENTS:\n"
        f"- Maintain {state_dir}/progress.md incrementally during the '{step_name}' step.\n"
        "- Before any long-running command such as builds, broad test suites, benchmarks, "
        "or other operations likely to take more than a minute, append a short note with "
        "the timestamp, the command you are about to run, and why.\n"
        "- Immediately after each major command finishes or fails, append the outcome, "
        "headline result, and next intended action.\n"
        "- Do not wait until the end of the step to write progress.\n"
    )


def run_foreground(
    task: str | None,
    config_path: str | None = None,
    max_iterations: int | None = None,
    default_model: str | None = None,
    state_dir: str | None = None,
    timeout_seconds: int | None = None,
    idle_timeout_seconds: int | None = None,
    cleanup_on_error: str | None = None,
    force: bool = False,
    plan_path: str | None = None,
    plan_only: bool = False,
    plan_model: str | None = None,
    resume_run: str | None = None,
    ralph_config: RalphConfig | None = None,
    max_cost: float | None = None,
    max_duration_seconds: int | None = None,
    completion_consensus: int | None = None,
    verify_command: str | None = None,
    verify_timeout: int | None = None,
) -> None:
    """Run a ralphkit task in the foreground (pipe or loop mode)."""
    if ralph_config is not None:
        config = ralph_config
    else:
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

    if timeout_seconds is not None:
        if timeout_seconds < 1:
            print_error(
                f"Config error: timeout_seconds must be >= 1, got {timeout_seconds}"
            )
            sys.exit(1)
        config = replace(config, timeout_seconds=timeout_seconds)

    if idle_timeout_seconds is not None:
        if idle_timeout_seconds < 1:
            print_error(
                "Config error: idle_timeout_seconds must be >= 1, "
                f"got {idle_timeout_seconds}"
            )
            sys.exit(1)
        config = replace(config, idle_timeout_seconds=idle_timeout_seconds)

    if cleanup_on_error is not None:
        if cleanup_on_error not in {"full", "light", "skip"}:
            print_error(
                "Config error: cleanup_on_error must be one of: full, light, skip"
            )
            sys.exit(1)
        config = replace(config, cleanup_on_error=cleanup_on_error)

    if plan_model is not None:
        config = replace(config, plan_model=plan_model)

    if max_cost is not None:
        config = replace(config, max_cost=max_cost)

    if max_duration_seconds is not None:
        config = replace(config, max_duration_seconds=max_duration_seconds)

    if completion_consensus is not None:
        config = replace(config, completion_consensus=completion_consensus)

    if verify_command is not None:
        config = replace(config, verify_command=verify_command)

    if verify_timeout is not None:
        config = replace(config, verify_timeout=verify_timeout)

    state = StateDir(config.state_dir)
    state.setup(resume_run=resume_run)

    existing_task = state.read_task()
    if task is not None:
        task_content = resolve_task(task)
    elif existing_task is not None:
        task_content = existing_task
    elif config.pipe:
        task_content = None
    else:
        print_error("task is required for loop mode")
        raise SystemExit(1)

    if state.resumed and existing_task is not None and task is not None:
        if task_content != existing_task and not force:
            print_error(
                "resume run task does not match the existing task.md. "
                "Pass --force to overwrite it."
            )
            raise SystemExit(1)

    start_time = time.time()
    initial_report_duration = 0.0

    if state.resumed:
        report_path = state.path / "report.json"
        if report_path.is_file():
            report = RunReport.load(report_path)
            initial_report_duration = report.total_duration_s
            report.outcome = None
            report.failure_summary = None
        else:
            report = RunReport()
        state.write_resume_marker(str(resume_run))
    else:
        report = RunReport()

    if task_content is not None:
        if not state.resumed or existing_task is None or force:
            state.write_task(task_content)

    # -- Banner --
    is_pipe = bool(config.pipe)
    console.print()
    print_banner(f"RALPH {'PIPE' if is_pipe else 'LOOP'}")
    console.print()
    print_kv("Dir", str(Path.cwd()))
    print_kv("Run", f"#{state.path.name}")
    if is_pipe:
        print_kv("Steps", str(len(config.pipe)))
        print_kv("Pipe", _step_names(config.pipe))
    else:
        print_kv("Max iter", str(config.max_iterations))
        print_kv("Timeout", f"{config.timeout_seconds}s")
        if config.max_cost is not None:
            print_kv("Max cost", f"${config.max_cost:.2f}")
        if config.max_duration_seconds is not None:
            print_kv("Max time", fmt_duration(config.max_duration_seconds))
        print_kv("Consensus", str(config.completion_consensus))
        if config.setup:
            print_kv("Setup", _step_names(config.setup))
        print_kv("Loop", _step_names(config.loop))
        if config.cleanup:
            print_kv("Cleanup", _step_names(config.cleanup))
        if config.verify_command:
            print_kv("Verify", config.verify_command)
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
            raise SystemExit(1)
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

    run_failed = False
    report_finalized = False

    def _step_timeout_settings(step: StepConfig) -> tuple[int, int | None]:
        timeout_s = step.timeout_seconds or config.timeout_seconds
        idle_s = (
            step.idle_timeout_seconds
            if step.idle_timeout_seconds is not None
            else config.idle_timeout_seconds
        )
        return timeout_s, idle_s

    def _finalize_report() -> None:
        nonlocal report_finalized
        if report_finalized:
            return
        try:
            report.total_duration_s = initial_report_duration + (
                time.time() - start_time
            )
            print_report(report)
            report.save(state.path / "report.json")
            console.print(f"  [dim]Saved to {state.path / 'report.json'}[/]")
            report_finalized = True
        except Exception as e:
            try:
                print_warning(f"Failed to save report: {e}")
            except Exception:
                pass

    def _write_failure_summary(
        *,
        step_name: str | None,
        phase: str,
        iteration: int | None,
        status: str,
        error_kind: str,
        error_message: str,
        diagnostics_path: str | None,
        transcript_path: str | None = None,
        elapsed_s: float | None = None,
    ) -> None:
        failure_summary = {
            "step_name": step_name,
            "phase": phase,
            "iteration": iteration,
            "status": status,
            "error_kind": error_kind,
            "error_message": error_message,
            "diagnostics_path": diagnostics_path,
            "claude_transcript_path": transcript_path,
            "elapsed_s": elapsed_s,
        }
        report.failure_summary = failure_summary
        state.write_json("last_failure.json", failure_summary)
        if report.outcome is None:
            report.outcome = "ERROR"

    def _record_nonstep_failure(
        *,
        phase: str,
        error_kind: str,
        error_message: str,
        status: str = "error",
        step_name: str | None = None,
        iteration: int | None = None,
        extra: dict | None = None,
    ) -> None:
        nonlocal run_failed
        run_failed = True
        diagnostics_path = state.artifact_path(
            step_name or "run",
            phase,
            iteration,
            suffix="diagnostics.json",
        )
        payload = {
            "step_name": step_name,
            "phase": phase,
            "iteration": iteration,
            "cwd": str(Path.cwd()),
            "error": {
                "kind": error_kind,
                "message": error_message,
            },
        }
        if extra:
            payload.update(extra)
        diagnostics_path.write_text(json.dumps(payload, indent=2) + "\n")
        _write_failure_summary(
            step_name=step_name,
            phase=phase,
            iteration=iteration,
            status=status,
            error_kind=error_kind,
            error_message=error_message,
            diagnostics_path=str(diagnostics_path),
        )

    def _exit(
        code: int,
        *,
        outcome: str | None = None,
        finalize: bool = False,
    ) -> None:
        if outcome is not None:
            report.outcome = outcome
        if finalize:
            _finalize_report()
        raise SystemExit(code)

    def _record_failure(
        step,
        model: str,
        t0: float,
        phase: str,
        before_diff: tuple[int, int],
        error: RuntimeError,
        iteration: int | None = None,
    ) -> None:
        nonlocal run_failed
        run_failed = True
        before_add, before_del = before_diff
        after_add, after_del = git_diff_stat()
        diagnostics_path = state.artifact_path(
            step.step_name,
            phase,
            iteration,
            suffix="diagnostics.json",
        )
        status = "timeout"
        error_kind = type(error).__name__
        timeout_s = None
        idle_s = None
        transcript_path = None
        elapsed_s = time.time() - t0
        diagnostics: dict = {
            "step_name": step.step_name,
            "phase": phase,
            "iteration": iteration,
            "model": model,
            "cwd": str(Path.cwd()),
            "duration_s": elapsed_s,
            "lines_added": max(0, after_add - before_add),
            "lines_deleted": max(0, after_del - before_del),
            "error": {
                "message": str(error),
            },
        }

        if isinstance(error, ClaudeRunError):
            error_kind = error.kind
            status = "timeout" if "timeout" in error.kind else "error"
            timeout_s = error.timeout_seconds
            idle_s = error.idle_timeout_seconds
            transcript_path = error.transcript_path
            diagnostics["error"] = error.to_dict()
        else:
            status = "error"
            diagnostics["error"]["kind"] = error_kind

        diagnostics_path.write_text(json.dumps(diagnostics, indent=2) + "\n")
        report.record_step(
            step_name=step.step_name,
            model=model,
            phase=phase,
            status=status,
            duration_s=elapsed_s,
            iteration=iteration,
            error_kind=error_kind,
            error_message=str(error),
            timeout_seconds=timeout_s,
            idle_timeout_seconds=idle_s,
            diagnostics_path=str(diagnostics_path),
            claude_transcript_path=transcript_path,
            lines_added=max(0, after_add - before_add),
            lines_deleted=max(0, after_del - before_del),
        )
        _write_failure_summary(
            step_name=step.step_name,
            phase=phase,
            iteration=iteration,
            status=status,
            error_kind=error_kind,
            error_message=str(error),
            diagnostics_path=str(diagnostics_path),
            transcript_path=transcript_path,
            elapsed_s=elapsed_s,
        )
        if phase in ("setup", "planning") or config.cleanup_on_error != "full":
            _finalize_report()

    def _run_step(
        step: StepConfig,
        *,
        phase: str,
        before_diff: tuple[int, int],
        t0: float,
        iteration: int | None = None,
        extra_vars: dict[str, str] | None = None,
        system_suffix: str = "",
    ) -> tuple[str, dict | None]:
        """Run a step and return (model, claude_json_output)."""
        variables = _base_vars(step)
        if extra_vars:
            variables.update(extra_vars)
        prompt = _render_prompt(step.task_prompt, variables)
        system = _render_prompt(step.system_prompt, variables)
        suffixes = []
        if system_suffix:
            suffixes.append(system_suffix)
        suffixes.append(_checkpoint_suffix(str(state.active_path), step.step_name))
        system = system + "\n\n" + "\n\n".join(suffixes)
        model = variables["model"]
        timeout_s, idle_s = _step_timeout_settings(step)
        result = _run_phase(
            prompt,
            model,
            system,
            timeout_seconds=timeout_s,
            idle_timeout_seconds=idle_s,
            cwd=str(Path.cwd()),
            on_error=lambda error: _record_failure(
                step, model, t0, phase, before_diff, error, iteration
            ),
        )
        return model, result

    def _record_step(step, model, claude_out, t0, phase, before_diff, iteration=None):
        before_add, before_del = before_diff
        after_add, after_del = git_diff_stat()
        report.record_step(
            step_name=step.step_name,
            model=model,
            phase=phase,
            status="success",
            duration_s=time.time() - t0,
            iteration=iteration,
            claude_output=claude_out,
            claude_transcript_path=(
                claude_out.get("_ralphkit_transcript_path")
                if isinstance(claude_out, dict)
                else None
            ),
            lines_added=max(0, after_add - before_add),
            lines_deleted=max(0, after_del - before_del),
        )

    def _check_blocked() -> None:
        blocked = state.is_blocked()
        if blocked:
            _record_nonstep_failure(
                phase="blocked",
                error_kind="blocked",
                error_message=blocked,
            )
            console.print()
            console.print("[error]Blocked:[/]")
            console.print(blocked)
            _exit(1, outcome="BLOCKED")

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
                    step,
                    phase="pipe",
                    before_diff=before_diff,
                    t0=t0,
                    extra_vars=pipe_vars,
                    system_suffix=handoff,
                )
                _record_step(step, model, claude_out, t0, "pipe", before_diff)
                print_step_done(fmt_duration(time.time() - t0))

                _check_blocked()

            report.outcome = "PIPE_COMPLETE"
            console.print()
            print_outcome(
                f"PIPE COMPLETE \u2014 {total_steps} steps finished", success=True
            )
            _exit(0, outcome="PIPE_COMPLETE")
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
            model, claude_out = _run_step(
                step,
                phase="setup",
                before_diff=before_diff,
                t0=t0,
            )
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
            _record_nonstep_failure(
                phase="planning",
                error_kind="plan_not_found",
                error_message=f"Plan file not found: {plan_path}",
            )
            _exit(1, outcome="ERROR", finalize=True)
        try:
            plan = json.loads(pp.read_text())
        except (json.JSONDecodeError, TypeError) as e:
            print_error(f"Invalid plan file: {e}")
            _record_nonstep_failure(
                phase="planning",
                error_kind="invalid_plan_file",
                error_message=f"Invalid plan file: {e}",
            )
            _exit(1, outcome="ERROR", finalize=True)
        err = _validate_plan(plan)
        if err:
            print_error(f"Invalid plan file: {err}")
            _record_nonstep_failure(
                phase="planning",
                error_kind="invalid_plan_file",
                error_message=f"Invalid plan file: {err}",
            )
            _exit(1, outcome="ERROR", finalize=True)
        if state.resumed and (state.path / "tickets.json").exists() and not force:
            current_plan = state.read_plan()
            if current_plan != plan:
                print_error(
                    "resume run plan does not match the existing tickets.json. "
                    "Pass --force to overwrite it."
                )
                _record_nonstep_failure(
                    phase="planning",
                    error_kind="resume_plan_mismatch",
                    error_message=(
                        "resume run plan does not match the existing tickets.json."
                    ),
                )
                _exit(1, outcome="ERROR", finalize=True)
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
        claude_out = _run_phase(
            prompt,
            planner_model,
            system,
            timeout_seconds=config.timeout_seconds,
            idle_timeout_seconds=config.idle_timeout_seconds,
            cwd=str(Path.cwd()),
            on_error=lambda error: _record_failure(
                planner_step, planner_model, t0, "planning", before_diff, error
            ),
        )
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
            _record_nonstep_failure(
                phase="planning",
                error_kind="invalid_generated_plan",
                error_message=f"Planning failed: {err}",
            )
            _exit(1, outcome="ERROR", finalize=True)

    # Show plan summary
    items = plan.get("items", [])
    console.print()
    console.print(f"  [label]Plan:[/] {len(items)} items")
    print_plan_summary(plan)
    console.print()

    # --plan-only: exit after showing the plan
    if plan_only:
        # Ensure plan is written if provided via --plan
        if not (state.path / "tickets.json").exists():
            state.write_plan(plan)
        console.print(f"  Plan written to {state.path / 'tickets.json'}")
        _exit(0, outcome="PLAN_ONLY", finalize=True)

    # -- LOOP phase (with cleanup in finally) --
    total_loop_steps = len(config.loop)
    completion_signal_count = 0

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

            # Check for verify failure from previous iteration
            verify_suffix = ""
            verify_failure = state.read_verify_failure()
            if verify_failure:
                verify_suffix = (
                    "VERIFICATION FAILURE from previous iteration:\n"
                    f"The verification command failed. Read {state.active_path}/verify_failure.txt "
                    "and fix the issues before proceeding with your assigned item."
                )

            for idx, step in enumerate(config.loop, 1):
                step_model = resolve_model(step, config.default_model)
                print_step_start(idx, total_loop_steps, step.step_name, step_model)
                before_diff = git_diff_stat()
                t0 = time.time()
                model, claude_out = _run_step(
                    step,
                    phase="loop",
                    before_diff=before_diff,
                    t0=t0,
                    iteration=i,
                    extra_vars=loop_vars,
                    system_suffix=verify_suffix,
                )
                _record_step(
                    step, model, claude_out, t0, "loop", before_diff, iteration=i
                )
                print_step_done(fmt_duration(time.time() - t0))

                _check_blocked()

            # -- Run verify command if configured --
            if config.verify_command:
                console.print(f"  [dim]Running verify: {config.verify_command}[/]")
                try:
                    verify_proc = subprocess.run(
                        config.verify_command,
                        shell=True,
                        capture_output=True,
                        text=True,
                        timeout=config.verify_timeout,
                        cwd=str(Path.cwd()),
                    )
                    if verify_proc.returncode == 0:
                        console.print("  [green]Verification passed[/]")
                        # Clean up any previous failure
                        (state.path / "verify_failure.txt").unlink(missing_ok=True)
                    else:
                        output = (
                            verify_proc.stdout + "\n" + verify_proc.stderr
                        ).strip()
                        state.write_verify_failure(output)
                        console.print(
                            f"  [yellow]Verification failed (exit {verify_proc.returncode})[/]"
                        )
                except subprocess.TimeoutExpired:
                    state.write_verify_failure(
                        f"Verification command timed out after {config.verify_timeout}s"
                    )
                    console.print("  [yellow]Verification timed out[/]")

            # Re-read plan after worker runs (1 file read)
            plan = state.read_plan()
            if plan is None:
                print_error("Worker corrupted tickets.json (invalid JSON).")
                _record_nonstep_failure(
                    phase="loop",
                    error_kind="invalid_plan_json",
                    error_message="Worker corrupted tickets.json (invalid JSON).",
                    iteration=i,
                )
                _exit(1, outcome="ERROR")

            plan_items = plan.get("items", [])
            done_count = sum(1 for it in plan_items if it.get("done", False))
            total_count = len(plan_items)
            all_done = done_count == total_count
            report.items_completed = done_count
            report.items_total = total_count

            # Show iteration summary
            elapsed = time.time() - iter_start
            cost_str = ""
            cost = report.estimated_cost_usd()
            if cost > 0:
                cost_str = f"  [dim]Cost: ${cost:.2f}[/]"
            console.print()
            print_plan_progress(done_count, total_count)
            console.print(
                f"  [dim]Iteration {i} completed in {fmt_duration(elapsed)}[/]{cost_str}"
            )

            # -- Check completion signal (RALPH-COMPLETE.md) --
            complete_msg = state.is_complete()
            if complete_msg:
                completion_signal_count += 1
                console.print(
                    f"  [dim]Completion signal {completion_signal_count}/{config.completion_consensus}[/]"
                )
                if completion_signal_count >= config.completion_consensus:
                    console.print()
                    print_outcome(
                        f"COMPLETE (signaled) \u2014 {done_count}/{total_count} items, "
                        f"{i} iteration(s)",
                        success=True,
                    )
                    _exit(0, outcome="COMPLETE_SIGNALED")
            else:
                completion_signal_count = 0

            # -- Check all plan items done --
            if all_done:
                report.outcome = "COMPLETE"
                console.print()
                print_outcome(
                    f"COMPLETE \u2014 All {total_count} items done in {i} iteration(s)!",
                    success=True,
                )
                _exit(0, outcome="COMPLETE")

            # -- Check max cost --
            if config.max_cost is not None and cost >= config.max_cost:
                console.print()
                print_outcome(
                    f"Max cost (${config.max_cost:.2f}) reached. "
                    f"{done_count}/{total_count} items completed. "
                    f"Spent ~${cost:.2f}.",
                    success=False,
                )
                _exit(1, outcome="MAX_COST")

            # -- Check max duration --
            if config.max_duration_seconds is not None:
                wall_time = time.time() - start_time
                if wall_time >= config.max_duration_seconds:
                    console.print()
                    print_outcome(
                        f"Max duration ({fmt_duration(config.max_duration_seconds)}) reached. "
                        f"{done_count}/{total_count} items completed.",
                        success=False,
                    )
                    _exit(1, outcome="MAX_DURATION")

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
        _exit(1, outcome="MAX_ITERATIONS")
    finally:
        if report.outcome is None:
            report.outcome = "ERROR"
        # -- CLEANUP phase (always runs) --
        if config.cleanup and (not run_failed or config.cleanup_on_error == "full"):
            console.print()
            print_rule("Cleanup")
            total_cleanup = len(config.cleanup)
            for idx, step in enumerate(config.cleanup, 1):
                print_step_start(idx, total_cleanup, step.step_name)
                before_diff = git_diff_stat()
                t0 = time.time()
                try:
                    model, claude_out = _run_step(
                        step,
                        phase="cleanup",
                        before_diff=before_diff,
                        t0=t0,
                    )
                    _record_step(step, model, claude_out, t0, "cleanup", before_diff)
                    print_step_done(fmt_duration(time.time() - t0))
                except SystemExit:
                    print_warning(
                        f"Cleanup step '{step.step_name}' failed, continuing..."
                    )
            console.print()
        elif config.cleanup and run_failed and config.cleanup_on_error == "light":
            console.print()
            print_warning(
                "Skipping Claude cleanup steps due to cleanup_on_error=light."
            )
            console.print()
        elif config.cleanup and run_failed and config.cleanup_on_error == "skip":
            console.print()
            print_warning("Skipping cleanup phase due to cleanup_on_error=skip.")
            console.print()
        _finalize_report()
