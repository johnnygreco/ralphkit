from ralphkit.config import RalphConfig, load_config


def test_default_config():
    config = RalphConfig()
    assert config.worker_model == "opus"
    assert config.reviewer_model == "sonnet"
    assert config.max_iterations == 10
    assert config.task is None


def test_load_config_missing_file(tmp_path):
    config = load_config(tmp_path / "nonexistent.yaml")
    assert config == RalphConfig()


def test_load_config_partial(tmp_path):
    cfg_file = tmp_path / "ralph.yaml"
    cfg_file.write_text("worker_model: haiku\nmax_iterations: 5\n")
    config = load_config(cfg_file)
    assert config.worker_model == "haiku"
    assert config.reviewer_model == "sonnet"
    assert config.max_iterations == 5


def test_resolve_task_string():
    from ralphkit.cli import resolve_task

    assert resolve_task("do something", None) == "do something"
    assert resolve_task("do something", "ignored") == "do something"
    assert resolve_task(None, "from config") == "from config"
    assert resolve_task(None, None) is None


def test_resolve_task_md_file(tmp_path):
    from ralphkit.cli import resolve_task

    md = tmp_path / "task.md"
    md.write_text("# My Task\nDo the thing.")
    assert resolve_task(str(md), None) == "# My Task\nDo the thing."
