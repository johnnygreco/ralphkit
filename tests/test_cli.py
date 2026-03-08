"""Tests for CLI command routing (Typer + RalphGroup)."""

from unittest.mock import patch

from typer.testing import CliRunner

from ralphkit.cli import app


runner = CliRunner()


# -- Default command routing --


@patch("ralphkit.engine.run_foreground")
def test_bare_task_routes_to_run(mock_fg):
    """ralph 'Add tests' routes to run command."""
    mock_fg.side_effect = SystemExit(0)
    runner.invoke(app, ["Add tests"])
    mock_fg.assert_called_once()
    assert mock_fg.call_args.kwargs["task"] == "Add tests"


@patch("ralphkit.engine.run_foreground")
def test_explicit_run_command(mock_fg):
    """ralph run 'Add tests' calls run_foreground directly."""
    mock_fg.side_effect = SystemExit(0)
    runner.invoke(app, ["run", "Add tests"])
    mock_fg.assert_called_once()
    assert mock_fg.call_args.kwargs["task"] == "Add tests"


def test_help_shows_commands():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "run" in result.output
    assert "runs" in result.output
    assert "submit" in result.output
    assert "jobs" in result.output
    assert "logs" in result.output
    assert "cancel" in result.output


def test_runs_command_not_confused_with_run():
    """ralph runs should route to the runs command, not run('runs')."""
    result = runner.invoke(app, ["runs", "--state-dir", "/nonexistent"])
    # Should print "No runs found." since /nonexistent has no runs
    assert "No runs found." in result.output


def test_version_flag():
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert "ralphkit" in result.output


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


# -- run command options --


@patch("ralphkit.engine.run_foreground")
def test_run_passes_all_options(mock_fg, tmp_path):
    """All CLI options are forwarded to run_foreground."""
    cfg = tmp_path / "ralph.yaml"
    cfg.write_text(
        "max_iterations: 1\nloop:\n  - step_name: w\n    task_prompt: W\n    system_prompt: S\n"
    )
    mock_fg.side_effect = SystemExit(0)

    runner.invoke(
        app,
        [
            "run",
            "my task",
            "--config",
            str(cfg),
            "--max-iterations",
            "5",
            "--default-model",
            "sonnet",
            "--state-dir",
            "/tmp/test",
            "-f",
        ],
    )
    mock_fg.assert_called_once()
    kwargs = mock_fg.call_args.kwargs
    assert kwargs["task"] == "my task"
    assert kwargs["config_path"] == str(cfg)
    assert kwargs["max_iterations"] == 5
    assert kwargs["default_model"] == "sonnet"
    assert kwargs["state_dir"] == "/tmp/test"
    assert kwargs["force"] is True


@patch("ralphkit.engine.run_foreground")
def test_run_no_task_for_pipe_mode(mock_fg):
    """run with no task argument passes None."""
    mock_fg.side_effect = SystemExit(0)
    runner.invoke(app, ["run"])
    mock_fg.assert_called_once()
    assert mock_fg.call_args.kwargs["task"] is None


@patch("ralphkit.engine.run_foreground")
def test_run_plan_flags_forwarded(mock_fg, tmp_path):
    """--plan, --plan-only, --plan-model are forwarded."""
    plan_file = tmp_path / "tickets.json"
    plan_file.write_text('{"items": []}')
    mock_fg.side_effect = SystemExit(0)

    runner.invoke(
        app,
        [
            "run",
            "my task",
            "--plan",
            str(plan_file),
            "--plan-only",
            "--plan-model",
            "sonnet",
            "-f",
        ],
    )
    mock_fg.assert_called_once()
    kwargs = mock_fg.call_args.kwargs
    assert kwargs["plan_path"] == str(plan_file)
    assert kwargs["plan_only"] is True
    assert kwargs["plan_model"] == "sonnet"


# -- submit command --


@patch("ralphkit.local.shutil.which", return_value="/usr/bin/tmux")
@patch("ralphkit.local.subprocess.run")
def test_submit_local(mock_run, mock_which):
    mock_run.return_value = __import__("subprocess").CompletedProcess(
        args=[], returncode=0
    )
    result = runner.invoke(app, ["submit", "do stuff"])
    assert result.exit_code == 0
    assert "Submitted" in result.output


@patch("ralphkit.remote.subprocess.run")
def test_submit_remote(mock_run):
    mock_run.return_value = __import__("subprocess").CompletedProcess(
        args=[], returncode=0, stdout="", stderr=""
    )
    result = runner.invoke(app, ["submit", "do stuff", "--host", "dev.example.com"])
    assert result.exit_code == 0
    assert "Submitted" in result.output
    assert "dev.example.com" in result.output


@patch("ralphkit.remote.subprocess.run")
def test_submit_remote_resolves_task_file(mock_run, tmp_path):
    """Task .md files are read locally and content is sent to remote."""
    mock_run.return_value = __import__("subprocess").CompletedProcess(
        args=[], returncode=0, stdout="", stderr=""
    )
    task_file = tmp_path / "task.md"
    task_file.write_text("# Refactor auth\nDo the thing.")

    result = runner.invoke(app, ["submit", str(task_file), "--host", "dev.example.com"])
    assert result.exit_code == 0
    # The uploaded script should contain the file content, not the file path
    calls = mock_run.call_args_list
    # Find the script upload call (has input= with script content)
    script_content = None
    for call in calls:
        inp = call[1].get("input", "")
        if inp and "ralph run" in inp:
            script_content = inp
            break
    assert script_content is not None
    assert "Refactor auth" in script_content
    assert str(task_file) not in script_content


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
