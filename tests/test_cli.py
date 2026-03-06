import sys
from unittest.mock import patch

import pytest

from ralphkit.cli import main, _render_prompt, _run_phase, _step_names
from ralphkit.config import STATE_DIR, VERDICT_REVISE, VERDICT_SHIP, StepConfig


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
def test_main_missing_task_arg(mock_run, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["ralph-loop", "--config", "x.yaml"])
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

    state_dir = tmp_path / STATE_DIR

    def fake_claude(prompt, model, system_prompt):
        state_dir.mkdir(exist_ok=True)
        (state_dir / "review-result.md").write_text(VERDICT_SHIP)

    mock_run.side_effect = fake_claude

    with pytest.raises(SystemExit) as exc_info:
        main()
    assert exc_info.value.code == 0


@patch("ralphkit.cli.run_claude")
def test_main_revise_then_ship(mock_run, monkeypatch, tmp_path):
    """Loop runs twice: first REVISE, then SHIP."""
    cfg = tmp_path / "ralph.yaml"
    cfg.write_text(_minimal_config_yaml())
    monkeypatch.setattr(
        sys, "argv", ["ralph-loop", "do stuff", "--config", str(cfg), "-f"]
    )
    monkeypatch.chdir(tmp_path)

    state_dir = tmp_path / STATE_DIR
    call_count = {"n": 0}

    def fake_claude(prompt, model, system_prompt):
        state_dir.mkdir(exist_ok=True)
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

    state_dir = tmp_path / STATE_DIR

    def fake_claude(prompt, model, system_prompt):
        state_dir.mkdir(exist_ok=True)
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

    state_dir = tmp_path / STATE_DIR

    def fake_claude(prompt, model, system_prompt):
        state_dir.mkdir(exist_ok=True)
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

    state_dir = tmp_path / STATE_DIR

    def fake_claude(prompt, model, system_prompt):
        state_dir.mkdir(exist_ok=True)
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

    state_dir = tmp_path / STATE_DIR
    calls = []

    def fake_claude(prompt, model, system_prompt):
        state_dir.mkdir(exist_ok=True)
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


@patch("ralphkit.cli.run_claude")
def test_main_custom_state_dir(mock_run, monkeypatch, tmp_path):
    """--state-dir overrides the state directory."""
    cfg = tmp_path / "ralph.yaml"
    cfg.write_text(_minimal_config_yaml())
    custom_dir = ".my-state"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "ralph-loop",
            "do stuff",
            "--config",
            str(cfg),
            "--state-dir",
            custom_dir,
            "-f",
        ],
    )
    monkeypatch.chdir(tmp_path)

    state_dir = tmp_path / custom_dir

    def fake_claude(prompt, model, system_prompt):
        state_dir.mkdir(exist_ok=True)
        (state_dir / "review-result.md").write_text(VERDICT_SHIP)

    mock_run.side_effect = fake_claude

    with pytest.raises(SystemExit) as exc_info:
        main()
    assert exc_info.value.code == 0
    assert (state_dir / "task.md").exists()
