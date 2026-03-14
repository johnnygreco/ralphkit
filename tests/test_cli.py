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


def test_old_commands_hidden_from_help():
    """run and submit don't appear in --help output."""
    result = runner.invoke(app, ["--help"])
    lines = result.output.split("\n")
    command_lines = [line.strip() for line in lines if line.strip()]
    assert not any(line.startswith("run ") for line in command_lines)
    assert not any(line.startswith("submit ") for line in command_lines)


def test_old_commands_show_deprecation():
    """run and submit show deprecation messages."""
    result = runner.invoke(app, ["run", "my task"])
    assert result.exit_code != 0
    assert "removed" in _strip_ansi(result.output).lower()
    assert "build" in _strip_ansi(result.output)

    result = runner.invoke(app, ["submit", "my task"])
    assert result.exit_code != 0
    assert "removed" in _strip_ansi(result.output).lower()
    assert "--host" in _strip_ansi(result.output)


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
            "--timeout-seconds",
            "1200",
            "--idle-timeout-seconds",
            "90",
            "--cleanup-on-error",
            "skip",
            "--plan-model",
            "haiku",
            "--resume-run",
            "12",
            "-f",
        ],
    )
    mock_fg.assert_called_once()
    kwargs = mock_fg.call_args.kwargs
    assert kwargs["task"] == "my task"
    assert kwargs["max_iterations"] == 5
    assert kwargs["default_model"] == "sonnet"
    assert kwargs["state_dir"] == "/tmp/test"
    assert kwargs["timeout_seconds"] == 1200
    assert kwargs["idle_timeout_seconds"] == 90
    assert kwargs["cleanup_on_error"] == "skip"
    assert kwargs["plan_model"] == "haiku"
    assert kwargs["resume_run"] == "12"
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


# -- pipe step names --


@patch("ralphkit.engine.run_foreground")
def test_fix_foreground_step_names(mock_fg):
    """fix command wires correct factory with correct step names."""
    mock_fg.side_effect = SystemExit(0)
    runner.invoke(app, ["fix", "Bug report", "-f"])
    mock_fg.assert_called_once()
    pipe = mock_fg.call_args.kwargs["ralph_config"].pipe
    assert [s.step_name for s in pipe] == ["diagnose", "fix", "verify"]


@patch("ralphkit.engine.run_foreground")
def test_research_foreground_step_names(mock_fg):
    """research command wires correct step names."""
    mock_fg.side_effect = SystemExit(0)
    runner.invoke(app, ["research", "Topic", "-f"])
    pipe = mock_fg.call_args.kwargs["ralph_config"].pipe
    assert [s.step_name for s in pipe] == ["explore", "synthesize", "report"]


@patch("ralphkit.engine.run_foreground")
def test_plan_foreground_step_names(mock_fg):
    """plan command wires correct step names."""
    mock_fg.side_effect = SystemExit(0)
    runner.invoke(app, ["plan", "Design task", "-f"])
    pipe = mock_fg.call_args.kwargs["ralph_config"].pipe
    assert [s.step_name for s in pipe] == ["analyze", "design"]


@patch("ralphkit.engine.run_foreground")
def test_big_swing_foreground_step_names(mock_fg):
    """big-swing command wires correct step names."""
    mock_fg.side_effect = SystemExit(0)
    runner.invoke(app, ["big-swing", "Epic task", "-f"])
    pipe = mock_fg.call_args.kwargs["ralph_config"].pipe
    assert [s.step_name for s in pipe] == [
        "research",
        "plan",
        "build",
        "review",
        "fix",
        "verify",
    ]


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


@patch("ralphkit.local.shutil.which", return_value="/usr/bin/tmux")
@patch("ralphkit.local.subprocess.run")
def test_build_host_local_forwards_options(mock_run, mock_which, tmp_path):
    """build --host local forwards --max-iterations, --plan-model, --plan-only."""
    mock_run.return_value = __import__("subprocess").CompletedProcess(
        args=[], returncode=0
    )
    with patch("ralphkit.local.script_path_local", return_value=tmp_path / "job.sh"):
        result = runner.invoke(
            app,
            [
                "build",
                "task",
                "--host",
                "local",
                "--max-iterations",
                "3",
                "--timeout-seconds",
                "900",
                "--idle-timeout-seconds",
                "45",
                "--cleanup-on-error",
                "skip",
                "--resume-run",
                "7",
                "--isolation",
                "worktree",
                "--plan-model",
                "haiku",
                "--plan-only",
            ],
        )
    assert result.exit_code == 0
    script = (tmp_path / "job.sh").read_text()
    assert "--max-iterations 3" in script
    assert "--timeout-seconds 900" in script
    assert "--idle-timeout-seconds 45" in script
    assert "--cleanup-on-error skip" in script
    assert "--plan-model haiku" in script
    assert "--plan-only" in script
    assert "--resume-run 7" in script
    assert "--force" in script
    assert 'WORKTREE_DIR="$JOB_DIR/worktree"' in script
    assert 'export RALPHKIT_WORKING_DIR="$WORKTREE_DIR"' in script


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


@patch("ralphkit.local.subprocess.run")
def test_jobs_host_local_uses_local(mock_run):
    """jobs --host local should list local jobs, not SSH to 'local'."""
    mock_run.return_value = __import__("subprocess").CompletedProcess(
        args=[], returncode=1, stdout="", stderr=""
    )
    result = runner.invoke(app, ["jobs", "--host", "local"])
    assert "No active jobs" in result.output
    # Verify it called tmux list-sessions, not ssh
    call_args = mock_run.call_args[0][0]
    assert call_args[0] == "tmux"


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


def test_loop_without_task_errors(tmp_path):
    """loop command without a task shows an error before doing any work."""
    cfg = tmp_path / "loop.yaml"
    cfg.write_text(
        "loop:\n  - step_name: w\n    task_prompt: W.\n    system_prompt: S.\n"
    )
    result = runner.invoke(app, ["loop", "--config", str(cfg)])
    assert result.exit_code != 0
    plain = _strip_ansi(result.output)
    assert "task is required" in plain


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
def test_host_auto_injects_force(mock_run, mock_which, tmp_path):
    """--host should auto-inject --force in background job args."""
    mock_run.return_value = __import__("subprocess").CompletedProcess(
        args=[], returncode=0
    )
    with patch("ralphkit.local.script_path_local", return_value=tmp_path / "job.sh"):
        result = runner.invoke(app, ["build", "do stuff", "--host", "local"])
    assert result.exit_code == 0
    script = (tmp_path / "job.sh").read_text()
    assert "--force" in script


@patch("ralphkit.remote.subprocess.run")
def test_remote_dispatch_includes_force(mock_run):
    """Remote dispatch auto-injects --force in CLI args."""
    mock_run.return_value = __import__("subprocess").CompletedProcess(
        args=[], returncode=0, stdout="", stderr=""
    )
    result = runner.invoke(app, ["research", "topic", "--host", "dev.example.com"])
    assert result.exit_code == 0
    calls = mock_run.call_args_list
    metadata_calls = [
        c
        for c in calls
        if c[1].get("input") and '"subcommand": "research"' in c[1]["input"]
    ]
    script_calls = [
        c for c in calls if c[1].get("input") and "ralphkit research" in c[1]["input"]
    ]
    assert len(metadata_calls) == 1
    assert "--force" in metadata_calls[0][1]["input"]
    assert len(script_calls) == 1
    assert "--force" in script_calls[0][1]["input"]


# -- remote dispatch with config --


@patch("ralphkit.remote.subprocess.run")
def test_pipe_host_remote_uploads_config(mock_run, tmp_path):
    """pipe --host remote --config uploads config content."""
    mock_run.return_value = __import__("subprocess").CompletedProcess(
        args=[], returncode=0, stdout="", stderr=""
    )
    cfg = tmp_path / "pipe.yaml"
    cfg.write_text(
        "pipe:\n  - step_name: s1\n    task_prompt: P.\n    system_prompt: S.\n"
    )
    result = runner.invoke(
        app, ["pipe", "task", "--config", str(cfg), "--host", "dev.example.com"]
    )
    assert result.exit_code == 0
    calls = mock_run.call_args_list
    config_uploads = [
        c for c in calls if c[1].get("input") and "pipe:" in str(c[1]["input"])
    ]
    assert len(config_uploads) >= 1


# -- subcommand dispatch names --


@patch("ralphkit.remote.subprocess.run")
def test_build_host_remote_uploads_plan(mock_run, tmp_path):
    """build --host remote --plan uploads plan file."""
    mock_run.return_value = __import__("subprocess").CompletedProcess(
        args=[], returncode=0, stdout="", stderr=""
    )
    plan_file = tmp_path / "tickets.json"
    plan_file.write_text('{"items": []}')
    result = runner.invoke(
        app,
        [
            "build",
            "task",
            "--host",
            "dev.example.com",
            "--plan",
            str(plan_file),
        ],
    )
    assert result.exit_code == 0
    calls = mock_run.call_args_list
    plan_uploads = [
        c for c in calls if c[1].get("input") and "items" in str(c[1]["input"])
    ]
    assert len(plan_uploads) >= 1


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


# -- validation: --working-dir / --ralph-version require --host --


def test_working_dir_without_host_errors():
    """--working-dir without --host should error."""
    result = runner.invoke(app, ["build", "task", "--working-dir", "/tmp/x", "-f"])
    assert result.exit_code != 0
    assert "--host" in _strip_ansi(result.output)


def test_ralph_version_without_host_errors():
    """--ralph-version without --host should error."""
    result = runner.invoke(app, ["fix", "bug", "--ralph-version", "0.5.0", "-f"])
    assert result.exit_code != 0
    assert "--host" in _strip_ansi(result.output)
