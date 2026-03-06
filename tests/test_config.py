import pytest

from ralphkit.cli import resolve_task
from ralphkit.config import (
    DEFAULT_MAX_ITERATIONS,
    DEFAULT_MODEL,
    STATE_DIR,
    StepConfig,
    load_config,
    resolve_model,
)


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


def test_load_config_no_loop_uses_default(tmp_path):
    """Config without loop section uses default loop steps."""
    cfg_file = tmp_path / "ralph.yaml"
    cfg_file.write_text(
        """\
setup:
  - step_name: init
    task_prompt: "Init."
    system_prompt: "Setup."
"""
    )
    config = load_config(cfg_file)
    assert len(config.loop) == 2
    assert config.loop[0].step_name == "worker"
    assert config.loop[1].step_name == "reviewer"
    assert config.max_iterations == DEFAULT_MAX_ITERATIONS
    assert config.default_model == DEFAULT_MODEL
    assert len(config.setup) == 1


def test_load_config_overrides_loop(tmp_path):
    """Config with loop section overrides the default."""
    cfg_file = tmp_path / "ralph.yaml"
    cfg_file.write_text(
        """\
loop:
  - step_name: custom_worker
    task_prompt: "Custom work."
    system_prompt: "Custom system."
"""
    )
    config = load_config(cfg_file)
    assert len(config.loop) == 1
    assert config.loop[0].step_name == "custom_worker"


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
loop:
  - step_name: worker
    task_prompt: "Work."
"""
    )
    with pytest.raises(ValueError, match="missing required field 'system_prompt'"):
        load_config(cfg_file)


@pytest.mark.parametrize("value", [0, -1])
def test_load_config_invalid_max_iterations(tmp_path, value):
    cfg_file = tmp_path / "ralph.yaml"
    cfg_file.write_text(
        f"""\
max_iterations: {value}
loop:
  - step_name: worker
    task_prompt: "Work."
    system_prompt: "System."
"""
    )
    with pytest.raises(ValueError, match="max_iterations must be >= 1"):
        load_config(cfg_file)


def test_load_config_none_returns_defaults():
    config = load_config(None)
    assert config.max_iterations == DEFAULT_MAX_ITERATIONS
    assert config.default_model == DEFAULT_MODEL
    assert config.state_dir == STATE_DIR
    assert len(config.loop) == 2
    assert config.loop[0].step_name == "worker"
    assert config.loop[1].step_name == "reviewer"
    assert config.setup == []
    assert config.cleanup == []


def test_load_config_no_args_returns_defaults():
    config = load_config()
    assert config.max_iterations == DEFAULT_MAX_ITERATIONS
    assert len(config.loop) == 2


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


def test_load_config_empty_loop(tmp_path):
    cfg_file = tmp_path / "ralph.yaml"
    cfg_file.write_text(
        """\
loop: []
"""
    )
    with pytest.raises(ValueError, match="loop must have at least 1 step"):
        load_config(cfg_file)


def test_load_config_empty_yaml(tmp_path):
    """Empty YAML file uses all defaults."""
    cfg_file = tmp_path / "ralph.yaml"
    cfg_file.write_text("")
    config = load_config(cfg_file)
    assert config.max_iterations == DEFAULT_MAX_ITERATIONS
    assert config.default_model == DEFAULT_MODEL
    assert len(config.loop) == 2


def test_load_config_step_missing_step_name(tmp_path):
    cfg_file = tmp_path / "ralph.yaml"
    cfg_file.write_text(
        """\
loop:
  - task_prompt: "Work."
    system_prompt: "System."
"""
    )
    with pytest.raises(ValueError, match="missing required field 'step_name'"):
        load_config(cfg_file)


def test_load_config_step_missing_task_prompt(tmp_path):
    cfg_file = tmp_path / "ralph.yaml"
    cfg_file.write_text(
        """\
loop:
  - step_name: worker
    system_prompt: "System."
"""
    )
    with pytest.raises(ValueError, match="missing required field 'task_prompt'"):
        load_config(cfg_file)


def test_load_config_step_model_none_by_default(tmp_path):
    cfg_file = tmp_path / "ralph.yaml"
    cfg_file.write_text(
        """\
loop:
  - step_name: worker
    task_prompt: "Work."
    system_prompt: "System."
"""
    )
    config = load_config(cfg_file)
    assert config.loop[0].model is None


def test_parse_steps_setup_section_error_message(tmp_path):
    cfg_file = tmp_path / "ralph.yaml"
    cfg_file.write_text(
        """\
setup:
  - step_name: init
loop:
  - step_name: worker
    task_prompt: "Work."
    system_prompt: "System."
"""
    )
    with pytest.raises(ValueError, match=r"setup\[0\] is missing required field"):
        load_config(cfg_file)


def test_load_config_max_iterations_coerced_to_int(tmp_path):
    cfg_file = tmp_path / "ralph.yaml"
    cfg_file.write_text(
        """\
max_iterations: "3"
loop:
  - step_name: worker
    task_prompt: "Work."
    system_prompt: "System."
"""
    )
    config = load_config(cfg_file)
    assert config.max_iterations == 3


def test_load_config_state_dir_default(tmp_path):
    """Config without state_dir uses the default."""
    cfg_file = tmp_path / "ralph.yaml"
    cfg_file.write_text(
        """\
loop:
  - step_name: worker
    task_prompt: "Work."
    system_prompt: "System."
"""
    )
    config = load_config(cfg_file)
    assert config.state_dir == STATE_DIR


def test_load_config_state_dir_custom(tmp_path):
    """Config with state_dir overrides the default."""
    cfg_file = tmp_path / "ralph.yaml"
    cfg_file.write_text(
        """\
state_dir: .custom-state
loop:
  - step_name: worker
    task_prompt: "Work."
    system_prompt: "System."
"""
    )
    config = load_config(cfg_file)
    assert config.state_dir == ".custom-state"
