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
)


def _host(user="deploy", working_dir="/opt/app"):
    return HostConfig(
        name="dev",
        hostname="dev.example.com",
        user=user,
        working_dir=working_dir,
    )


def test_ssh_target_with_user():
    assert _ssh_target(_host()) == "deploy@dev.example.com"


def test_ssh_target_without_user():
    assert _ssh_target(_host(user=None)) == "dev.example.com"


@patch("ralphkit.remote.subprocess.run")
def test_submit_job_full_flow(mock_run):
    mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
    host = _host()
    submit_job(host, "rk-abc123", ["--model", "opus", "do stuff"])

    calls = mock_run.call_args_list
    # Pre-flight: tmux check
    assert calls[0][0][0] == ["ssh", "deploy@dev.example.com", "command -v tmux"]
    # Pre-flight: working dir check
    assert calls[1][0][0] == ["ssh", "deploy@dev.example.com", "test -d /opt/app"]
    # Upload script
    assert "mkdir -p" in calls[2][0][0][2]
    assert "cat >" in calls[2][0][0][2]
    # Launch tmux
    assert "tmux new-session" in calls[3][0][0][2]
    # Set remain-on-exit
    assert "tmux set-option" in calls[4][0][0][2]


@patch("ralphkit.remote.subprocess.run")
def test_submit_job_no_tmux(mock_run):
    mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="")
    with pytest.raises(SystemExit, match="tmux is not installed"):
        submit_job(_host(), "rk-abc123", ["do stuff"])


@patch("ralphkit.remote.subprocess.run")
def test_submit_job_working_dir_missing(mock_run):
    # First call (tmux check) succeeds, second call (workdir check) fails
    mock_run.side_effect = [
        subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr=""),
        subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr=""),
    ]
    with pytest.raises(SystemExit, match="Working directory does not exist"):
        submit_job(_host(), "rk-abc123", ["do stuff"])


@patch("ralphkit.remote.subprocess.run")
def test_list_jobs_parses_output(mock_run):
    mock_run.return_value = subprocess.CompletedProcess(
        args=[], returncode=0,
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
def test_cancel_job_missing_raises_system_exit(mock_run):
    mock_run.return_value = subprocess.CompletedProcess(
        args=[], returncode=1, stdout="", stderr=""
    )
    with pytest.raises(SystemExit, match="No job 'rk-missing'"):
        cancel_job(_host(), "rk-missing")


def test_get_attach_command():
    cmd = get_attach_command(_host(), "rk-abc123")
    assert cmd == ["ssh", "-t", "deploy@dev.example.com", "tmux", "attach", "-t", "rk-abc123"]


@patch("ralphkit.remote.subprocess.run")
def test_ssh_run_connection_refused(mock_run):
    mock_run.side_effect = subprocess.CalledProcessError(
        255, "ssh", stderr="Connection refused"
    )
    with pytest.raises(SystemExit, match="SSH connection to 'dev.example.com' failed"):
        _ssh_run(_host(), "echo hello")
