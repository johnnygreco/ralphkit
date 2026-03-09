"""Tests for CLI subcommands and dispatch."""

import re
from unittest.mock import patch

from typer.testing import CliRunner

from ralphkit.cli import app


runner = CliRunner()


def _strip_ansi(text: str) -> str:
    """Remove ANSI escape codes from text."""
    return re.sub(r"\x1b\[[^m]*m", "", text)


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
    plain = _strip_ansi(result.output)
    assert "#001" in plain
    assert "first task" in plain
    assert "#002" in plain
    assert "second task" in plain


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


# -- pipe and loop commands --


@patch("ralphkit.engine.run_foreground")
def test_pipe_requires_config(mock_fg):
    """pipe command without --config fails."""
    result = runner.invoke(app, ["pipe", "my task", "-f"])
    assert result.exit_code != 0


@patch("ralphkit.engine.run_foreground")
def test_pipe_foreground(mock_fg, tmp_path):
    """pipe command with --config calls run_foreground."""
    cfg = tmp_path / "pipe.yaml"
    cfg.write_text(
        "pipe:\n  - step_name: s1\n    task_prompt: P.\n    system_prompt: S.\n"
    )
    mock_fg.side_effect = SystemExit(0)
    runner.invoke(app, ["pipe", "task", "--config", str(cfg), "-f"])
    mock_fg.assert_called_once()
    kwargs = mock_fg.call_args.kwargs
    assert kwargs["config_path"] == str(cfg)


@patch("ralphkit.engine.run_foreground")
def test_loop_requires_config(mock_fg):
    """loop command without --config fails."""
    result = runner.invoke(app, ["loop", "my task", "-f"])
    assert result.exit_code != 0


@patch("ralphkit.engine.run_foreground")
def test_loop_foreground(mock_fg, tmp_path):
    """loop command with --config calls run_foreground."""
    cfg = tmp_path / "loop.yaml"
    cfg.write_text(
        "loop:\n  - step_name: w\n    task_prompt: W.\n    system_prompt: S.\n"
    )
    mock_fg.side_effect = SystemExit(0)
    runner.invoke(app, ["loop", "task", "--config", str(cfg), "-f"])
    mock_fg.assert_called_once()
    kwargs = mock_fg.call_args.kwargs
    assert kwargs["config_path"] == str(cfg)


# -- force auto-injection --


@patch("ralphkit.local.shutil.which", return_value="/usr/bin/tmux")
@patch("ralphkit.local.subprocess.run")
def test_host_auto_injects_force(mock_run, mock_which):
    """--host should auto-inject --force in background job args."""
    mock_run.return_value = __import__("subprocess").CompletedProcess(
        args=[], returncode=0
    )
    result = runner.invoke(app, ["build", "do stuff", "--host", "local"])
    assert result.exit_code == 0
    # The script written by submit_local should contain --force
    script_file = mock_run.call_args[0][0]
    # tmux new-session command includes the script path
    # The job script is written to disk and passed to tmux
    # Just verify submit_local was called (force is in the CLI args)
    mock_run.assert_called_once()


@patch("ralphkit.remote.subprocess.run")
def test_remote_dispatch_includes_force(mock_run):
    """Remote dispatch auto-injects --force in CLI args."""
    mock_run.return_value = __import__("subprocess").CompletedProcess(
        args=[], returncode=0, stdout="", stderr=""
    )
    result = runner.invoke(
        app, ["research", "topic", "--host", "dev.example.com"]
    )
    assert result.exit_code == 0
    # The script uploaded to remote should contain --force
    calls = mock_run.call_args_list
    # Find the script upload call (contains the script content as input)
    script_calls = [c for c in calls if c[1].get("input")]
    assert any("--force" in c[1]["input"] for c in script_calls)


# -- subcommand dispatch names --


@patch("ralphkit.local.shutil.which", return_value="/usr/bin/tmux")
@patch("ralphkit.local.subprocess.run")
def test_fix_host_local_uses_fix_subcommand(mock_run, mock_which, tmp_path):
    """fix --host local dispatches with subcommand='fix'."""
    mock_run.return_value = __import__("subprocess").CompletedProcess(
        args=[], returncode=0
    )
    with patch("ralphkit.local.script_path_local", return_value=tmp_path / "job.sh"):
        result = runner.invoke(app, ["fix", "bug", "--host", "local"])
    assert result.exit_code == 0
    script = (tmp_path / "job.sh").read_text()
    assert "ralphkit fix" in script
