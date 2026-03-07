import subprocess
from unittest.mock import patch

import pytest

from ralphkit.local import submit_local, list_local_jobs, cancel_local, tail_local_logs


@patch("ralphkit.local.subprocess.run")
def test_submit_local_calls_tmux_commands(mock_run, tmp_path):
    mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0)
    job_id = "rk-test-0307-120000-abcd"
    with patch("ralphkit.local.script_path_local", return_value=tmp_path / f"{job_id}.sh"):
        submit_local(job_id, ["pipe.yml"])

    # _check_tmux + tmux new-session + tmux set-option = 3 calls
    assert mock_run.call_count == 3
    # First call is _check_tmux (which tmux)
    assert mock_run.call_args_list[0][0][0] == ["which", "tmux"]
    # Second call is tmux new-session
    new_session_args = mock_run.call_args_list[1][0][0]
    assert new_session_args[:4] == ["tmux", "new-session", "-d", "-s"]
    assert new_session_args[4] == job_id
    # Third call is tmux set-option
    set_option_args = mock_run.call_args_list[2][0][0]
    assert set_option_args == ["tmux", "set-option", "-t", job_id, "remain-on-exit", "on"]


@patch("ralphkit.local.subprocess.run")
def test_submit_local_script_file_is_executable(mock_run, tmp_path):
    mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0)
    job_id = "rk-test-0307-120000-abcd"
    script_file = tmp_path / f"{job_id}.sh"
    with patch("ralphkit.local.script_path_local", return_value=script_file):
        submit_local(job_id, ["pipe.yml"])

    assert script_file.exists()
    # Check executable bit (0o755 means owner execute bit is set)
    assert script_file.stat().st_mode & 0o100


@patch("ralphkit.local.subprocess.run")
def test_list_local_jobs_returns_empty_on_tmux_error(mock_run):
    mock_run.return_value = subprocess.CompletedProcess(
        args=[], returncode=1, stdout="", stderr="no server running"
    )
    result = list_local_jobs()
    assert result == []


@patch("ralphkit.local.subprocess.run")
def test_list_local_jobs_parses_tmux_output(mock_run):
    mock_run.return_value = subprocess.CompletedProcess(
        args=[],
        returncode=0,
        stdout="rk-deploy-0307-1200-ab12\t1709812800\t1709812900\t0\n",
    )
    result = list_local_jobs()
    assert len(result) == 1
    assert result[0]["name"] == "rk-deploy-0307-1200-ab12"


@patch("ralphkit.local.subprocess.run")
def test_cancel_local_raises_on_missing_job(mock_run):
    mock_run.return_value = subprocess.CompletedProcess(
        args=[], returncode=1, stdout="", stderr="session not found"
    )
    with pytest.raises(SystemExit, match="No job 'rk-nonexistent' found"):
        cancel_local("rk-nonexistent")


def test_tail_local_logs_raises_when_log_missing(tmp_path):
    with patch("ralphkit.local.log_path_local", return_value=tmp_path / "nope.log"):
        with pytest.raises(SystemExit, match="No log file"):
            tail_local_logs("rk-nonexistent")
