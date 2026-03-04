import argparse

import pytest

from ralphkit.cli import merge_config, resolve_task
from ralphkit.config import RalphConfig, load_config


def test_default_config():
    config = RalphConfig()
    assert config.worker_model == "opus"
    assert config.reviewer_model == "sonnet"
    assert config.max_iterations == 10


def test_load_config_none():
    config = load_config(None)
    assert config == RalphConfig()


def test_load_config_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_config(tmp_path / "nonexistent.yaml")


def test_load_config_partial(tmp_path):
    cfg_file = tmp_path / "ralph.yaml"
    cfg_file.write_text("worker_model: haiku\nmax_iterations: 5\n")
    config = load_config(cfg_file)
    assert config.worker_model == "haiku"
    assert config.reviewer_model == "sonnet"
    assert config.max_iterations == 5


def test_load_config_ignores_unknown_keys(tmp_path):
    cfg_file = tmp_path / "ralph.yaml"
    cfg_file.write_text("worker_model: haiku\ntask: do stuff\n")
    config = load_config(cfg_file)
    assert config.worker_model == "haiku"


def test_resolve_task_string():
    assert resolve_task("do something") == "do something"


def test_resolve_task_md_file(tmp_path):
    md = tmp_path / "task.md"
    md.write_text("# My Task\nDo the thing.")
    assert resolve_task(str(md)) == "# My Task\nDo the thing."


def test_resolve_task_missing_md():
    assert resolve_task("nonexistent.md") == "nonexistent.md"


def test_merge_config_no_overrides():
    config = RalphConfig(worker_model="haiku", max_iterations=5)
    args = argparse.Namespace(
        worker_model=None, reviewer_model=None, max_iterations=None
    )
    result = merge_config(config, args)
    assert result == config


def test_merge_config_cli_overrides():
    config = RalphConfig()
    args = argparse.Namespace(
        worker_model="haiku", reviewer_model=None, max_iterations=3
    )
    result = merge_config(config, args)
    assert result.worker_model == "haiku"
    assert result.reviewer_model == "sonnet"
    assert result.max_iterations == 3
