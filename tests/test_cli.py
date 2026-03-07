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
    _validate_plan,
)
from ralphkit.config import STATE_DIR, StepConfig


# ── Helper ──────────────────────────────────────────────────────────


def _minimal_config_yaml():
    return """\
max_iterations: 3
default_model: opus
loop:
  - step_name: worker
    task_prompt: "Work."
    system_prompt: "System."
"""


def _make_plan(items=None, goal="Test"):
    """Create a valid plan dict."""
    if items is None:
        items = [
            {"id": 1, "title": "Item 1", "details": "Do thing 1", "done": False},
            {"id": 2, "title": "Item 2", "details": "Do thing 2", "done": False},
        ]
    return {"goal": goal, "items": items}


# ── _validate_plan ──────────────────────────────────────────────────


def test_validate_plan_valid():
    plan = _make_plan()
    assert _validate_plan(plan) is None


def test_validate_plan_none():
    assert _validate_plan(None) is not None


def test_validate_plan_empty_items():
    assert _validate_plan({"items": []}) is not None


def test_validate_plan_missing_fields():
    plan = {"items": [{"id": 1, "title": "A"}]}  # missing 'done'
    assert _validate_plan(plan) is not None


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
def test_main_plan_then_complete(mock_run, monkeypatch, tmp_path):
    """Planner writes 2-item plan, worker marks items done -> COMPLETE."""
    cfg = tmp_path / "ralph.yaml"
    cfg.write_text(_minimal_config_yaml())
    monkeypatch.setattr(
        sys, "argv", ["ralph-loop", "do stuff", "--config", str(cfg), "-f"]
    )
    monkeypatch.chdir(tmp_path)

    state_dir = tmp_path / STATE_DIR / "current"
    call_count = {"n": 0}
    plan = _make_plan()

    def fake_claude(prompt, model, system_prompt):
        call_count["n"] += 1
        if call_count["n"] == 1:
            # Planner writes plan.json
            (state_dir / "plan.json").write_text(json.dumps(plan))
        elif call_count["n"] == 2:
            # Worker marks item 1 done
            p = json.loads((state_dir / "plan.json").read_text())
            p["items"][0]["done"] = True
            (state_dir / "plan.json").write_text(json.dumps(p))
        elif call_count["n"] == 3:
            # Worker marks item 2 done
            p = json.loads((state_dir / "plan.json").read_text())
            p["items"][1]["done"] = True
            (state_dir / "plan.json").write_text(json.dumps(p))

    mock_run.side_effect = fake_claude

    with pytest.raises(SystemExit) as exc_info:
        main()
    assert exc_info.value.code == 0
    assert call_count["n"] == 3  # planner + 2 worker iterations

    # report.json should have COMPLETE outcome
    report_path = tmp_path / STATE_DIR / "runs" / "001" / "report.json"
    assert report_path.exists()
    data = json.loads(report_path.read_text())
    assert data["outcome"] == "COMPLETE"


@patch("ralphkit.cli.run_claude")
def test_main_plan_complete_single_iteration(mock_run, monkeypatch, tmp_path):
    """1-item plan, worker marks done -> COMPLETE in 1 iteration."""
    cfg = tmp_path / "ralph.yaml"
    cfg.write_text(_minimal_config_yaml())
    monkeypatch.setattr(
        sys, "argv", ["ralph-loop", "do stuff", "--config", str(cfg), "-f"]
    )
    monkeypatch.chdir(tmp_path)

    state_dir = tmp_path / STATE_DIR / "current"
    plan = _make_plan(
        items=[{"id": 1, "title": "Only item", "details": "Do it", "done": False}]
    )

    call_count = {"n": 0}

    def fake_claude(prompt, model, system_prompt):
        call_count["n"] += 1
        if call_count["n"] == 1:
            (state_dir / "plan.json").write_text(json.dumps(plan))
        else:
            p = json.loads((state_dir / "plan.json").read_text())
            p["items"][0]["done"] = True
            (state_dir / "plan.json").write_text(json.dumps(p))

    mock_run.side_effect = fake_claude

    with pytest.raises(SystemExit) as exc_info:
        main()
    assert exc_info.value.code == 0
    assert call_count["n"] == 2  # planner + 1 worker


@patch("ralphkit.cli.run_claude")
def test_main_plan_max_iterations(mock_run, monkeypatch, tmp_path):
    """3-item plan, max_iterations=1, worker marks 1 done -> MAX_ITERATIONS."""
    cfg = tmp_path / "ralph.yaml"
    cfg.write_text(
        """\
max_iterations: 1
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
    plan = _make_plan(
        items=[
            {"id": 1, "title": "A", "details": "a", "done": False},
            {"id": 2, "title": "B", "details": "b", "done": False},
            {"id": 3, "title": "C", "details": "c", "done": False},
        ]
    )

    call_count = {"n": 0}

    def fake_claude(prompt, model, system_prompt):
        call_count["n"] += 1
        if call_count["n"] == 1:
            (state_dir / "plan.json").write_text(json.dumps(plan))
        else:
            p = json.loads((state_dir / "plan.json").read_text())
            p["items"][0]["done"] = True
            (state_dir / "plan.json").write_text(json.dumps(p))

    mock_run.side_effect = fake_claude

    with pytest.raises(SystemExit) as exc_info:
        main()
    assert exc_info.value.code == 1

    report_path = tmp_path / STATE_DIR / "runs" / "001" / "report.json"
    data = json.loads(report_path.read_text())
    assert data["outcome"] == "MAX_ITERATIONS"
    assert data["items_completed"] == 1
    assert data["items_total"] == 3


@patch("ralphkit.cli.run_claude")
def test_main_plan_only_exits_after_planning(mock_run, monkeypatch, tmp_path):
    """--plan-only flag -> plan.json written, exit 0, no worker runs."""
    cfg = tmp_path / "ralph.yaml"
    cfg.write_text(_minimal_config_yaml())
    monkeypatch.setattr(
        sys,
        "argv",
        ["ralph-loop", "do stuff", "--config", str(cfg), "-f", "--plan-only"],
    )
    monkeypatch.chdir(tmp_path)

    state_dir = tmp_path / STATE_DIR / "current"
    plan = _make_plan()

    call_count = {"n": 0}

    def fake_claude(prompt, model, system_prompt):
        call_count["n"] += 1
        (state_dir / "plan.json").write_text(json.dumps(plan))

    mock_run.side_effect = fake_claude

    with pytest.raises(SystemExit) as exc_info:
        main()
    assert exc_info.value.code == 0
    assert call_count["n"] == 1  # only planner, no worker


@patch("ralphkit.cli.run_claude")
def test_main_plan_flag_skips_planner(mock_run, monkeypatch, tmp_path):
    """--plan plan.json -> planner not called, file copied."""
    cfg = tmp_path / "ralph.yaml"
    cfg.write_text(_minimal_config_yaml())

    plan = _make_plan(items=[{"id": 1, "title": "A", "details": "a", "done": False}])
    plan_file = tmp_path / "my_plan.json"
    plan_file.write_text(json.dumps(plan))

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "ralph-loop",
            "do stuff",
            "--config",
            str(cfg),
            "-f",
            "--plan",
            str(plan_file),
        ],
    )
    monkeypatch.chdir(tmp_path)

    state_dir = tmp_path / STATE_DIR / "current"
    call_count = {"n": 0}

    def fake_claude(prompt, model, system_prompt):
        call_count["n"] += 1
        # Worker marks item done
        p = json.loads((state_dir / "plan.json").read_text())
        p["items"][0]["done"] = True
        (state_dir / "plan.json").write_text(json.dumps(p))

    mock_run.side_effect = fake_claude

    with pytest.raises(SystemExit) as exc_info:
        main()
    assert exc_info.value.code == 0
    assert call_count["n"] == 1  # only worker, no planner


@patch("ralphkit.cli.run_claude")
def test_main_plan_flag_file_not_found(mock_run, monkeypatch, tmp_path, capsys):
    """--plan missing.json -> exit 1."""
    cfg = tmp_path / "ralph.yaml"
    cfg.write_text(_minimal_config_yaml())
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "ralph-loop",
            "do stuff",
            "--config",
            str(cfg),
            "-f",
            "--plan",
            "/tmp/missing.json",
        ],
    )
    monkeypatch.chdir(tmp_path)

    with pytest.raises(SystemExit) as exc_info:
        main()
    assert exc_info.value.code == 1
    assert "not found" in capsys.readouterr().err


@patch("ralphkit.cli.run_claude")
def test_main_plan_flag_invalid_json(mock_run, monkeypatch, tmp_path, capsys):
    """--plan bad.json -> exit 1."""
    cfg = tmp_path / "ralph.yaml"
    cfg.write_text(_minimal_config_yaml())
    bad_plan = tmp_path / "bad.json"
    bad_plan.write_text("not json {{{")
    monkeypatch.setattr(
        sys,
        "argv",
        ["ralph-loop", "do stuff", "--config", str(cfg), "-f", "--plan", str(bad_plan)],
    )
    monkeypatch.chdir(tmp_path)

    with pytest.raises(SystemExit) as exc_info:
        main()
    assert exc_info.value.code == 1
    assert "Invalid plan file" in capsys.readouterr().err


@patch("ralphkit.cli.run_claude")
def test_main_planner_produces_no_plan(mock_run, monkeypatch, tmp_path, capsys):
    """Planner runs but doesn't write plan.json -> exit 1."""
    cfg = tmp_path / "ralph.yaml"
    cfg.write_text(_minimal_config_yaml())
    monkeypatch.setattr(
        sys, "argv", ["ralph-loop", "do stuff", "--config", str(cfg), "-f"]
    )
    monkeypatch.chdir(tmp_path)

    # Planner does nothing (doesn't write plan.json)
    mock_run.side_effect = lambda *a: None

    with pytest.raises(SystemExit) as exc_info:
        main()
    assert exc_info.value.code == 1
    assert "Planning failed" in capsys.readouterr().err


@patch("ralphkit.cli.run_claude")
def test_main_planner_produces_empty_plan(mock_run, monkeypatch, tmp_path, capsys):
    """Plan with 0 items -> exit 1."""
    cfg = tmp_path / "ralph.yaml"
    cfg.write_text(_minimal_config_yaml())
    monkeypatch.setattr(
        sys, "argv", ["ralph-loop", "do stuff", "--config", str(cfg), "-f"]
    )
    monkeypatch.chdir(tmp_path)

    state_dir = tmp_path / STATE_DIR / "current"

    def fake_claude(prompt, model, system_prompt):
        (state_dir / "plan.json").write_text(json.dumps({"goal": "X", "items": []}))

    mock_run.side_effect = fake_claude

    with pytest.raises(SystemExit) as exc_info:
        main()
    assert exc_info.value.code == 1
    assert "Planning failed" in capsys.readouterr().err


@patch("ralphkit.cli.run_claude")
def test_main_worker_corrupts_plan(mock_run, monkeypatch, tmp_path, capsys):
    """Worker writes bad JSON to plan.json -> exit 1."""
    cfg = tmp_path / "ralph.yaml"
    cfg.write_text(_minimal_config_yaml())
    monkeypatch.setattr(
        sys, "argv", ["ralph-loop", "do stuff", "--config", str(cfg), "-f"]
    )
    monkeypatch.chdir(tmp_path)

    state_dir = tmp_path / STATE_DIR / "current"
    plan = _make_plan()
    call_count = {"n": 0}

    def fake_claude(prompt, model, system_prompt):
        call_count["n"] += 1
        if call_count["n"] == 1:
            (state_dir / "plan.json").write_text(json.dumps(plan))
        else:
            (state_dir / "plan.json").write_text("corrupted {{{")

    mock_run.side_effect = fake_claude

    with pytest.raises(SystemExit) as exc_info:
        main()
    assert exc_info.value.code == 1
    assert "corrupted" in capsys.readouterr().err.lower()


@patch("ralphkit.cli.run_claude")
def test_main_worker_marks_multiple_done(mock_run, monkeypatch, tmp_path):
    """Worker marks 2 items done in one iteration -> loop completes sooner."""
    cfg = tmp_path / "ralph.yaml"
    cfg.write_text(_minimal_config_yaml())
    monkeypatch.setattr(
        sys, "argv", ["ralph-loop", "do stuff", "--config", str(cfg), "-f"]
    )
    monkeypatch.chdir(tmp_path)

    state_dir = tmp_path / STATE_DIR / "current"
    plan = _make_plan()
    call_count = {"n": 0}

    def fake_claude(prompt, model, system_prompt):
        call_count["n"] += 1
        if call_count["n"] == 1:
            (state_dir / "plan.json").write_text(json.dumps(plan))
        else:
            # Mark both items done at once
            p = json.loads((state_dir / "plan.json").read_text())
            for item in p["items"]:
                item["done"] = True
            (state_dir / "plan.json").write_text(json.dumps(p))

    mock_run.side_effect = fake_claude

    with pytest.raises(SystemExit) as exc_info:
        main()
    assert exc_info.value.code == 0
    assert call_count["n"] == 2  # planner + 1 worker (both done in one shot)


@patch("ralphkit.cli.run_claude")
def test_main_plan_model_override(mock_run, monkeypatch, tmp_path):
    """--plan-model sonnet -> planner uses sonnet, worker uses default."""
    cfg = tmp_path / "ralph.yaml"
    cfg.write_text(_minimal_config_yaml())
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "ralph-loop",
            "do stuff",
            "--config",
            str(cfg),
            "-f",
            "--plan-model",
            "sonnet",
        ],
    )
    monkeypatch.chdir(tmp_path)

    state_dir = tmp_path / STATE_DIR / "current"
    plan = _make_plan(items=[{"id": 1, "title": "A", "details": "a", "done": False}])
    captured_models = []

    def fake_claude(prompt, model, system_prompt):
        captured_models.append(model)
        if len(captured_models) == 1:
            (state_dir / "plan.json").write_text(json.dumps(plan))
        else:
            p = json.loads((state_dir / "plan.json").read_text())
            p["items"][0]["done"] = True
            (state_dir / "plan.json").write_text(json.dumps(p))

    mock_run.side_effect = fake_claude

    with pytest.raises(SystemExit) as exc_info:
        main()
    assert exc_info.value.code == 0
    assert captured_models[0] == "sonnet"  # planner
    assert captured_models[1] == "opus"  # worker


@patch("ralphkit.cli.run_claude")
def test_main_report_includes_plan_stats(mock_run, monkeypatch, tmp_path):
    """report.json has items_completed, items_total."""
    cfg = tmp_path / "ralph.yaml"
    cfg.write_text(_minimal_config_yaml())
    monkeypatch.setattr(
        sys, "argv", ["ralph-loop", "do stuff", "--config", str(cfg), "-f"]
    )
    monkeypatch.chdir(tmp_path)

    state_dir = tmp_path / STATE_DIR / "current"
    plan = _make_plan()
    call_count = {"n": 0}

    def fake_claude(prompt, model, system_prompt):
        call_count["n"] += 1
        if call_count["n"] == 1:
            (state_dir / "plan.json").write_text(json.dumps(plan))
        else:
            p = json.loads((state_dir / "plan.json").read_text())
            for item in p["items"]:
                item["done"] = True
            (state_dir / "plan.json").write_text(json.dumps(p))

    mock_run.side_effect = fake_claude

    with pytest.raises(SystemExit) as exc_info:
        main()
    assert exc_info.value.code == 0

    report_path = tmp_path / STATE_DIR / "runs" / "001" / "report.json"
    data = json.loads(report_path.read_text())
    assert data["items_completed"] == 2
    assert data["items_total"] == 2


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
    plan = _make_plan()
    call_count = {"n": 0}

    def fake_claude(prompt, model, system_prompt):
        call_count["n"] += 1
        if call_count["n"] == 1:
            # Planner writes plan
            (state_dir / "plan.json").write_text(json.dumps(plan))
        else:
            # Worker gets blocked
            (state_dir / "RALPH-BLOCKED.md").write_text("stuck")

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
    plan = _make_plan(items=[{"id": 1, "title": "A", "details": "a", "done": False}])

    def fake_claude(prompt, model, system_prompt):
        calls.append(prompt)
        if "Init." in prompt:
            pass  # setup step
        elif len(calls) == 2:
            # Planner
            (state_dir / "plan.json").write_text(json.dumps(plan))
        elif "Work." in prompt:
            # Worker marks done
            p = json.loads((state_dir / "plan.json").read_text())
            p["items"][0]["done"] = True
            (state_dir / "plan.json").write_text(json.dumps(p))
        # cleanup does nothing

    mock_run.side_effect = fake_claude

    with pytest.raises(SystemExit) as exc_info:
        main()
    assert exc_info.value.code == 0
    assert len(calls) == 4  # setup + planner + worker + cleanup
    assert "Init." in calls[0]
    assert "Cleanup." in calls[3]


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


@patch("ralphkit.cli.run_claude")
def test_main_list_runs_shows_plan_progress(mock_run, monkeypatch, tmp_path, capsys):
    """--list-runs shows plan item counts when plan.json exists."""
    state_root = tmp_path / STATE_DIR
    runs_dir = state_root / "runs"
    (runs_dir / "001").mkdir(parents=True)
    (runs_dir / "001" / "task.md").write_text("auth tests")
    plan = _make_plan()
    plan["items"][0]["done"] = True
    (runs_dir / "001" / "plan.json").write_text(json.dumps(plan))
    (runs_dir / "001" / "report.json").write_text(json.dumps({"outcome": "COMPLETE"}))

    monkeypatch.setattr(
        sys, "argv", ["ralph-loop", "--list-runs", "--state-dir", str(state_root)]
    )
    with pytest.raises(SystemExit) as exc_info:
        main()
    assert exc_info.value.code == 0
    out = capsys.readouterr().out
    assert "COMPLETE" in out
    assert "1/2" in out


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
    plan = _make_plan(items=[{"id": 1, "title": "A", "details": "a", "done": False}])

    call_count = {"n": 0}

    def fake_claude(prompt, model, system_prompt):
        call_count["n"] += 1
        if call_count["n"] == 1:
            (state_dir / "plan.json").write_text(json.dumps(plan))
        else:
            p = json.loads((state_dir / "plan.json").read_text())
            p["items"][0]["done"] = True
            (state_dir / "plan.json").write_text(json.dumps(p))

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
    plan = _make_plan(items=[{"id": 1, "title": "A", "details": "a", "done": False}])

    call_count = {"n": 0}

    def fake_claude(prompt, model, system_prompt):
        call_count["n"] += 1
        if call_count["n"] == 1:
            (state_dir / "plan.json").write_text(json.dumps(plan))
        else:
            p = json.loads((state_dir / "plan.json").read_text())
            p["items"][0]["done"] = True
            (state_dir / "plan.json").write_text(json.dumps(p))

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
    cfg.write_text(_minimal_config_yaml())
    monkeypatch.setattr(
        sys, "argv", ["ralph-loop", "do stuff", "--config", str(cfg), "-f"]
    )
    monkeypatch.chdir(tmp_path)

    state_dir = tmp_path / STATE_DIR / "current"
    mock_time.time.return_value = 100.0
    plan = _make_plan(items=[{"id": 1, "title": "A", "details": "a", "done": False}])

    call_count = {"n": 0}

    def fake_claude(prompt, model, system_prompt):
        call_count["n"] += 1
        if call_count["n"] == 1:
            (state_dir / "plan.json").write_text(json.dumps(plan))
        else:
            p = json.loads((state_dir / "plan.json").read_text())
            p["items"][0]["done"] = True
            (state_dir / "plan.json").write_text(json.dumps(p))

    mock_run.side_effect = fake_claude

    with pytest.raises(SystemExit) as exc_info:
        main()
    assert exc_info.value.code == 0

    out = capsys.readouterr().out
    assert "[1/1]" in out


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
    plan = _make_plan(items=[{"id": 1, "title": "A", "details": "a", "done": False}])

    call_count = {"n": 0}
    # time.time() calls: start, planning_before, planning_t0, planning_end, plan_summary...
    # then loop: iter_start, step_t0, step_end, ...
    times = [100.0, 100.0, 100.0, 114.3]  # start, planning, t0, step_end

    time_call_count = {"n": 0}

    def fake_time():
        time_call_count["n"] += 1
        if time_call_count["n"] <= len(times):
            return times[time_call_count["n"] - 1]
        return 142.1

    mock_time.time.side_effect = fake_time

    def fake_claude(prompt, model, system_prompt):
        call_count["n"] += 1
        if call_count["n"] == 1:
            (state_dir / "plan.json").write_text(json.dumps(plan))
        else:
            p = json.loads((state_dir / "plan.json").read_text())
            p["items"][0]["done"] = True
            (state_dir / "plan.json").write_text(json.dumps(p))

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
    """A full loop with multiple iterations must create exactly one run directory."""
    cfg = tmp_path / "ralph.yaml"
    cfg.write_text(_minimal_config_yaml())
    monkeypatch.setattr(
        sys, "argv", ["ralph-loop", "do stuff", "--config", str(cfg), "-f"]
    )
    monkeypatch.chdir(tmp_path)

    state_dir = tmp_path / STATE_DIR / "current"
    plan = _make_plan()
    call_count = {"n": 0}

    def fake_claude(prompt, model, system_prompt):
        call_count["n"] += 1
        if call_count["n"] == 1:
            (state_dir / "plan.json").write_text(json.dumps(plan))
        elif call_count["n"] == 2:
            p = json.loads((state_dir / "plan.json").read_text())
            p["items"][0]["done"] = True
            (state_dir / "plan.json").write_text(json.dumps(p))
        else:
            p = json.loads((state_dir / "plan.json").read_text())
            p["items"][1]["done"] = True
            (state_dir / "plan.json").write_text(json.dumps(p))

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
    plan = _make_plan(items=[{"id": 1, "title": "A", "details": "a", "done": False}])

    def fake_claude(prompt, model, system_prompt):
        if not (state_dir / "plan.json").exists():
            (state_dir / "plan.json").write_text(json.dumps(plan))
        else:
            p = json.loads((state_dir / "plan.json").read_text())
            p["items"][0]["done"] = True
            (state_dir / "plan.json").write_text(json.dumps(p))

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
    plan = _make_plan(items=[{"id": 1, "title": "A", "details": "a", "done": False}])
    captured_prompts = []

    call_count = {"n": 0}

    def fake_claude(prompt, model, system_prompt):
        call_count["n"] += 1
        captured_prompts.append(prompt)
        if call_count["n"] == 1:
            (state_dir / "plan.json").write_text(json.dumps(plan))
        else:
            p = json.loads((state_dir / "plan.json").read_text())
            p["items"][0]["done"] = True
            (state_dir / "plan.json").write_text(json.dumps(p))

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
