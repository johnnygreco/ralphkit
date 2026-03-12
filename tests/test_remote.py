import subprocess
from unittest.mock import patch

import pytest

from ralphkit.remote import (
    _ssh_run,
    _ralph_cmd,
    _is_prerelease,
    submit_job,
    list_jobs,
    cancel_job,
    tail_logs,
)


_OK = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")


def test_ralph_cmd_default():
    cmd = _ralph_cmd(["--model", "opus", "do stuff"], subcommand="build")
    assert (
        cmd
        == "uvx --refresh --from ralphkit@latest ralphkit build --model opus 'do stuff'"
    )


def test_ralph_cmd_with_version():
    cmd = _ralph_cmd(["do stuff"], ralph_version="0.5.0", subcommand="fix")
    assert cmd == "uvx --refresh --from ralphkit==0.5.0 ralphkit fix 'do stuff'"


def test_ralph_cmd_auto_detects_prerelease():
    cmd = _ralph_cmd(["do stuff"], ralph_version="0.6.0a1", subcommand="build")
    assert (
        cmd
        == "uvx --refresh --from ralphkit==0.6.0a1 --prerelease allow ralphkit build 'do stuff'"
    )


def test_ralph_cmd_no_prerelease_for_stable():
    cmd = _ralph_cmd(["do stuff"], ralph_version="0.6.0", subcommand="build")
    assert cmd == "uvx --refresh --from ralphkit==0.6.0 ralphkit build 'do stuff'"


def test_ralph_cmd_with_subcommand():
    cmd = _ralph_cmd(["task.md", "--force"], subcommand="build")
    assert cmd == "uvx --refresh --from ralphkit@latest ralphkit build task.md --force"


def test_ralph_cmd_with_subcommand_and_version():
    cmd = _ralph_cmd(["task.md"], ralph_version="0.5.0", subcommand="fix")
    assert cmd == "uvx --refresh --from ralphkit==0.5.0 ralphkit fix task.md"


@pytest.mark.parametrize(
    "version,expected",
    [
        ("0.6.0a1", True),
        ("0.6.0b2", True),
        ("0.6.0rc1", True),
        ("0.6.0dev1", True),
        ("0.6.0alpha1", True),
        ("0.6.0beta3", True),
        ("0.6.0", False),
        ("1.0.0", False),
        ("1.2.3", False),
    ],
)
def test_is_prerelease(version, expected):
    assert _is_prerelease(version) == expected


@patch("ralphkit.remote.subprocess.run")
def test_submit_job_full_flow(mock_run):
    mock_run.return_value = _OK
    submit_job(
        "dev.example.com",
        "rk-abc123",
        ["--model", "opus", "do stuff"],
        subcommand="build",
    )

    calls = mock_run.call_args_list
    # SSH args are ["ssh", "-o", "ConnectTimeout=10", host, cmd] so cmd is at index 4
    # Pre-flight: tmux check
    assert "command -v tmux" in calls[0][0][0][4]
    # Resolve remote home
    assert "echo $HOME" in calls[1][0][0][4]
    # mkdir -p (once, before uploads)
    assert "mkdir -p" in calls[2][0][0][4]
    # Upload script (no mkdir -p)
    assert "mkdir -p" not in calls[3][0][0][4]
    assert "cat >" in calls[3][0][0][4]
    # Launch tmux
    assert "tmux new-session" in calls[4][0][0][4]
    assert "remain-on-exit" in calls[4][0][0][4]
    assert len(calls) == 5


@patch("ralphkit.remote.subprocess.run")
def test_submit_job_with_working_dir(mock_run):
    mock_run.return_value = _OK
    submit_job(
        "dev.example.com",
        "rk-abc123",
        ["do stuff"],
        subcommand="build",
        working_dir="/opt/app",
    )

    calls = mock_run.call_args_list
    # Pre-flight: tmux check
    assert "command -v tmux" in calls[0][0][0][4]
    # Pre-flight: working dir check
    assert "/opt/app" in calls[1][0][0][4]
    # echo $HOME, mkdir -p, upload script, launch = 6 calls total
    assert len(calls) == 6


@patch("ralphkit.remote.subprocess.run")
def test_submit_job_with_ralph_version(mock_run):
    mock_run.return_value = _OK
    submit_job(
        "dev.example.com",
        "rk-abc123",
        ["do stuff"],
        subcommand="build",
        ralph_version="0.5.0",
    )

    calls = mock_run.call_args_list
    # The uploaded script should contain uvx --from ralphkit==0.5.0
    # calls[0]=tmux check, calls[1]=echo $HOME, calls[2]=mkdir, calls[3]=upload script
    upload_call = calls[3]
    script_content = upload_call[1]["input"]
    assert "uvx --refresh --from ralphkit==0.5.0 ralphkit" in script_content


@patch("ralphkit.remote.subprocess.run")
def test_submit_job_with_config_content(mock_run):
    mock_run.return_value = _OK
    submit_job(
        "dev.example.com",
        "rk-abc123",
        ["do stuff"],
        subcommand="loop",
        config_content="max_iterations: 3\nloop:\n  - step_name: w\n",
    )

    calls = mock_run.call_args_list
    # calls: tmux check, echo $HOME, mkdir, config upload, script upload, tmux launch
    assert len(calls) == 6
    # mkdir -p (once)
    assert "mkdir -p" in calls[2][0][0][4]
    # Config upload (no mkdir -p)
    config_call = calls[3]
    assert "rk-abc123.config.yaml" in config_call[0][0][4]
    assert "mkdir -p" not in config_call[0][0][4]
    assert config_call[1]["input"] == "max_iterations: 3\nloop:\n  - step_name: w\n"
    # Script should reference the config path
    script_call = calls[4]
    script_content = script_call[1]["input"]
    assert "--config" in script_content
    assert "rk-abc123.config.yaml" in script_content


@patch("ralphkit.remote.subprocess.run")
def test_submit_job_with_plan_content(mock_run):
    mock_run.return_value = _OK
    submit_job(
        "dev.example.com",
        "rk-abc123",
        ["do stuff"],
        subcommand="build",
        plan_content='{"items": [{"id": 1, "title": "test", "done": false}]}',
    )
    calls = mock_run.call_args_list
    # calls: tmux check, echo $HOME, mkdir, plan upload, script upload, tmux launch
    assert len(calls) == 6
    plan_uploads = [
        c for c in calls if c[1].get("input") and "items" in str(c[1]["input"])
    ]
    assert len(plan_uploads) == 1
    assert "tickets.json" in plan_uploads[0][0][0][4]
    assert "mkdir -p" not in plan_uploads[0][0][0][4]


@patch("ralphkit.remote.subprocess.run")
def test_submit_job_with_subcommand(mock_run):
    mock_run.return_value = _OK
    submit_job(
        "dev.example.com", "rk-abc123", ["task.md", "--force"], subcommand="build"
    )

    calls = mock_run.call_args_list
    # calls[0]=tmux check, calls[1]=echo $HOME, calls[2]=mkdir, calls[3]=script upload
    upload_call = calls[3]
    script_content = upload_call[1]["input"]
    assert "ralphkit build task.md --force" in script_content
    assert "ralphkit run" not in script_content


@patch("ralphkit.remote.subprocess.run")
def test_submit_job_no_tmux(mock_run):
    mock_run.return_value = subprocess.CompletedProcess(
        args=[], returncode=1, stdout="", stderr=""
    )
    with pytest.raises(SystemExit, match="tmux is not installed"):
        submit_job("dev.example.com", "rk-abc123", ["do stuff"], subcommand="build")


@patch("ralphkit.remote.subprocess.run")
def test_submit_job_working_dir_missing(mock_run):
    mock_run.side_effect = [
        _OK,
        subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr=""),
    ]
    with pytest.raises(SystemExit, match="Working directory does not exist"):
        submit_job(
            "dev.example.com",
            "rk-abc123",
            ["do stuff"],
            subcommand="build",
            working_dir="/bad/path",
        )


@patch("ralphkit.remote.subprocess.run")
def test_list_jobs_parses_output(mock_run):
    mock_run.return_value = subprocess.CompletedProcess(
        args=[],
        returncode=0,
        stdout="rk-abc123\t1234567890\t1234567891\t0\nrk-def456\t1234567892\t1234567893\t1\n",
        stderr="",
    )
    result = list_jobs("dev.example.com")
    assert len(result) == 2
    assert result[0]["name"] == "rk-abc123"
    assert result[1]["name"] == "rk-def456"


@patch("ralphkit.remote.subprocess.run")
def test_list_jobs_returns_empty_on_failure(mock_run):
    mock_run.return_value = subprocess.CompletedProcess(
        args=[], returncode=1, stdout="", stderr=""
    )
    assert list_jobs("dev.example.com") == []


@patch("ralphkit.remote.subprocess.run")
def test_cancel_job_success(mock_run):
    mock_run.return_value = _OK
    cancel_job("dev.example.com", "rk-abc123")  # should not raise


@patch("ralphkit.remote.subprocess.run")
def test_cancel_job_missing_raises_system_exit(mock_run):
    mock_run.return_value = subprocess.CompletedProcess(
        args=[], returncode=1, stdout="", stderr=""
    )
    with pytest.raises(SystemExit, match="No job 'rk-missing'"):
        cancel_job("dev.example.com", "rk-missing")


@patch("ralphkit.remote.subprocess.run")
def test_tail_logs_calls_ssh_with_correct_args(mock_run):
    mock_run.return_value = _OK
    tail_logs("dev.example.com", "rk-abc123")

    args = mock_run.call_args[0][0]
    assert "ssh" in args
    assert "-t" in args
    cmd_str = args[-1]
    assert "tail" in cmd_str
    assert '"$HOME/' in cmd_str


@patch("ralphkit.remote.subprocess.run")
def test_tail_logs_follow_flag(mock_run):
    mock_run.return_value = _OK
    tail_logs("dev.example.com", "rk-abc123", follow=True)

    cmd_str = mock_run.call_args[0][0][-1]
    assert "tail -f" in cmd_str


@patch("ralphkit.remote.subprocess.run")
def test_ssh_run_connection_refused(mock_run):
    mock_run.side_effect = subprocess.CalledProcessError(
        255, "ssh", stderr="Connection refused"
    )
    with pytest.raises(SystemExit, match="SSH connection to 'dev.example.com' failed"):
        _ssh_run("dev.example.com", "echo hello")


@patch("ralphkit.remote.subprocess.run")
def test_ssh_run_auth_failure(mock_run):
    mock_run.side_effect = subprocess.CalledProcessError(
        255, "ssh", stderr="Permission denied (publickey)"
    )
    with pytest.raises(SystemExit, match="Permission denied"):
        _ssh_run("dev.example.com", "echo hello")


@patch("ralphkit.remote.subprocess.run")
def test_ssh_run_includes_connect_timeout(mock_run):
    mock_run.return_value = _OK
    _ssh_run("dev.example.com", "echo hello", check=False)
    args = mock_run.call_args[0][0]
    assert "-o" in args
    assert "ConnectTimeout=10" in args
