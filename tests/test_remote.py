import subprocess
from unittest.mock import patch

import pytest

from ralphkit.remote import (
    _ssh_run,
    _ralph_cmd,
    submit_job,
    list_jobs,
    cancel_job,
    get_attach_command,
    tail_logs,
)


_OK = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")


def test_ralph_cmd_default():
    cmd = _ralph_cmd(["--model", "opus", "do stuff"])
    assert cmd == "uvx --from ralphkit@latest ralph run --model opus 'do stuff'"


def test_ralph_cmd_with_version():
    cmd = _ralph_cmd(["do stuff"], ralph_version="0.5.0")
    assert cmd == "uvx --from ralphkit==0.5.0 ralph run 'do stuff'"


def test_ralph_cmd_with_prerelease():
    cmd = _ralph_cmd(["do stuff"], allow_prerelease=True)
    assert cmd == "uvx --from ralphkit@latest --prerelease allow ralph run 'do stuff'"


def test_ralph_cmd_with_version_and_prerelease():
    cmd = _ralph_cmd(["do stuff"], ralph_version="0.6.0a1", allow_prerelease=True)
    assert cmd == "uvx --from ralphkit==0.6.0a1 --prerelease allow ralph run 'do stuff'"


@patch("ralphkit.remote.subprocess.run")
def test_submit_job_full_flow(mock_run):
    mock_run.return_value = _OK
    submit_job("dev.example.com", "rk-abc123", ["--model", "opus", "do stuff"])

    calls = mock_run.call_args_list
    # SSH args are ["ssh", "-o", "ConnectTimeout=10", host, cmd] so cmd is at index 4
    # Pre-flight: tmux check
    assert "command -v tmux" in calls[0][0][0][4]
    # Upload script (no working dir = skip dir check)
    assert "mkdir -p" in calls[1][0][0][4]
    # Launch tmux
    assert "tmux new-session" in calls[2][0][0][4]
    assert "remain-on-exit" in calls[2][0][0][4]
    assert len(calls) == 3


@patch("ralphkit.remote.subprocess.run")
def test_submit_job_with_working_dir(mock_run):
    mock_run.return_value = _OK
    submit_job("dev.example.com", "rk-abc123", ["do stuff"], working_dir="/opt/app")

    calls = mock_run.call_args_list
    # Pre-flight: tmux check
    assert "command -v tmux" in calls[0][0][0][4]
    # Pre-flight: working dir check
    assert "/opt/app" in calls[1][0][0][4]
    # Upload + launch = 4 calls total
    assert len(calls) == 4


@patch("ralphkit.remote.subprocess.run")
def test_submit_job_with_ralph_version(mock_run):
    mock_run.return_value = _OK
    submit_job("dev.example.com", "rk-abc123", ["do stuff"], ralph_version="0.5.0")

    calls = mock_run.call_args_list
    # The uploaded script should contain uvx --from ralphkit==0.5.0
    upload_call = calls[1]
    script_content = upload_call[1]["input"]
    assert "uvx --from ralphkit==0.5.0 ralph" in script_content


@patch("ralphkit.remote.subprocess.run")
def test_submit_job_no_tmux(mock_run):
    mock_run.return_value = subprocess.CompletedProcess(
        args=[], returncode=1, stdout="", stderr=""
    )
    with pytest.raises(SystemExit, match="tmux is not installed"):
        submit_job("dev.example.com", "rk-abc123", ["do stuff"])


@patch("ralphkit.remote.subprocess.run")
def test_submit_job_working_dir_missing(mock_run):
    mock_run.side_effect = [
        _OK,
        subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr=""),
    ]
    with pytest.raises(SystemExit, match="Working directory does not exist"):
        submit_job(
            "dev.example.com", "rk-abc123", ["do stuff"], working_dir="/bad/path"
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


def test_get_attach_command():
    cmd = get_attach_command("dev.example.com", "rk-abc123")
    assert cmd == [
        "ssh",
        "-t",
        "dev.example.com",
        "tmux",
        "attach",
        "-t",
        "rk-abc123",
    ]


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
