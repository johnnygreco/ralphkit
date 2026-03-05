import pytest

from ralphkit.cli import resolve_task
from ralphkit.config import StepConfig, load_config, resolve_model


def test_load_config_valid_full(tmp_path):
    cfg_file = tmp_path / "ralph.yaml"
    cfg_file.write_text(
        """\
max_iterations: 5
default_model: opus

setup:
  - step_name: init
    task_prompt: "Initialize the project"
    system_prompt: "You are a setup agent."

loop:
  - step_name: worker
    task_prompt: "Do work on iteration {iteration}."
    system_prompt: "You are a worker."
    model: opus
  - step_name: reviewer
    task_prompt: "Review the work."
    system_prompt: "You are a reviewer."
    model: sonnet

cleanup:
  - step_name: finalize
    task_prompt: "Clean up."
    system_prompt: "You are a cleanup agent."
"""
    )
    config = load_config(cfg_file)
    assert config.max_iterations == 5
    assert config.default_model == "opus"
    assert len(config.setup) == 1
    assert config.setup[0].step_name == "init"
    assert len(config.loop) == 2
    assert config.loop[0].model == "opus"
    assert config.loop[1].model == "sonnet"
    assert len(config.cleanup) == 1


def test_load_config_loop_only(tmp_path):
    cfg_file = tmp_path / "ralph.yaml"
    cfg_file.write_text(
        """\
max_iterations: 3
default_model: haiku

loop:
  - step_name: worker
    task_prompt: "Work."
    system_prompt: "System."
"""
    )
    config = load_config(cfg_file)
    assert config.max_iterations == 3
    assert config.default_model == "haiku"
    assert len(config.loop) == 1
    assert config.setup == []
    assert config.cleanup == []


def test_load_config_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_config(tmp_path / "nonexistent.yaml")


def test_load_config_missing_loop(tmp_path):
    cfg_file = tmp_path / "ralph.yaml"
    cfg_file.write_text("max_iterations: 5\ndefault_model: opus\n")
    with pytest.raises(ValueError, match="missing required key 'loop'"):
        load_config(cfg_file)


def test_load_config_missing_default_model(tmp_path):
    cfg_file = tmp_path / "ralph.yaml"
    cfg_file.write_text(
        """\
max_iterations: 5
loop:
  - step_name: worker
    task_prompt: "Work."
    system_prompt: "System."
"""
    )
    with pytest.raises(ValueError, match="missing required key 'default_model'"):
        load_config(cfg_file)


def test_load_config_warns_unknown_keys(tmp_path, capsys):
    cfg_file = tmp_path / "ralph.yaml"
    cfg_file.write_text(
        """\
max_iterations: 5
default_model: opus
bogus_key: hello
loop:
  - step_name: worker
    task_prompt: "Work."
    system_prompt: "System."
"""
    )
    load_config(cfg_file)
    assert "unknown config keys ignored: bogus_key" in capsys.readouterr().err


def test_step_missing_required_fields(tmp_path):
    cfg_file = tmp_path / "ralph.yaml"
    cfg_file.write_text(
        """\
max_iterations: 5
default_model: opus
loop:
  - step_name: worker
    task_prompt: "Work."
"""
    )
    with pytest.raises(ValueError, match="missing required field 'system_prompt'"):
        load_config(cfg_file)


def test_load_config_invalid_max_iterations(tmp_path):
    cfg_file = tmp_path / "ralph.yaml"
    cfg_file.write_text(
        """\
max_iterations: 0
default_model: opus
loop:
  - step_name: worker
    task_prompt: "Work."
    system_prompt: "System."
"""
    )
    with pytest.raises(ValueError, match="max_iterations must be >= 1"):
        load_config(cfg_file)


def test_load_config_none():
    with pytest.raises(ValueError, match="config file is required"):
        load_config(None)


def test_resolve_model_fallback():
    step = StepConfig(step_name="test", task_prompt="p", system_prompt="s")
    assert resolve_model(step, "opus") == "opus"


def test_resolve_model_override():
    step = StepConfig(
        step_name="test", task_prompt="p", system_prompt="s", model="haiku"
    )
    assert resolve_model(step, "opus") == "haiku"


def test_resolve_task_string():
    assert resolve_task("do something") == "do something"


def test_resolve_task_md_file(tmp_path):
    md = tmp_path / "task.md"
    md.write_text("# My Task\nDo the thing.")
    assert resolve_task(str(md)) == "# My Task\nDo the thing."


def test_resolve_task_missing_md():
    assert resolve_task("nonexistent.md") == "nonexistent.md"
