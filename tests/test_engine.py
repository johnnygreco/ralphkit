import json
import re
from pathlib import Path
from unittest.mock import patch

import pytest

from ralphkit.engine import (
    _build_default_handoff,
    _render_prompt,
    _resolve_handoff,
    _run_phase,
    _step_names,
    _validate_plan,
    resolve_task,
    run_foreground,
)
from ralphkit.config import STATE_DIR, StepConfig
from ralphkit.runner import ClaudeRunError


# -- Helper --


def _strip_ansi(text: str) -> str:
    """Remove ANSI escape codes from text."""
    return re.sub(r"\x1b\[[^m]*m", "", text)


def _minimal_config_yaml():
    return """\
max_iterations: 3
default_model: opus
loop:
  - step_name: worker
    task_prompt: "Work."
    system_prompt: "System."
"""


def _minimal_config_with_two_loop_steps():
    return """\
max_iterations: 1
default_model: opus
loop:
  - step_name: worker
    task_prompt: "Work."
    system_prompt: "System."
  - step_name: checker
    task_prompt: "Check."
    system_prompt: "System."
"""


def _write_plan(state_dir, items, goal="test goal"):
    """Write a tickets.json to the state directory."""
    plan = {"goal": goal, "items": items}
    (state_dir / "tickets.json").write_text(json.dumps(plan, indent=2))


def _make_items(n, done=None):
    """Create n plan items. done is a set of 1-based IDs that should be marked done."""
    done = done or set()
    return [
        {"id": i, "title": f"Item {i}", "details": f"Do item {i}", "done": i in done}
        for i in range(1, n + 1)
    ]


# -- _render_prompt --


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


# -- _step_names --


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


# -- _run_phase --


@patch("ralphkit.engine.run_claude")
def test_run_phase_success(mock_run):
    _run_phase(
        "prompt",
        "model",
        "system",
        timeout_seconds=12,
        idle_timeout_seconds=3,
        cwd="/tmp/work",
    )
    mock_run.assert_called_once_with(
        "prompt",
        "model",
        "system",
        timeout_seconds=12,
        idle_timeout_seconds=3,
        cwd="/tmp/work",
    )


@patch("ralphkit.engine.run_claude", side_effect=RuntimeError("boom"))
def test_run_phase_runtime_error_exits(mock_run):
    with pytest.raises(SystemExit) as exc_info:
        _run_phase(
            "p",
            "m",
            "s",
            timeout_seconds=10,
            idle_timeout_seconds=None,
            cwd="/tmp/work",
        )
    assert exc_info.value.code == 1


@patch("ralphkit.engine.run_claude", side_effect=RuntimeError("boom"))
def test_run_phase_runtime_error_prints_to_stderr(mock_run, capsys):
    with pytest.raises(SystemExit):
        _run_phase(
            "p",
            "m",
            "s",
            timeout_seconds=10,
            idle_timeout_seconds=None,
            cwd="/tmp/work",
        )
    assert "boom" in capsys.readouterr().err


@patch("ralphkit.engine.run_claude", side_effect=TypeError("unexpected"))
def test_run_phase_non_runtime_error_propagates(mock_run):
    with pytest.raises(TypeError, match="unexpected"):
        _run_phase(
            "p",
            "m",
            "s",
            timeout_seconds=10,
            idle_timeout_seconds=None,
            cwd="/tmp/work",
        )


# -- _validate_plan --


def test_validate_plan_none():
    assert _validate_plan(None) is not None


def test_validate_plan_valid():
    plan = {"items": [{"id": 1, "title": "t", "done": False}]}
    assert _validate_plan(plan) is None


def test_validate_plan_empty_items():
    assert _validate_plan({"items": []}) is not None


def test_validate_plan_missing_field():
    plan = {"items": [{"id": 1, "title": "t"}]}
    assert _validate_plan(plan) is not None


# -- run_foreground() --


@patch("ralphkit.engine.run_claude")
def test_foreground_missing_task_loop_mode(mock_run, tmp_path):
    """Loop mode without task exits with error."""
    cfg = tmp_path / "ralph.yaml"
    cfg.write_text(_minimal_config_yaml())
    with pytest.raises(SystemExit) as exc_info:
        run_foreground(task=None, config_path=str(cfg))
    assert exc_info.value.code == 1


@patch("ralphkit.engine.run_claude")
def test_foreground_config_error_exits(mock_run, tmp_path):
    bad_cfg = tmp_path / "bad.yaml"
    bad_cfg.write_text("max_iterations: 5\n")
    with pytest.raises(SystemExit) as exc_info:
        run_foreground(task="task", config_path=str(bad_cfg), force=True)
    assert exc_info.value.code == 1


@pytest.mark.parametrize("value", [0, -1])
@patch("ralphkit.engine.run_claude")
def test_foreground_max_iterations_invalid_exits(mock_run, tmp_path, value):
    cfg = tmp_path / "ralph.yaml"
    cfg.write_text(_minimal_config_yaml())
    with pytest.raises(SystemExit) as exc_info:
        run_foreground(
            task="task", config_path=str(cfg), max_iterations=value, force=True
        )
    assert exc_info.value.code == 1


@patch("ralphkit.engine.run_claude")
def test_foreground_complete_on_first_iteration(mock_run, monkeypatch, tmp_path):
    """Full integration: planner creates plan, worker completes all items, exits 0."""
    cfg = tmp_path / "ralph.yaml"
    cfg.write_text(_minimal_config_yaml())
    monkeypatch.chdir(tmp_path)

    state_dir = tmp_path / STATE_DIR / "current"
    call_count = {"n": 0}

    def fake_claude(prompt, model, system_prompt, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            # Planner: create plan with 1 item
            _write_plan(state_dir, _make_items(1))
        else:
            # Worker: mark item done
            _write_plan(state_dir, _make_items(1, done={1}))

    mock_run.side_effect = fake_claude

    with pytest.raises(SystemExit) as exc_info:
        run_foreground(task="do stuff", config_path=str(cfg), force=True)
    assert exc_info.value.code == 0

    report_path = tmp_path / STATE_DIR / "runs" / "001" / "report.json"
    assert report_path.exists()
    data = json.loads(report_path.read_text())
    assert data["outcome"] == "COMPLETE"
    assert isinstance(data["steps"], list)


@patch("ralphkit.engine.run_claude")
def test_foreground_two_iterations_then_complete(mock_run, monkeypatch, tmp_path):
    """Loop runs twice: first iteration completes item 1, second completes item 2."""
    cfg = tmp_path / "ralph.yaml"
    cfg.write_text(_minimal_config_yaml())
    monkeypatch.chdir(tmp_path)

    state_dir = tmp_path / STATE_DIR / "current"
    call_count = {"n": 0}

    def fake_claude(prompt, model, system_prompt, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            # Planner
            _write_plan(state_dir, _make_items(2))
        elif call_count["n"] == 2:
            # Worker iter 1: complete item 1
            _write_plan(state_dir, _make_items(2, done={1}))
        else:
            # Worker iter 2: complete item 2
            _write_plan(state_dir, _make_items(2, done={1, 2}))

    mock_run.side_effect = fake_claude

    with pytest.raises(SystemExit) as exc_info:
        run_foreground(task="do stuff", config_path=str(cfg), force=True)
    assert exc_info.value.code == 0
    # 1 planner + 2 worker + 1 cleanup (review) calls
    assert call_count["n"] == 4


@patch("ralphkit.engine.run_claude")
def test_foreground_max_iterations_reached(mock_run, monkeypatch, tmp_path):
    """Loop exhausts max iterations without completing all items."""
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
    monkeypatch.chdir(tmp_path)

    state_dir = tmp_path / STATE_DIR / "current"
    call_count = {"n": 0}

    def fake_claude(prompt, model, system_prompt, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            # Planner: 3 items (more than max_iterations can complete)
            _write_plan(state_dir, _make_items(3))
        elif call_count["n"] == 2:
            # Worker iter 1: complete item 1
            _write_plan(state_dir, _make_items(3, done={1}))
        else:
            # Worker iter 2: complete item 2 (item 3 still incomplete)
            _write_plan(state_dir, _make_items(3, done={1, 2}))

    mock_run.side_effect = fake_claude

    with pytest.raises(SystemExit) as exc_info:
        run_foreground(task="do stuff", config_path=str(cfg), force=True)
    assert exc_info.value.code == 1


@patch("ralphkit.engine.run_claude")
def test_foreground_worker_corrupts_plan_exits(mock_run, monkeypatch, tmp_path):
    """Worker corrupting tickets.json (invalid JSON) -> exit 1."""
    cfg = tmp_path / "ralph.yaml"
    cfg.write_text(_minimal_config_yaml())
    monkeypatch.chdir(tmp_path)

    state_dir = tmp_path / STATE_DIR / "current"
    call_count = {"n": 0}

    def fake_claude(prompt, model, system_prompt, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            _write_plan(state_dir, _make_items(1))
        else:
            # Worker corrupts tickets.json
            (state_dir / "tickets.json").write_text("not json{{{")

    mock_run.side_effect = fake_claude

    with pytest.raises(SystemExit) as exc_info:
        run_foreground(task="do stuff", config_path=str(cfg), force=True)
    assert exc_info.value.code == 1


@patch("ralphkit.engine.run_claude")
def test_foreground_blocked_exits(mock_run, monkeypatch, tmp_path):
    """Blocked state after a step -> exit 1."""
    cfg = tmp_path / "ralph.yaml"
    cfg.write_text(_minimal_config_yaml())
    monkeypatch.chdir(tmp_path)

    state_dir = tmp_path / STATE_DIR / "current"
    call_count = {"n": 0}

    def fake_claude(prompt, model, system_prompt, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            _write_plan(state_dir, _make_items(1))
        else:
            (state_dir / "RALPH-BLOCKED.md").write_text("stuck")

    mock_run.side_effect = fake_claude

    with pytest.raises(SystemExit) as exc_info:
        run_foreground(task="do stuff", config_path=str(cfg), force=True)
    assert exc_info.value.code == 1


@patch("ralphkit.engine.run_claude")
def test_foreground_setup_and_cleanup_phases(mock_run, monkeypatch, tmp_path):
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
    monkeypatch.chdir(tmp_path)

    state_dir = tmp_path / STATE_DIR / "current"
    calls = []

    def fake_claude(prompt, model, system_prompt, **kwargs):
        calls.append(prompt)
        if "Init." in prompt:
            pass  # setup step
        elif len(calls) == 2:
            # Planner
            _write_plan(state_dir, _make_items(1))
        elif "Work." in prompt:
            # Worker: complete the item
            _write_plan(state_dir, _make_items(1, done={1}))

    mock_run.side_effect = fake_claude

    with pytest.raises(SystemExit) as exc_info:
        run_foreground(task="do stuff", config_path=str(cfg), force=True)
    assert exc_info.value.code == 0
    # setup(1) + planner(1) + worker(1) + cleanup(1) = 4
    assert len(calls) == 4
    assert "Init." in calls[0]
    assert "Work." in calls[2]
    assert "Cleanup." in calls[3]


@patch("ralphkit.engine.run_claude")
def test_foreground_cleanup_runs_on_max_iterations(mock_run, monkeypatch, tmp_path):
    """Cleanup phase executes even when max_iterations is reached."""
    cfg = tmp_path / "ralph.yaml"
    cfg.write_text(
        """\
max_iterations: 1
default_model: opus
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
    monkeypatch.chdir(tmp_path)

    state_dir = tmp_path / STATE_DIR / "current"
    calls = []

    def fake_claude(prompt, model, system_prompt, **kwargs):
        calls.append(prompt)
        if len(calls) == 1:
            # Planner: 2 items, but only 1 iteration allowed
            _write_plan(state_dir, _make_items(2))
        elif "Work." in prompt:
            # Worker: complete only item 1
            _write_plan(state_dir, _make_items(2, done={1}))

    mock_run.side_effect = fake_claude

    with pytest.raises(SystemExit) as exc_info:
        run_foreground(task="do stuff", config_path=str(cfg), force=True)
    assert exc_info.value.code == 1  # max iterations reached
    # planner(1) + worker(1) + cleanup(1) = 3
    assert len(calls) == 3
    assert "Cleanup." in calls[2]


@patch("ralphkit.engine.run_claude")
def test_foreground_timeout_skips_cleanup_with_light_policy(
    mock_run, monkeypatch, tmp_path
):
    cfg = tmp_path / "ralph.yaml"
    cfg.write_text(
        """\
max_iterations: 1
default_model: opus
cleanup_on_error: light
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
    monkeypatch.chdir(tmp_path)

    state_dir = tmp_path / STATE_DIR / "current"
    calls = []

    def fake_claude(prompt, model, system_prompt, **kwargs):
        calls.append(prompt)
        if len(calls) == 1:
            _write_plan(state_dir, _make_items(1))
            return None
        raise ClaudeRunError(
            "claude process timed out after 30s.",
            kind="hard_timeout",
            elapsed_s=30.0,
            timeout_seconds=30,
        )

    mock_run.side_effect = fake_claude

    with pytest.raises(SystemExit) as exc_info:
        run_foreground(task="do stuff", config_path=str(cfg), force=True)
    assert exc_info.value.code == 1
    assert len(calls) == 2
    assert calls[1] == "Work."

    report = json.loads(
        (tmp_path / STATE_DIR / "runs" / "001" / "report.json").read_text()
    )
    assert report["outcome"] == "ERROR"
    assert report["failure_summary"]["error_kind"] == "hard_timeout"
    assert report["failure_summary"]["phase"] == "loop"
    assert report["steps"][-1]["status"] == "timeout"


@patch("ralphkit.engine.run_claude")
def test_foreground_with_plan_path(mock_run, monkeypatch, tmp_path):
    """Providing --plan skips the planner and uses the given plan file."""
    cfg = tmp_path / "ralph.yaml"
    cfg.write_text(_minimal_config_yaml())
    monkeypatch.chdir(tmp_path)

    plan_file = tmp_path / "my-tickets.json"
    plan_file.write_text(json.dumps({"goal": "test", "items": _make_items(1)}))

    state_dir = tmp_path / STATE_DIR / "current"

    def fake_claude(prompt, model, system_prompt, **kwargs):
        # Worker: complete the item
        _write_plan(state_dir, _make_items(1, done={1}))

    mock_run.side_effect = fake_claude

    with pytest.raises(SystemExit) as exc_info:
        run_foreground(
            task="do stuff",
            config_path=str(cfg),
            force=True,
            plan_path=str(plan_file),
        )
    assert exc_info.value.code == 0
    # 1 worker + 1 cleanup (review), no planner
    assert mock_run.call_count == 2


@patch("ralphkit.engine.run_claude")
def test_foreground_plan_only_exits_after_planning(mock_run, monkeypatch, tmp_path):
    """--plan-only generates plan and exits without running the loop."""
    cfg = tmp_path / "ralph.yaml"
    cfg.write_text(_minimal_config_yaml())
    monkeypatch.chdir(tmp_path)

    state_dir = tmp_path / STATE_DIR / "current"

    def fake_claude(prompt, model, system_prompt, **kwargs):
        _write_plan(state_dir, _make_items(3))

    mock_run.side_effect = fake_claude

    with pytest.raises(SystemExit) as exc_info:
        run_foreground(
            task="do stuff", config_path=str(cfg), force=True, plan_only=True
        )
    assert exc_info.value.code == 0
    # Only 1 call (planner), no worker
    mock_run.assert_called_once()


# -- Banner and output --


@patch("ralphkit.engine.run_claude")
def test_foreground_shows_run_number(mock_run, monkeypatch, tmp_path, capsys):
    cfg = tmp_path / "ralph.yaml"
    cfg.write_text(_minimal_config_yaml())
    monkeypatch.chdir(tmp_path)

    state_dir = tmp_path / STATE_DIR / "current"
    call_count = {"n": 0}

    def fake_claude(prompt, model, system_prompt, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            _write_plan(state_dir, _make_items(1))
        else:
            _write_plan(state_dir, _make_items(1, done={1}))

    mock_run.side_effect = fake_claude

    with pytest.raises(SystemExit) as exc_info:
        run_foreground(task="do stuff", config_path=str(cfg), force=True)
    assert exc_info.value.code == 0
    assert "#001" in _strip_ansi(capsys.readouterr().out)


@patch("ralphkit.engine.time")
@patch("ralphkit.engine.run_claude")
def test_foreground_shows_step_numbering(
    mock_run, mock_time, monkeypatch, tmp_path, capsys
):
    """Step numbering [N/M] appears in output."""
    cfg = tmp_path / "ralph.yaml"
    cfg.write_text(_minimal_config_with_two_loop_steps())
    monkeypatch.chdir(tmp_path)

    state_dir = tmp_path / STATE_DIR / "current"
    mock_time.time.return_value = 100.0
    call_count = {"n": 0}

    def fake_claude(prompt, model, system_prompt, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            _write_plan(state_dir, _make_items(1))
        elif "Check." in prompt:
            _write_plan(state_dir, _make_items(1, done={1}))

    mock_run.side_effect = fake_claude

    with pytest.raises(SystemExit) as exc_info:
        run_foreground(task="do stuff", config_path=str(cfg), force=True)
    assert exc_info.value.code == 0

    out = _strip_ansi(capsys.readouterr().out)
    assert "[1/2]" in out
    assert "[2/2]" in out


@patch("ralphkit.engine.time")
@patch("ralphkit.engine.run_claude")
def test_foreground_shows_timing(mock_run, mock_time, monkeypatch, tmp_path, capsys):
    """Timing output appears for steps."""
    cfg = tmp_path / "ralph.yaml"
    cfg.write_text(_minimal_config_yaml())
    monkeypatch.chdir(tmp_path)

    state_dir = tmp_path / STATE_DIR / "current"

    # Return incrementing times so durations are predictable
    mock_time.time.return_value = 100.0

    plan_written = {"done": False}

    def fake_claude(prompt, model, system_prompt, **kwargs):
        if not plan_written["done"]:
            plan_written["done"] = True
            _write_plan(state_dir, _make_items(1))
        else:
            _write_plan(state_dir, _make_items(1, done={1}))

    mock_run.side_effect = fake_claude

    with pytest.raises(SystemExit) as exc_info:
        run_foreground(task="do stuff", config_path=str(cfg), force=True)
    assert exc_info.value.code == 0

    out = capsys.readouterr().out
    assert "Total time:" in out


# -- Run directory invariants --


@patch("ralphkit.engine.run_claude")
def test_foreground_multiple_iterations_single_run_directory(
    mock_run, monkeypatch, tmp_path
):
    """A full loop with 2 iterations must create exactly one run directory."""
    cfg = tmp_path / "ralph.yaml"
    cfg.write_text(_minimal_config_yaml())
    monkeypatch.chdir(tmp_path)

    state_dir = tmp_path / STATE_DIR / "current"
    call_count = {"n": 0}

    def fake_claude(prompt, model, system_prompt, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            _write_plan(state_dir, _make_items(2))
        elif call_count["n"] == 2:
            _write_plan(state_dir, _make_items(2, done={1}))
        else:
            _write_plan(state_dir, _make_items(2, done={1, 2}))

    mock_run.side_effect = fake_claude

    with pytest.raises(SystemExit) as exc_info:
        run_foreground(task="do stuff", config_path=str(cfg), force=True)
    assert exc_info.value.code == 0

    runs_dir = tmp_path / STATE_DIR / "runs"
    run_dirs = sorted(d.name for d in runs_dir.iterdir() if d.is_dir())
    assert run_dirs == ["001"]


@patch("ralphkit.engine.run_claude")
def test_foreground_two_invocations_create_two_runs(mock_run, monkeypatch, tmp_path):
    """Two sequential invocations create runs 001 and 002."""
    cfg = tmp_path / "ralph.yaml"
    cfg.write_text(_minimal_config_yaml())
    monkeypatch.chdir(tmp_path)

    state_dir = tmp_path / STATE_DIR / "current"
    call_count = {"n": 0}

    def fake_claude(prompt, model, system_prompt, **kwargs):
        call_count["n"] += 1
        if call_count["n"] in (1, 3):
            # Planner calls
            _write_plan(state_dir, _make_items(1))
        else:
            # Worker calls
            _write_plan(state_dir, _make_items(1, done={1}))

    mock_run.side_effect = fake_claude

    with pytest.raises(SystemExit):
        run_foreground(task="task one", config_path=str(cfg), force=True)

    with pytest.raises(SystemExit):
        run_foreground(task="task two", config_path=str(cfg), force=True)

    runs_dir = tmp_path / STATE_DIR / "runs"
    run_dirs = sorted(d.name for d in runs_dir.iterdir() if d.is_dir())
    assert run_dirs == ["001", "002"]
    assert (runs_dir / "001" / "task.md").read_text() == "task one"
    assert (runs_dir / "002" / "task.md").read_text() == "task two"


@patch("ralphkit.engine.run_claude")
def test_foreground_prompts_use_real_run_path(mock_run, monkeypatch, tmp_path):
    """Prompt templates receive the real run dir, not the 'current' symlink."""
    cfg = tmp_path / "ralph.yaml"
    cfg.write_text(
        """\
max_iterations: 3
default_model: opus
loop:
  - step_name: worker
    task_prompt: "Read {state_dir}/task.md"
    system_prompt: "System."
"""
    )
    monkeypatch.chdir(tmp_path)

    state_dir = tmp_path / STATE_DIR / "current"
    captured_prompts = []
    call_count = {"n": 0}

    def fake_claude(prompt, model, system_prompt, **kwargs):
        call_count["n"] += 1
        captured_prompts.append(prompt)
        if call_count["n"] == 1:
            _write_plan(state_dir, _make_items(1))
        else:
            _write_plan(state_dir, _make_items(1, done={1}))

    mock_run.side_effect = fake_claude

    with pytest.raises(SystemExit):
        run_foreground(task="do stuff", config_path=str(cfg), force=True)

    assert any("runs/001" in p for p in captured_prompts)
    assert not any(str(Path(STATE_DIR) / "current") in p for p in captured_prompts)


# -- Pipe tests --


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


@patch("ralphkit.engine.run_claude")
def test_foreground_pipe_runs_all_steps(mock_run, monkeypatch, tmp_path):
    """Pipe config runs all steps exactly once and exits 0."""
    cfg = tmp_path / "pipe.yaml"
    cfg.write_text(_pipe_config_yaml())
    monkeypatch.chdir(tmp_path)

    calls = []

    def fake_claude(prompt, model, system_prompt, **kwargs):
        calls.append(prompt)

    mock_run.side_effect = fake_claude

    with pytest.raises(SystemExit) as exc_info:
        run_foreground(task=None, config_path=str(cfg), force=True)
    assert exc_info.value.code == 0
    assert len(calls) == 3

    report_path = tmp_path / STATE_DIR / "runs" / "001" / "report.json"
    assert report_path.exists()
    data = json.loads(report_path.read_text())
    assert data["outcome"] == "PIPE_COMPLETE"
    assert len(data["steps"]) == 3


@patch("ralphkit.engine.run_claude")
def test_foreground_pipe_no_task_succeeds(mock_run, monkeypatch, tmp_path):
    """Pipe config with no task arg succeeds."""
    cfg = tmp_path / "pipe.yaml"
    cfg.write_text(_pipe_config_yaml())
    monkeypatch.chdir(tmp_path)

    mock_run.side_effect = lambda *a, **kwargs: None

    with pytest.raises(SystemExit) as exc_info:
        run_foreground(task=None, config_path=str(cfg), force=True)
    assert exc_info.value.code == 0
    assert not (tmp_path / STATE_DIR / "current" / "task.md").exists()


@patch("ralphkit.engine.run_claude")
def test_foreground_pipe_with_task(mock_run, monkeypatch, tmp_path):
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
    monkeypatch.chdir(tmp_path)

    captured_prompts = []

    def fake_claude(prompt, model, system_prompt, **kwargs):
        captured_prompts.append(prompt)

    mock_run.side_effect = fake_claude

    with pytest.raises(SystemExit) as exc_info:
        run_foreground(task="refactor auth", config_path=str(cfg), force=True)
    assert exc_info.value.code == 0
    assert (tmp_path / STATE_DIR / "current" / "task.md").read_text() == "refactor auth"
    assert captured_prompts[0] == "Do: refactor auth"


@patch("ralphkit.engine.run_claude")
def test_foreground_pipe_blocked_aborts(mock_run, monkeypatch, tmp_path):
    """Blocked state during pipe execution exits 1."""
    cfg = tmp_path / "pipe.yaml"
    cfg.write_text(_pipe_config_yaml())
    monkeypatch.chdir(tmp_path)

    state_dir = tmp_path / STATE_DIR / "current"

    def fake_claude(prompt, model, system_prompt, **kwargs):
        (state_dir / "RALPH-BLOCKED.md").write_text("stuck")

    mock_run.side_effect = fake_claude

    with pytest.raises(SystemExit) as exc_info:
        run_foreground(task=None, config_path=str(cfg), force=True)
    assert exc_info.value.code == 1


@patch("ralphkit.engine.run_claude")
def test_foreground_pipe_shows_banner(mock_run, monkeypatch, tmp_path, capsys):
    """Pipe banner shows RALPH PIPE and step names."""
    cfg = tmp_path / "pipe.yaml"
    cfg.write_text(_pipe_config_yaml())
    monkeypatch.chdir(tmp_path)

    mock_run.side_effect = lambda *a, **kwargs: None

    with pytest.raises(SystemExit) as exc_info:
        run_foreground(task=None, config_path=str(cfg), force=True)
    assert exc_info.value.code == 0

    out = capsys.readouterr().out
    assert "RALPH PIPE" in out
    assert "analyze, plan, implement" in out
    assert "Steps:" in out
    assert "PIPE COMPLETE" in out


@patch("ralphkit.engine.run_claude")
def test_foreground_pipe_handoff_in_system_prompt(mock_run, monkeypatch, tmp_path):
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
    monkeypatch.chdir(tmp_path)

    captured_systems = []

    def fake_claude(prompt, model, system_prompt, **kwargs):
        captured_systems.append(system_prompt)

    mock_run.side_effect = fake_claude

    with pytest.raises(SystemExit) as exc_info:
        run_foreground(task=None, config_path=str(cfg), force=True)
    assert exc_info.value.code == 0

    assert "handoff__step1__to__step2" in captured_systems[0]
    assert (
        "handoff__"
        not in captured_systems[0]
        .split("handoff__step1__to__step2")[0]
        .rsplit("task.md", 1)[0]
    )
    assert "handoff__step1__to__step2" in captured_systems[1]


@patch("ralphkit.engine.run_claude")
def test_foreground_pipe_step_handoff_prompt_override(mock_run, monkeypatch, tmp_path):
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
    monkeypatch.chdir(tmp_path)

    captured_systems = []

    def fake_claude(prompt, model, system_prompt, **kwargs):
        captured_systems.append(system_prompt)

    mock_run.side_effect = fake_claude

    with pytest.raises(SystemExit) as exc_info:
        run_foreground(task=None, config_path=str(cfg), force=True)
    assert exc_info.value.code == 0

    assert "CUSTOM HANDOFF" in captured_systems[0]
    assert "handoff__step1__to__step2" in captured_systems[1]


@patch("ralphkit.engine.run_claude")
def test_foreground_pipe_empty_handoff_prompt_disables(mock_run, monkeypatch, tmp_path):
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
    monkeypatch.chdir(tmp_path)

    captured_systems = []

    def fake_claude(prompt, model, system_prompt, **kwargs):
        captured_systems.append(system_prompt)

    mock_run.side_effect = fake_claude

    with pytest.raises(SystemExit) as exc_info:
        run_foreground(task=None, config_path=str(cfg), force=True)
    assert exc_info.value.code == 0

    assert captured_systems[0].startswith("You are step1.")
    assert "handoff__" not in captured_systems[0]


# -- _build_default_handoff --


def test_build_default_handoff_first_step():
    steps = [
        StepConfig(step_name="a", task_prompt="", system_prompt=""),
        StepConfig(step_name="b", task_prompt="", system_prompt=""),
    ]
    result = _build_default_handoff(1, 2, steps, ".ralphkit/current")
    assert "handoff__a__to__b" in result
    assert "Write" in result or "write" in result
    assert "Read" not in result.split("task.md")[0]


def test_build_default_handoff_last_step():
    steps = [
        StepConfig(step_name="a", task_prompt="", system_prompt=""),
        StepConfig(step_name="b", task_prompt="", system_prompt=""),
    ]
    result = _build_default_handoff(2, 2, steps, ".ralphkit/current")
    assert "handoff__a__to__b" in result
    assert "Read" in result or "read" in result


def test_build_default_handoff_middle_step():
    steps = [
        StepConfig(step_name="a", task_prompt="", system_prompt=""),
        StepConfig(step_name="b", task_prompt="", system_prompt=""),
        StepConfig(step_name="c", task_prompt="", system_prompt=""),
    ]
    result = _build_default_handoff(2, 3, steps, ".ralphkit/current")
    assert "handoff__a__to__b" in result
    assert "handoff__b__to__c" in result


# -- _resolve_handoff --


def test_resolve_handoff_step_level_wins():
    step = StepConfig(
        step_name="s", task_prompt="", system_prompt="", handoff_prompt="STEP"
    )
    result = _resolve_handoff(step, 1, 1, [step], "dir")
    assert result == "STEP"


def test_resolve_handoff_falls_back_to_default():
    step = StepConfig(step_name="s", task_prompt="", system_prompt="")
    result = _resolve_handoff(step, 1, 1, [step], "dir")
    assert "task.md" in result


# -- resolve_task --


@patch("ralphkit.engine.print_warning")
def test_resolve_task_warns_on_missing_md(mock_warn):
    """resolve_task warns when .md file doesn't exist."""
    result = resolve_task("nonexistent-file.md")
    assert result == "nonexistent-file.md"
    mock_warn.assert_called_once()
    assert "nonexistent-file.md" in mock_warn.call_args[0][0]
