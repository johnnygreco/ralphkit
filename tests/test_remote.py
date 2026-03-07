import subprocess
from unittest.mock import patch

import pytest

from ralphkit.hosts import HostConfig
from ralphkit.remote import (
    _ssh_target,
    _ssh_run,
    submit_job,
    list_jobs,
    cancel_job,
    get_attach_command,
    tail_logs,
)


def _host(user="deploy", working_dir="/opt/app"):
    return HostConfig(
        name="dev",
        hostname="dev.example.com",
        user=user,
        working_dir=working_dir,
    )


_OK = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")


def test_ssh_target_with_user():
    assert _ssh_target(_host()) == "deploy@dev.example.com"


def test_ssh_target_without_user():
    assert _ssh_target(_host(user=None)) == "dev.example.com"


@patch("ralphkit.remote.subprocess.run")
def test_submit_job_full_flow(mock_run):
    mock_run.return_value = _OK
    host = _host()
    submit_job(host, "rk-abc123", ["--model", "opus", "do stuff"])

    calls = mock_run.call_args_list
    # SSH args are ["ssh", "-o", "ConnectTimeout=10", target, cmd] so cmd is at index 4
    # Pre-flight: tmux check
    assert "command -v tmux" in calls[0][0][0][4]
    # Pre-flight: working dir check
    assert "test -d" in calls[1][0][0][4]
    # Upload script
    assert "mkdir -p" in calls[2][0][0][4]
    # Launch tmux (atomic: new-session + set-option in one call)
    assert "tmux new-session" in calls[3][0][0][4]
    assert "remain-on-exit" in calls[3][0][0][4]
    # Should be 4 calls total (was 5 before atomic tmux)
    assert len(calls) == 4


@patch("ralphkit.remote.subprocess.run")
def test_submit_job_with_working_dir_override(mock_run):
    mock_run.return_value = _OK
    host = _host(working_dir="/opt/app")
    submit_job(host, "rk-abc123", ["do stuff"], working_dir="/override/path")

    calls = mock_run.call_args_list
    # Working dir check should use the override, not host config
    assert "/override/path" in calls[1][0][0][4]


@patch("ralphkit.remote.subprocess.run")
def test_submit_job_no_working_dir(mock_run):
    mock_run.return_value = _OK
    host = _host(working_dir=None)
    submit_job(host, "rk-abc123", ["do stuff"])

    calls = mock_run.call_args_list
    # Should skip working dir check: tmux check, upload, launch = 3 calls
    assert len(calls) == 3


@patch("ralphkit.remote.subprocess.run")
def test_submit_job_no_tmux(mock_run):
    mock_run.return_value = subprocess.CompletedProcess(
        args=[], returncode=1, stdout="", stderr=""
    )
    with pytest.raises(SystemExit, match="tmux is not installed"):
        submit_job(_host(), "rk-abc123", ["do stuff"])


@patch("ralphkit.remote.subprocess.run")
def test_submit_job_working_dir_missing(mock_run):
    mock_run.side_effect = [
        _OK,
        subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr=""),
    ]
    with pytest.raises(SystemExit, match="Working directory does not exist"):
        submit_job(_host(), "rk-abc123", ["do stuff"])


@patch("ralphkit.remote.subprocess.run")
def test_list_jobs_parses_output(mock_run):
    mock_run.return_value = subprocess.CompletedProcess(
        args=[],
        returncode=0,
        stdout="rk-abc123\t1234567890\t1234567891\t0\nrk-def456\t1234567892\t1234567893\t1\n",
        stderr="",
    )
    jobs = list_jobs(_host())
    assert len(jobs) == 2
    assert jobs[0]["name"] == "rk-abc123"
    assert jobs[1]["name"] == "rk-def456"


@patch("ralphkit.remote.subprocess.run")
def test_list_jobs_returns_empty_on_failure(mock_run):
    mock_run.return_value = subprocess.CompletedProcess(
        args=[], returncode=1, stdout="", stderr=""
    )
    assert list_jobs(_host()) == []


@patch("ralphkit.remote.subprocess.run")
def test_cancel_job_success(mock_run):
    mock_run.return_value = _OK
    cancel_job(_host(), "rk-abc123")  # should not raise


@patch("ralphkit.remote.subprocess.run")
def test_cancel_job_missing_raises_system_exit(mock_run):
    mock_run.return_value = subprocess.CompletedProcess(
        args=[], returncode=1, stdout="", stderr=""
    )
    with pytest.raises(SystemExit, match="No job 'rk-missing'"):
        cancel_job(_host(), "rk-missing")


def test_get_attach_command():
    cmd = get_attach_command(_host(), "rk-abc123")
    assert cmd == [
        "ssh",
        "-t",
        "deploy@dev.example.com",
        "tmux",
        "attach",
        "-t",
        "rk-abc123",
    ]


@patch("ralphkit.remote.subprocess.run")
def test_tail_logs_calls_ssh_with_correct_args(mock_run):
    mock_run.return_value = _OK
    tail_logs(_host(), "rk-abc123")

    args = mock_run.call_args[0][0]
    assert "ssh" in args
    assert "-t" in args
    # Should use double quotes (not single) so $HOME expands
    cmd_str = args[-1]
    assert "tail" in cmd_str
    assert '"$HOME/' in cmd_str


@patch("ralphkit.remote.subprocess.run")
def test_tail_logs_follow_flag(mock_run):
    mock_run.return_value = _OK
    tail_logs(_host(), "rk-abc123", follow=True)

    cmd_str = mock_run.call_args[0][0][-1]
    assert "tail -f" in cmd_str


@patch("ralphkit.remote.subprocess.run")
def test_ssh_run_connection_refused(mock_run):
    mock_run.side_effect = subprocess.CalledProcessError(
        255, "ssh", stderr="Connection refused"
    )
    with pytest.raises(SystemExit, match="SSH connection to 'dev.example.com' failed"):
        _ssh_run(_host(), "echo hello")


@patch("ralphkit.remote.subprocess.run")
def test_ssh_run_auth_failure(mock_run):
    mock_run.side_effect = subprocess.CalledProcessError(
        255, "ssh", stderr="Permission denied (publickey)"
    )
    with pytest.raises(SystemExit, match="Permission denied"):
        _ssh_run(_host(), "echo hello")


@patch("ralphkit.remote.subprocess.run")
def test_ssh_run_includes_connect_timeout(mock_run):
    mock_run.return_value = _OK
    _ssh_run(_host(), "echo hello", check=False)
    args = mock_run.call_args[0][0]
    assert "-o" in args
    assert "ConnectTimeout=10" in args
