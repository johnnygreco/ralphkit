import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from ralphkit.cli import (
    main,
    _build_default_handoff,
    _render_prompt,
    _resolve_handoff,
    _run_phase,
    _step_names,
)
from ralphkit.config import STATE_DIR, VERDICT_REVISE, VERDICT_SHIP, StepConfig


# ── Helper ──────────────────────────────────────────────────────────


def _minimal_config_with_two_loop_steps():
    return """\
max_iterations: 1
default_model: opus
loop:
  - step_name: worker
    task_prompt: "Work."
    system_prompt: "System."
  - step_name: reviewer
    task_prompt: "Review."
    system_prompt: "System."
"""


# ── _render_prompt ───────────────────────────────────────────────────


def test_render_prompt_single_variable():
    assert _render_prompt("{task}", {"task": "build it"}) == "build it"


def test_render_prompt_multiple_variables():
    result = _render_prompt(
        "{step_name} on iter {iteration}",
        {"step_name": "worker", "iteration": "3"},
    )
    assert result == "worker on iter 3"


def test_render_prompt_missing_key_preserved():
    assert _render_prompt("{unknown}", {}) == "{unknown}"


def test_render_prompt_mix_present_and_missing():
    result = _render_prompt("{a} and {b}", {"a": "yes"})
    assert result == "yes and {b}"


def test_render_prompt_empty_template():
    assert _render_prompt("", {"a": "1"}) == ""


def test_render_prompt_no_placeholders():
    assert _render_prompt("plain text", {"a": "1"}) == "plain text"


def test_render_prompt_empty_variables():
    assert _render_prompt("{x} {y}", {}) == "{x} {y}"


def test_render_prompt_repeated_placeholder():
    assert _render_prompt("{x} {x}", {"x": "hi"}) == "hi hi"


# ── _step_names ──────────────────────────────────────────────────────


def test_step_names_empty():
    assert _step_names([]) == "(none)"


def test_step_names_single():
    steps = [StepConfig(step_name="worker", task_prompt="p", system_prompt="s")]
    assert _step_names(steps) == "worker"


def test_step_names_multiple():
    steps = [
        StepConfig(step_name="worker", task_prompt="p", system_prompt="s"),
        StepConfig(step_name="reviewer", task_prompt="p", system_prompt="s"),
    ]
    assert _step_names(steps) == "worker, reviewer"


# ── _run_phase ───────────────────────────────────────────────────────


@patch("ralphkit.cli.run_claude")
def test_run_phase_success(mock_run):
    _run_phase("prompt", "model", "system")
    mock_run.assert_called_once_with("prompt", "model", "system")


@patch("ralphkit.cli.run_claude", side_effect=RuntimeError("boom"))
def test_run_phase_runtime_error_exits(mock_run):
    with pytest.raises(SystemExit) as exc_info:
        _run_phase("p", "m", "s")
    assert exc_info.value.code == 1


@patch("ralphkit.cli.run_claude", side_effect=RuntimeError("boom"))
def test_run_phase_runtime_error_prints_to_stderr(mock_run, capsys):
    with pytest.raises(SystemExit):
        _run_phase("p", "m", "s")
    assert "boom" in capsys.readouterr().err


@patch("ralphkit.cli.run_claude", side_effect=TypeError("unexpected"))
def test_run_phase_non_runtime_error_propagates(mock_run):
    with pytest.raises(TypeError, match="unexpected"):
        _run_phase("p", "m", "s")


# ── main() ───────────────────────────────────────────────────────────


def _minimal_config_yaml():
    return """\
max_iterations: 3
default_model: opus
loop:
  - step_name: worker
    task_prompt: "Work."
    system_prompt: "System."
"""


@patch("ralphkit.cli.run_claude")
def test_main_missing_task_arg(mock_run, monkeypatch, tmp_path):
    cfg = tmp_path / "ralph.yaml"
    cfg.write_text(_minimal_config_yaml())
    monkeypatch.setattr(sys, "argv", ["ralph-loop", "--config", str(cfg)])
    with pytest.raises(SystemExit) as exc_info:
        main()
    assert exc_info.value.code == 2


@patch("ralphkit.cli.run_claude")
def test_main_config_error_exits(mock_run, monkeypatch, tmp_path):
    bad_cfg = tmp_path / "bad.yaml"
    bad_cfg.write_text("max_iterations: 5\n")
    monkeypatch.setattr(
        sys, "argv", ["ralph-loop", "task", "--config", str(bad_cfg), "-f"]
    )
    with pytest.raises(SystemExit) as exc_info:
        main()
    assert exc_info.value.code == 1


@pytest.mark.parametrize("value", ["0", "-1"])
@patch("ralphkit.cli.run_claude")
def test_main_max_iterations_invalid_exits(mock_run, monkeypatch, tmp_path, value):
    cfg = tmp_path / "ralph.yaml"
    cfg.write_text(_minimal_config_yaml())
    monkeypatch.setattr(
        sys,
        "argv",
        ["ralph-loop", "task", "--config", str(cfg), "--max-iterations", value, "-f"],
    )
    with pytest.raises(SystemExit) as exc_info:
        main()
    assert exc_info.value.code == 1


@patch("ralphkit.cli.run_claude")
def test_main_ship_on_first_iteration(mock_run, monkeypatch, tmp_path):
    """Full integration: loop runs once, reviewer SHIPs, exits 0."""
    cfg = tmp_path / "ralph.yaml"
    cfg.write_text(_minimal_config_yaml())
    monkeypatch.setattr(
        sys, "argv", ["ralph-loop", "do stuff", "--config", str(cfg), "-f"]
    )
    monkeypatch.chdir(tmp_path)

    state_dir = tmp_path / STATE_DIR / "current"

    def fake_claude(prompt, model, system_prompt):
        (state_dir / "review-result.md").write_text(VERDICT_SHIP)

    mock_run.side_effect = fake_claude

    with pytest.raises(SystemExit) as exc_info:
        main()
    assert exc_info.value.code == 0

    # report.json should be written
    report_path = tmp_path / STATE_DIR / "runs" / "001" / "report.json"
    assert report_path.exists()
    data = json.loads(report_path.read_text())
    assert data["outcome"] == "SHIP"
    assert isinstance(data["steps"], list)


@patch("ralphkit.cli.run_claude")
def test_main_revise_then_ship(mock_run, monkeypatch, tmp_path):
    """Loop runs twice: first REVISE, then SHIP."""
    cfg = tmp_path / "ralph.yaml"
    cfg.write_text(_minimal_config_yaml())
    monkeypatch.setattr(
        sys, "argv", ["ralph-loop", "do stuff", "--config", str(cfg), "-f"]
    )
    monkeypatch.chdir(tmp_path)

    state_dir = tmp_path / STATE_DIR / "current"
    call_count = {"n": 0}

    def fake_claude(prompt, model, system_prompt):
        call_count["n"] += 1
        if call_count["n"] == 1:
            (state_dir / "review-result.md").write_text(VERDICT_REVISE)
            (state_dir / "review-feedback.md").write_text("fix it")
        else:
            (state_dir / "review-result.md").write_text(VERDICT_SHIP)

    mock_run.side_effect = fake_claude

    with pytest.raises(SystemExit) as exc_info:
        main()
    assert exc_info.value.code == 0
    assert call_count["n"] == 2


@patch("ralphkit.cli.run_claude")
def test_main_max_iterations_reached(mock_run, monkeypatch, tmp_path):
    """Loop exhausts max iterations without SHIP."""
    cfg = tmp_path / "ralph.yaml"
    cfg.write_text(
        """\
max_iterations: 2
default_model: opus
loop:
  - step_name: worker
    task_prompt: "Work."
    system_prompt: "System."
"""
    )
    monkeypatch.setattr(
        sys, "argv", ["ralph-loop", "do stuff", "--config", str(cfg), "-f"]
    )
    monkeypatch.chdir(tmp_path)

    state_dir = tmp_path / STATE_DIR / "current"

    def fake_claude(prompt, model, system_prompt):
        (state_dir / "review-result.md").write_text(VERDICT_REVISE)
        (state_dir / "review-feedback.md").write_text("more work")

    mock_run.side_effect = fake_claude

    with pytest.raises(SystemExit) as exc_info:
        main()
    assert exc_info.value.code == 1


@patch("ralphkit.cli.run_claude")
def test_main_no_review_result_exits(mock_run, monkeypatch, tmp_path):
    """Loop step produces no review-result.md -> exit 1."""
    cfg = tmp_path / "ralph.yaml"
    cfg.write_text(_minimal_config_yaml())
    monkeypatch.setattr(
        sys, "argv", ["ralph-loop", "do stuff", "--config", str(cfg), "-f"]
    )
    monkeypatch.chdir(tmp_path)

    with pytest.raises(SystemExit) as exc_info:
        main()
    assert exc_info.value.code == 1


@patch("ralphkit.cli.run_claude")
def test_main_blocked_exits(mock_run, monkeypatch, tmp_path):
    """Blocked state after a step -> exit 1."""
    cfg = tmp_path / "ralph.yaml"
    cfg.write_text(_minimal_config_yaml())
    monkeypatch.setattr(
        sys, "argv", ["ralph-loop", "do stuff", "--config", str(cfg), "-f"]
    )
    monkeypatch.chdir(tmp_path)

    state_dir = tmp_path / STATE_DIR / "current"

    def fake_claude(prompt, model, system_prompt):
        (state_dir / "RALPH-BLOCKED.md").write_text("stuck")

    mock_run.side_effect = fake_claude

    with pytest.raises(SystemExit) as exc_info:
        main()
    assert exc_info.value.code == 1


@patch("ralphkit.cli.run_claude")
def test_main_unexpected_review_result_exits(mock_run, monkeypatch, tmp_path):
    """Unknown review result string -> exit 1."""
    cfg = tmp_path / "ralph.yaml"
    cfg.write_text(_minimal_config_yaml())
    monkeypatch.setattr(
        sys, "argv", ["ralph-loop", "do stuff", "--config", str(cfg), "-f"]
    )
    monkeypatch.chdir(tmp_path)

    state_dir = tmp_path / STATE_DIR / "current"

    def fake_claude(prompt, model, system_prompt):
        (state_dir / "review-result.md").write_text("MAYBE")

    mock_run.side_effect = fake_claude

    with pytest.raises(SystemExit) as exc_info:
        main()
    assert exc_info.value.code == 1


@patch("ralphkit.cli.run_claude")
def test_main_setup_and_cleanup_phases(mock_run, monkeypatch, tmp_path):
    """Setup and cleanup steps execute around the loop."""
    cfg = tmp_path / "ralph.yaml"
    cfg.write_text(
        """\
max_iterations: 1
default_model: opus
setup:
  - step_name: init
    task_prompt: "Init."
    system_prompt: "Setup."
loop:
  - step_name: worker
    task_prompt: "Work."
    system_prompt: "System."
cleanup:
  - step_name: finalize
    task_prompt: "Cleanup."
    system_prompt: "Cleanup system."
"""
    )
    monkeypatch.setattr(
        sys, "argv", ["ralph-loop", "do stuff", "--config", str(cfg), "-f"]
    )
    monkeypatch.chdir(tmp_path)

    state_dir = tmp_path / STATE_DIR / "current"
    calls = []

    def fake_claude(prompt, model, system_prompt):
        calls.append(prompt)
        if "Work." in prompt:
            (state_dir / "review-result.md").write_text(VERDICT_SHIP)

    mock_run.side_effect = fake_claude

    with pytest.raises(SystemExit) as exc_info:
        main()
    assert exc_info.value.code == 0
    assert len(calls) == 3  # setup + loop + cleanup
    assert "Init." in calls[0]
    assert "Work." in calls[1]
    assert "Cleanup." in calls[2]


# ── --list-runs ────────────────────────────────────────────────────


@patch("ralphkit.cli.run_claude")
def test_main_list_runs_empty(mock_run, monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(
        sys,
        "argv",
        ["ralph-loop", "--list-runs", "--state-dir", str(tmp_path / STATE_DIR)],
    )
    with pytest.raises(SystemExit) as exc_info:
        main()
    assert exc_info.value.code == 0
    assert "No runs found." in capsys.readouterr().out


@patch("ralphkit.cli.run_claude")
def test_main_list_runs_shows_runs(mock_run, monkeypatch, tmp_path, capsys):
    """--list-runs shows numbered runs with task first lines."""
    # Set up some runs manually
    state_root = tmp_path / STATE_DIR
    runs_dir = state_root / "runs"
    (runs_dir / "001").mkdir(parents=True)
    (runs_dir / "001" / "task.md").write_text("first task\ndetails")
    (runs_dir / "002").mkdir()
    (runs_dir / "002" / "task.md").write_text("second task")

    monkeypatch.setattr(
        sys, "argv", ["ralph-loop", "--list-runs", "--state-dir", str(state_root)]
    )
    with pytest.raises(SystemExit) as exc_info:
        main()
    assert exc_info.value.code == 0
    out = capsys.readouterr().out
    assert "#001" in out
    assert "first task" in out
    assert "#002" in out
    assert "second task" in out


# ── Run number in banner ──────────────────────────────────────────


@patch("ralphkit.cli.run_claude")
def test_main_shows_run_number(mock_run, monkeypatch, tmp_path, capsys):
    cfg = tmp_path / "ralph.yaml"
    cfg.write_text(_minimal_config_yaml())
    monkeypatch.setattr(
        sys, "argv", ["ralph-loop", "do stuff", "--config", str(cfg), "-f"]
    )
    monkeypatch.chdir(tmp_path)

    state_dir = tmp_path / STATE_DIR / "current"

    def fake_claude(prompt, model, system_prompt):
        (state_dir / "review-result.md").write_text(VERDICT_SHIP)

    mock_run.side_effect = fake_claude

    with pytest.raises(SystemExit) as exc_info:
        main()
    assert exc_info.value.code == 0
    assert "#001" in capsys.readouterr().out


# ── No existing task proceeds ─────────────────────────────────────


@patch("ralphkit.cli.run_claude")
def test_main_no_existing_task_proceeds(mock_run, monkeypatch, tmp_path):
    """No existing task.md -> proceeds normally."""
    cfg = tmp_path / "ralph.yaml"
    cfg.write_text(_minimal_config_yaml())
    monkeypatch.setattr(
        sys, "argv", ["ralph-loop", "do stuff", "--config", str(cfg), "-f"]
    )
    monkeypatch.chdir(tmp_path)

    state_dir = tmp_path / STATE_DIR / "current"

    def fake_claude(prompt, model, system_prompt):
        (state_dir / "review-result.md").write_text(VERDICT_SHIP)

    mock_run.side_effect = fake_claude

    with pytest.raises(SystemExit) as exc_info:
        main()
    assert exc_info.value.code == 0


# ── Timing and step numbering ──────────────────────────────────────


@patch("ralphkit.cli.time")
@patch("ralphkit.cli.run_claude")
def test_main_shows_step_numbering(mock_run, mock_time, monkeypatch, tmp_path, capsys):
    """Step numbering [N/M] appears in output."""
    cfg = tmp_path / "ralph.yaml"
    cfg.write_text(_minimal_config_with_two_loop_steps())
    monkeypatch.setattr(
        sys, "argv", ["ralph-loop", "do stuff", "--config", str(cfg), "-f"]
    )
    monkeypatch.chdir(tmp_path)

    state_dir = tmp_path / STATE_DIR / "current"
    mock_time.time.return_value = 100.0

    def fake_claude(prompt, model, system_prompt):
        if "Review." in prompt:
            (state_dir / "review-result.md").write_text(VERDICT_SHIP)

    mock_run.side_effect = fake_claude

    with pytest.raises(SystemExit) as exc_info:
        main()
    assert exc_info.value.code == 0

    out = capsys.readouterr().out
    assert "[1/2]" in out
    assert "[2/2]" in out


@patch("ralphkit.cli.time")
@patch("ralphkit.cli.run_claude")
def test_main_shows_timing(mock_run, mock_time, monkeypatch, tmp_path, capsys):
    """Timing output appears for steps, iteration, and total."""
    cfg = tmp_path / "ralph.yaml"
    cfg.write_text(_minimal_config_yaml())
    monkeypatch.setattr(
        sys, "argv", ["ralph-loop", "do stuff", "--config", str(cfg), "-f"]
    )
    monkeypatch.chdir(tmp_path)

    state_dir = tmp_path / STATE_DIR / "current"
    # time.time() calls: start_time, iter_start, step_t0, step_end(x2), iter_end, total(x2)
    mock_time.time.return_value = 142.1
    # Override first few calls to control step elapsed
    call_count = {"n": 0}
    times = [100.0, 100.0, 100.0, 114.3]  # start, iter_start, step_t0, step_end

    def fake_time():
        call_count["n"] += 1
        if call_count["n"] <= len(times):
            return times[call_count["n"] - 1]
        return 142.1

    mock_time.time.side_effect = fake_time

    def fake_claude(prompt, model, system_prompt):
        (state_dir / "review-result.md").write_text(VERDICT_SHIP)

    mock_run.side_effect = fake_claude

    with pytest.raises(SystemExit) as exc_info:
        main()
    assert exc_info.value.code == 0

    out = capsys.readouterr().out
    assert "14.3s" in out  # step elapsed
    assert "Total time:" in out


# ── Run directory invariants ─────────────────────────────────────────


@patch("ralphkit.cli.run_claude")
def test_main_multiple_iterations_single_run_directory(mock_run, monkeypatch, tmp_path):
    """A full loop with REVISE then SHIP must create exactly one run directory."""
    cfg = tmp_path / "ralph.yaml"
    cfg.write_text(_minimal_config_yaml())
    monkeypatch.setattr(
        sys, "argv", ["ralph-loop", "do stuff", "--config", str(cfg), "-f"]
    )
    monkeypatch.chdir(tmp_path)

    state_dir = tmp_path / STATE_DIR / "current"
    call_count = {"n": 0}

    def fake_claude(prompt, model, system_prompt):
        call_count["n"] += 1
        if call_count["n"] == 1:
            (state_dir / "review-result.md").write_text(VERDICT_REVISE)
            (state_dir / "review-feedback.md").write_text("add tests")
        else:
            (state_dir / "review-result.md").write_text(VERDICT_SHIP)

    mock_run.side_effect = fake_claude

    with pytest.raises(SystemExit) as exc_info:
        main()
    assert exc_info.value.code == 0

    runs_dir = tmp_path / STATE_DIR / "runs"
    run_dirs = sorted(d.name for d in runs_dir.iterdir() if d.is_dir())
    assert run_dirs == ["001"]


@patch("ralphkit.cli.run_claude")
def test_main_two_invocations_create_two_runs(mock_run, monkeypatch, tmp_path):
    """Two sequential ralph-loop invocations create runs 001 and 002, not more."""
    cfg = tmp_path / "ralph.yaml"
    cfg.write_text(_minimal_config_yaml())
    monkeypatch.chdir(tmp_path)

    state_dir = tmp_path / STATE_DIR / "current"

    def fake_claude(prompt, model, system_prompt):
        (state_dir / "review-result.md").write_text(VERDICT_SHIP)

    mock_run.side_effect = fake_claude

    # First invocation
    monkeypatch.setattr(
        sys, "argv", ["ralph-loop", "task one", "--config", str(cfg), "-f"]
    )
    with pytest.raises(SystemExit) as exc_info:
        main()
    assert exc_info.value.code == 0

    # Second invocation
    monkeypatch.setattr(
        sys, "argv", ["ralph-loop", "task two", "--config", str(cfg), "-f"]
    )
    with pytest.raises(SystemExit) as exc_info:
        main()
    assert exc_info.value.code == 0

    runs_dir = tmp_path / STATE_DIR / "runs"
    run_dirs = sorted(d.name for d in runs_dir.iterdir() if d.is_dir())
    assert run_dirs == ["001", "002"]
    assert (runs_dir / "001" / "task.md").read_text() == "task one"
    assert (runs_dir / "002" / "task.md").read_text() == "task two"


@patch("ralphkit.cli.run_claude")
def test_main_prompts_use_symlink_path(mock_run, monkeypatch, tmp_path):
    """Prompt templates receive the 'current' symlink as state_dir, not the run dir."""
    cfg = tmp_path / "ralph.yaml"
    cfg.write_text("""\
max_iterations: 3
default_model: opus
loop:
  - step_name: worker
    task_prompt: "Read {state_dir}/task.md"
    system_prompt: "System."
""")
    monkeypatch.setattr(
        sys, "argv", ["ralph-loop", "do stuff", "--config", str(cfg), "-f"]
    )
    monkeypatch.chdir(tmp_path)

    state_dir = tmp_path / STATE_DIR / "current"
    captured_prompts = []

    def fake_claude(prompt, model, system_prompt):
        captured_prompts.append(prompt)
        (state_dir / "review-result.md").write_text(VERDICT_SHIP)

    mock_run.side_effect = fake_claude

    with pytest.raises(SystemExit):
        main()

    expected_suffix = str(Path(STATE_DIR) / "current")
    assert any(expected_suffix in p for p in captured_prompts)
    # Must NOT contain the raw run dir path
    assert not any("runs/001" in p for p in captured_prompts)


# ── Pipe tests ───────────────────────────────────────────────────────


def _pipe_config_yaml():
    return """\
default_model: opus
pipe:
  - step_name: analyze
    task_prompt: "Analyze the code."
    system_prompt: "You are an analyst."
  - step_name: plan
    task_prompt: "Create a plan."
    system_prompt: "You are a planner."
  - step_name: implement
    task_prompt: "Implement the plan."
    system_prompt: "You are a developer."
"""


@patch("ralphkit.cli.run_claude")
def test_main_pipe_runs_all_steps(mock_run, monkeypatch, tmp_path):
    """Pipe config runs all steps exactly once and exits 0."""
    cfg = tmp_path / "pipe.yaml"
    cfg.write_text(_pipe_config_yaml())
    monkeypatch.setattr(sys, "argv", ["ralph", "--config", str(cfg), "-f"])
    monkeypatch.chdir(tmp_path)

    calls = []

    def fake_claude(prompt, model, system_prompt):
        calls.append(prompt)

    mock_run.side_effect = fake_claude

    with pytest.raises(SystemExit) as exc_info:
        main()
    assert exc_info.value.code == 0
    assert len(calls) == 3

    # report.json should be written for pipe runs too
    report_path = tmp_path / STATE_DIR / "runs" / "001" / "report.json"
    assert report_path.exists()
    data = json.loads(report_path.read_text())
    assert data["outcome"] == "PIPE_COMPLETE"
    assert len(data["steps"]) == 3


@patch("ralphkit.cli.run_claude")
def test_main_pipe_no_task_succeeds(mock_run, monkeypatch, tmp_path):
    """Pipe config with no task arg succeeds."""
    cfg = tmp_path / "pipe.yaml"
    cfg.write_text(_pipe_config_yaml())
    monkeypatch.setattr(sys, "argv", ["ralph", "--config", str(cfg), "-f"])
    monkeypatch.chdir(tmp_path)

    mock_run.side_effect = lambda *a: None

    with pytest.raises(SystemExit) as exc_info:
        main()
    assert exc_info.value.code == 0
    # No task.md should be created
    assert not (tmp_path / STATE_DIR / "current" / "task.md").exists()


@patch("ralphkit.cli.run_claude")
def test_main_pipe_with_task(mock_run, monkeypatch, tmp_path):
    """Pipe config + task arg writes task.md and makes {task} available."""
    cfg = tmp_path / "pipe.yaml"
    cfg.write_text(
        """\
default_model: opus
pipe:
  - step_name: step1
    task_prompt: "Do: {task}"
    system_prompt: "System."
"""
    )
    monkeypatch.setattr(
        sys, "argv", ["ralph", "refactor auth", "--config", str(cfg), "-f"]
    )
    monkeypatch.chdir(tmp_path)

    captured_prompts = []

    def fake_claude(prompt, model, system_prompt):
        captured_prompts.append(prompt)

    mock_run.side_effect = fake_claude

    with pytest.raises(SystemExit) as exc_info:
        main()
    assert exc_info.value.code == 0
    assert (tmp_path / STATE_DIR / "current" / "task.md").read_text() == "refactor auth"
    assert captured_prompts[0] == "Do: refactor auth"


@patch("ralphkit.cli.run_claude")
def test_main_pipe_blocked_aborts(mock_run, monkeypatch, tmp_path):
    """Blocked state during pipe execution exits 1."""
    cfg = tmp_path / "pipe.yaml"
    cfg.write_text(_pipe_config_yaml())
    monkeypatch.setattr(sys, "argv", ["ralph", "--config", str(cfg), "-f"])
    monkeypatch.chdir(tmp_path)

    state_dir = tmp_path / STATE_DIR / "current"

    def fake_claude(prompt, model, system_prompt):
        (state_dir / "RALPH-BLOCKED.md").write_text("stuck")

    mock_run.side_effect = fake_claude

    with pytest.raises(SystemExit) as exc_info:
        main()
    assert exc_info.value.code == 1


@patch("ralphkit.cli.run_claude")
def test_main_pipe_shows_banner(mock_run, monkeypatch, tmp_path, capsys):
    """Pipe banner shows RALPH PIPE and step names."""
    cfg = tmp_path / "pipe.yaml"
    cfg.write_text(_pipe_config_yaml())
    monkeypatch.setattr(sys, "argv", ["ralph", "--config", str(cfg), "-f"])
    monkeypatch.chdir(tmp_path)

    mock_run.side_effect = lambda *a: None

    with pytest.raises(SystemExit) as exc_info:
        main()
    assert exc_info.value.code == 0

    out = capsys.readouterr().out
    assert "RALPH PIPE" in out
    assert "analyze, plan, implement" in out
    assert "Steps:" in out
    assert "PIPE COMPLETE" in out


@patch("ralphkit.cli.run_claude")
def test_main_pipe_handoff_in_system_prompt(mock_run, monkeypatch, tmp_path):
    """Default handoff instructions are appended to system_prompt."""
    cfg = tmp_path / "pipe.yaml"
    cfg.write_text(
        """\
default_model: opus
pipe:
  - step_name: step1
    task_prompt: "Work."
    system_prompt: "You are step1."
  - step_name: step2
    task_prompt: "Work."
    system_prompt: "You are step2."
"""
    )
    monkeypatch.setattr(sys, "argv", ["ralph", "--config", str(cfg), "-f"])
    monkeypatch.chdir(tmp_path)

    captured_systems = []

    def fake_claude(prompt, model, system_prompt):
        captured_systems.append(system_prompt)

    mock_run.side_effect = fake_claude

    with pytest.raises(SystemExit) as exc_info:
        main()
    assert exc_info.value.code == 0

    # First step: should have write instruction for handoff to step2, no read
    assert "handoff__step1__to__step2" in captured_systems[0]
    assert (
        "handoff__"
        not in captured_systems[0]
        .split("handoff__step1__to__step2")[0]
        .rsplit("task.md", 1)[0]
    )

    # Last step: should have read instruction from step1, no write
    assert "handoff__step1__to__step2" in captured_systems[1]


@patch("ralphkit.cli.run_claude")
def test_main_pipe_step_handoff_prompt_override(mock_run, monkeypatch, tmp_path):
    """Step-level handoff_prompt overrides the default."""
    cfg = tmp_path / "pipe.yaml"
    cfg.write_text(
        """\
default_model: opus
pipe:
  - step_name: step1
    task_prompt: "Work."
    system_prompt: "You are step1."
    handoff_prompt: "CUSTOM HANDOFF"
  - step_name: step2
    task_prompt: "Work."
    system_prompt: "You are step2."
"""
    )
    monkeypatch.setattr(sys, "argv", ["ralph", "--config", str(cfg), "-f"])
    monkeypatch.chdir(tmp_path)

    captured_systems = []

    def fake_claude(prompt, model, system_prompt):
        captured_systems.append(system_prompt)

    mock_run.side_effect = fake_claude

    with pytest.raises(SystemExit) as exc_info:
        main()
    assert exc_info.value.code == 0

    # Step 1 should use custom handoff
    assert "CUSTOM HANDOFF" in captured_systems[0]
    # Step 2 should use default (has read instruction)
    assert "handoff__step1__to__step2" in captured_systems[1]


@patch("ralphkit.cli.run_claude")
def test_main_pipe_empty_handoff_prompt_disables(mock_run, monkeypatch, tmp_path):
    """Empty string handoff_prompt disables handoff injection."""
    cfg = tmp_path / "pipe.yaml"
    cfg.write_text(
        """\
default_model: opus
pipe:
  - step_name: step1
    task_prompt: "Work."
    system_prompt: "You are step1."
    handoff_prompt: ""
"""
    )
    monkeypatch.setattr(sys, "argv", ["ralph", "--config", str(cfg), "-f"])
    monkeypatch.chdir(tmp_path)

    captured_systems = []

    def fake_claude(prompt, model, system_prompt):
        captured_systems.append(system_prompt)

    mock_run.side_effect = fake_claude

    with pytest.raises(SystemExit) as exc_info:
        main()
    assert exc_info.value.code == 0

    # System prompt should be just the original, no handoff appended
    assert captured_systems[0] == "You are step1."


# ── _build_default_handoff ───────────────────────────────────────────


def test_build_default_handoff_first_step():
    steps = [
        StepConfig(step_name="a", task_prompt="", system_prompt=""),
        StepConfig(step_name="b", task_prompt="", system_prompt=""),
    ]
    result = _build_default_handoff(1, 2, steps, ".ralphkit/current")
    # First step: write handoff, no read
    assert "handoff__a__to__b" in result
    assert "Write" in result or "write" in result
    assert "Read" not in result.split("task.md")[0]  # no read before task.md mention


def test_build_default_handoff_last_step():
    steps = [
        StepConfig(step_name="a", task_prompt="", system_prompt=""),
        StepConfig(step_name="b", task_prompt="", system_prompt=""),
    ]
    result = _build_default_handoff(2, 2, steps, ".ralphkit/current")
    # Last step: read handoff, no write
    assert "handoff__a__to__b" in result
    assert "Read" in result or "read" in result


def test_build_default_handoff_middle_step():
    steps = [
        StepConfig(step_name="a", task_prompt="", system_prompt=""),
        StepConfig(step_name="b", task_prompt="", system_prompt=""),
        StepConfig(step_name="c", task_prompt="", system_prompt=""),
    ]
    result = _build_default_handoff(2, 3, steps, ".ralphkit/current")
    # Middle step: read from a, write to c
    assert "handoff__a__to__b" in result
    assert "handoff__b__to__c" in result


# ── _resolve_handoff ────────────────────────────────────────────────


def test_resolve_handoff_step_level_wins():
    step = StepConfig(
        step_name="s", task_prompt="", system_prompt="", handoff_prompt="STEP"
    )
    result = _resolve_handoff(step, "CONFIG", 1, 1, [step], "dir")
    assert result == "STEP"


def test_resolve_handoff_config_level_wins_over_default():
    step = StepConfig(step_name="s", task_prompt="", system_prompt="")
    result = _resolve_handoff(step, "CONFIG", 1, 1, [step], "dir")
    assert result == "CONFIG"


def test_resolve_handoff_falls_back_to_default():
    step = StepConfig(step_name="s", task_prompt="", system_prompt="")
    result = _resolve_handoff(step, None, 1, 1, [step], "dir")
    assert "task.md" in result  # default always mentions task.md
