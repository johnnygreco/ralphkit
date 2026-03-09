"""Tests for CLI subcommands and dispatch."""

from unittest.mock import patch

from typer.testing import CliRunner

from ralphkit.cli import app


runner = CliRunner()


# -- Help and version --


def test_help_shows_commands():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "build" in result.output
    assert "fix" in result.output
    assert "research" in result.output
    assert "plan" in result.output
    assert "big-swing" in result.output
    assert "pipe" in result.output
    assert "loop" in result.output
    assert "runs" in result.output
    assert "jobs" in result.output
    assert "logs" in result.output
    assert "cancel" in result.output


def test_version_flag():
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert "ralphkit" in result.output


def test_old_commands_removed():
    """run and submit commands no longer exist."""
    result = runner.invoke(app, ["--help"])
    # 'runs' is valid, but bare 'run ' as a subcommand should not appear
    lines = result.output.split("\n")
    command_lines = [l.strip() for l in lines if l.strip()]
    # Check no line starts with 'run ' (the run command) — 'runs' is fine
    assert not any(l.startswith("run ") for l in command_lines)
    assert "submit" not in result.output


# -- build command --


@patch("ralphkit.engine.run_foreground")
def test_build_foreground(mock_fg):
    """build command calls run_foreground with a RalphConfig."""
    mock_fg.side_effect = SystemExit(0)
    runner.invoke(app, ["build", "Add tests", "-f"])
    mock_fg.assert_called_once()
    kwargs = mock_fg.call_args.kwargs
    assert kwargs["task"] == "Add tests"
    assert kwargs["force"] is True
    assert kwargs["ralph_config"] is not None
    assert len(kwargs["ralph_config"].loop) > 0
    assert len(kwargs["ralph_config"].cleanup) > 0


@patch("ralphkit.engine.run_foreground")
def test_build_passes_options(mock_fg):
    """build forwards all options to run_foreground."""
    mock_fg.side_effect = SystemExit(0)
    runner.invoke(
        app,
        [
            "build",
            "my task",
            "--max-iterations",
            "5",
            "--default-model",
            "sonnet",
            "--state-dir",
            "/tmp/test",
            "--plan-model",
            "haiku",
            "-f",
        ],
    )
    mock_fg.assert_called_once()
    kwargs = mock_fg.call_args.kwargs
    assert kwargs["task"] == "my task"
    assert kwargs["max_iterations"] == 5
    assert kwargs["default_model"] == "sonnet"
    assert kwargs["state_dir"] == "/tmp/test"
    assert kwargs["plan_model"] == "haiku"
    assert kwargs["force"] is True


# -- fix command --


@patch("ralphkit.engine.run_foreground")
def test_fix_foreground(mock_fg):
    """fix command creates pipe config with 3 steps."""
    mock_fg.side_effect = SystemExit(0)
    runner.invoke(app, ["fix", "Bug report", "-f"])
    mock_fg.assert_called_once()
    kwargs = mock_fg.call_args.kwargs
    assert kwargs["task"] == "Bug report"
    assert len(kwargs["ralph_config"].pipe) == 3


# -- research command --


@patch("ralphkit.engine.run_foreground")
def test_research_foreground(mock_fg):
    """research command creates pipe config with 3 steps."""
    mock_fg.side_effect = SystemExit(0)
    runner.invoke(app, ["research", "Topic", "-f"])
    mock_fg.assert_called_once()
    assert len(mock_fg.call_args.kwargs["ralph_config"].pipe) == 3


# -- plan command --


@patch("ralphkit.engine.run_foreground")
def test_plan_foreground(mock_fg):
    """plan command creates pipe config with 2 steps."""
    mock_fg.side_effect = SystemExit(0)
    runner.invoke(app, ["plan", "Design task", "-f"])
    mock_fg.assert_called_once()
    assert len(mock_fg.call_args.kwargs["ralph_config"].pipe) == 2


# -- big-swing command --


@patch("ralphkit.engine.run_foreground")
def test_big_swing_foreground(mock_fg):
    """big-swing command creates pipe config with 6 steps."""
    mock_fg.side_effect = SystemExit(0)
    runner.invoke(app, ["big-swing", "Epic task", "-f"])
    mock_fg.assert_called_once()
    assert len(mock_fg.call_args.kwargs["ralph_config"].pipe) == 6


# -- background dispatch --


@patch("ralphkit.local.shutil.which", return_value="/usr/bin/tmux")
@patch("ralphkit.local.subprocess.run")
def test_build_host_local(mock_run, mock_which):
    """build --host local submits to local tmux."""
    mock_run.return_value = __import__("subprocess").CompletedProcess(
        args=[], returncode=0
    )
    result = runner.invoke(app, ["build", "do stuff", "--host", "local"])
    assert result.exit_code == 0
    assert "Submitted" in result.output


@patch("ralphkit.remote.subprocess.run")
def test_fix_host_remote(mock_run):
    """fix --host <name> submits via SSH."""
    mock_run.return_value = __import__("subprocess").CompletedProcess(
        args=[], returncode=0, stdout="", stderr=""
    )
    result = runner.invoke(app, ["fix", "bug report", "--host", "dev.example.com"])
    assert result.exit_code == 0
    assert "Submitted" in result.output
    assert "dev.example.com" in result.output


# -- runs command --


def test_runs_empty(tmp_path):
    result = runner.invoke(app, ["runs", "--state-dir", str(tmp_path)])
    assert "No runs found." in result.output


def test_runs_shows_entries(tmp_path):
    runs_dir = tmp_path / "runs"
    (runs_dir / "001").mkdir(parents=True)
    (runs_dir / "001" / "task.md").write_text("first task\ndetails")
    (runs_dir / "002").mkdir()
    (runs_dir / "002" / "task.md").write_text("second task")

    result = runner.invoke(app, ["runs", "--state-dir", str(tmp_path)])
    assert "#001" in result.output
    assert "first task" in result.output
    assert "#002" in result.output
    assert "second task" in result.output


# -- jobs command --


@patch("ralphkit.local.subprocess.run")
def test_jobs_local_empty(mock_run):
    mock_run.return_value = __import__("subprocess").CompletedProcess(
        args=[], returncode=1, stdout="", stderr=""
    )
    result = runner.invoke(app, ["jobs"])
    assert "No active jobs" in result.output


@patch("ralphkit.remote.subprocess.run")
def test_jobs_remote(mock_run):
    mock_run.return_value = __import__("subprocess").CompletedProcess(
        args=[],
        returncode=0,
        stdout="rk-test-0307-1200-ab12\t1709812800\t1709812900\t0\n",
        stderr="",
    )
    result = runner.invoke(app, ["jobs", "--host", "dev.example.com"])
    assert result.exit_code == 0
    assert "rk-test" in result.output


# -- logs command --


def test_logs_local_missing(tmp_path):
    with patch("ralphkit.local.log_path_local", return_value=tmp_path / "nope.log"):
        result = runner.invoke(app, ["logs", "rk-nonexistent"])
    assert result.exit_code != 0


# -- cancel command --


@patch("ralphkit.local.subprocess.run")
def test_cancel_local_success(mock_run):
    mock_run.return_value = __import__("subprocess").CompletedProcess(
        args=[], returncode=0, stdout="", stderr=""
    )
    result = runner.invoke(app, ["cancel", "rk-abc123"])
    assert "Cancelled" in result.output
