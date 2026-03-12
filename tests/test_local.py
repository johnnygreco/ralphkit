import subprocess
import json
from unittest.mock import patch

import pytest

from ralphkit.local import submit_local, list_local_jobs, cancel_local, tail_local_logs


@patch("ralphkit.local.shutil.which", return_value="/usr/bin/tmux")
@patch("ralphkit.local.subprocess.run")
def test_submit_local_calls_tmux_commands(mock_run, mock_which, tmp_path):
    mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0)
    job_id = "rk-test-0307-120000-abcd"
    with patch(
        "ralphkit.local.script_path_local", return_value=tmp_path / f"{job_id}.sh"
    ):
        submit_local(job_id, ["pipe.yml"], subcommand="pipe")

    # Single tmux call (atomic new-session + set-option)
    assert mock_run.call_count == 1
    tmux_args = mock_run.call_args_list[0][0][0]
    assert tmux_args[:4] == ["tmux", "new-session", "-d", "-s"]
    assert tmux_args[4] == job_id
    # Verify atomic: set-option chained via ";"
    assert ";" in tmux_args
    assert "remain-on-exit" in tmux_args


@patch("ralphkit.local.shutil.which", return_value=None)
def test_submit_local_no_tmux_raises(mock_which):
    with pytest.raises(SystemExit, match="tmux is required"):
        submit_local("rk-test-0307-120000-abcd", ["pipe.yml"], subcommand="pipe")


@patch("ralphkit.local.shutil.which", return_value="/usr/bin/tmux")
@patch("ralphkit.local.subprocess.run")
def test_submit_local_script_file_is_executable(mock_run, mock_which, tmp_path):
    mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0)
    job_id = "rk-test-0307-120000-abcd"
    script_file = tmp_path / f"{job_id}.sh"
    meta_file = tmp_path / f"{job_id}.meta.json"
    job_dir = tmp_path / job_id
    with patch("ralphkit.local.script_path_local", return_value=script_file), patch(
        "ralphkit.local.meta_path_local", return_value=meta_file
    ), patch("ralphkit.local.job_path_local", return_value=job_dir):
        submit_local(job_id, ["pipe.yml"], subcommand="pipe")

    assert script_file.exists()
    # Check permissions are 0o700 (owner-only)
    assert script_file.stat().st_mode & 0o777 == 0o700
    assert job_dir.exists()
    meta = json.loads(meta_file.read_text())
    assert meta["job_id"] == job_id
    assert meta["subcommand"] == "pipe"
    assert meta["isolation"] == "shared"
    assert meta["scratch_dir"] == str(job_dir)
    assert "submitted_at" in meta


@patch("ralphkit.local.shutil.which", return_value="/usr/bin/tmux")
@patch("ralphkit.local.subprocess.run")
def test_submit_local_uses_subcommand_in_script(mock_run, mock_which, tmp_path):
    mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0)
    job_id = "rk-test-0307-120000-abcd"
    script_file = tmp_path / f"{job_id}.sh"
    meta_file = tmp_path / f"{job_id}.meta.json"
    job_dir = tmp_path / job_id
    with patch("ralphkit.local.script_path_local", return_value=script_file), patch(
        "ralphkit.local.meta_path_local", return_value=meta_file
    ), patch("ralphkit.local.job_path_local", return_value=job_dir):
        submit_local(
            job_id,
            [
                "task.md",
                "--force",
                "--timeout-seconds",
                "900",
                "--idle-timeout-seconds",
                "60",
                "--cleanup-on-error",
                "skip",
                "--resume-run",
                "7",
            ],
            subcommand="build",
        )

    script_content = script_file.read_text()
    assert "ralphkit build task.md --force" in script_content
    assert "ralphkit run" not in script_content
    meta = json.loads(meta_file.read_text())
    assert meta["timeout_seconds"] == 900
    assert meta["idle_timeout_seconds"] == 60
    assert meta["cleanup_on_error"] == "skip"
    assert meta["resume_run"] == "7"


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
