import subprocess
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

import ralphkit.runner as runner
from ralphkit.runner import ClaudeRunError, run_claude


def _proc(*, returncode=0, stdout='{"ok": true}', stderr="") -> Mock:
    proc = Mock()
    proc.communicate.return_value = (stdout, stderr)
    proc.returncode = returncode
    proc.poll.return_value = returncode
    return proc


@patch.object(runner, "_latest_transcript", return_value=("/tmp/transcript.jsonl", 1.0))
@patch.object(runner.subprocess, "Popen")
def test_run_claude_success_invokes_popen_with_expected_options(
    mock_popen, mock_latest, monkeypatch
):
    monkeypatch.setenv("RALPHKIT_TEST_VAR", "hello")
    monkeypatch.setenv("CLAUDE_CODE_DISABLE_AUTO_MEMORY", "0")
    proc = _proc(stdout='{"type":"result","num_turns":1}')
    mock_popen.return_value = proc

    result = run_claude(
        "do stuff",
        "opus",
        "be helpful",
        cwd=Path("/tmp/worktree"),
    )

    assert result == {
        "type": "result",
        "num_turns": 1,
        "_ralphkit_transcript_path": "/tmp/transcript.jsonl",
    }
    mock_popen.assert_called_once()
    args, kwargs = mock_popen.call_args
    assert args[0] == [
        "claude",
        "-p",
        "do stuff",
        "--model",
        "opus",
        "--append-system-prompt",
        "be helpful",
        "--dangerously-skip-permissions",
        "--output-format",
        "json",
    ]
    assert kwargs["stdout"] is subprocess.PIPE
    assert kwargs["stderr"] is subprocess.PIPE
    assert kwargs["text"] is True
    assert kwargs["encoding"] == "utf-8"
    assert kwargs["errors"] == "replace"
    assert kwargs["cwd"] == "/tmp/worktree"
    assert kwargs["env"]["RALPHKIT_TEST_VAR"] == "hello"
    assert kwargs["env"]["CLAUDE_CODE_DISABLE_AUTO_MEMORY"] == "1"
    mock_latest.assert_called()


@patch.object(runner, "_latest_transcript", return_value=(None, None))
@patch.object(runner.subprocess, "Popen")
def test_run_claude_raises_invalid_json_error(mock_popen, mock_latest):
    mock_popen.return_value = _proc(stdout="not json")

    with pytest.raises(
        ClaudeRunError, match="did not emit valid JSON"
    ) as exc_info:
        run_claude("p", "m", "s")

    error = exc_info.value
    assert error.kind == "invalid_json_output"
    assert error.stdout_tail == "not json"
    mock_latest.assert_called_once()


@patch.object(runner.subprocess, "Popen", side_effect=FileNotFoundError)
def test_run_claude_raises_not_found_error(mock_popen):
    with pytest.raises(ClaudeRunError, match="'claude' command not found") as exc_info:
        run_claude("p", "m", "s")
    error = exc_info.value
    assert error.kind == "not_found"
    assert error.elapsed_s == 0.0


@patch.object(runner, "_latest_transcript", return_value=("/tmp/session.jsonl", 5.0))
@patch.object(runner.subprocess, "Popen")
def test_run_claude_raises_process_error_with_diagnostics(mock_popen, mock_latest):
    mock_popen.return_value = _proc(
        returncode=42,
        stdout="partial stdout",
        stderr="partial stderr",
    )

    with pytest.raises(ClaudeRunError, match="exited with code 42") as exc_info:
        run_claude("p", "m", "s")

    error = exc_info.value
    assert error.kind == "process_error"
    assert error.returncode == 42
    assert error.stdout_tail == "partial stdout"
    assert error.stderr_tail == "partial stderr"
    assert error.transcript_path == "/tmp/session.jsonl"
    assert error.to_dict()["kind"] == "process_error"
    mock_latest.assert_called_once()


@patch.object(runner, "_stop_process")
@patch.object(runner, "_latest_transcript", return_value=(None, None))
@patch.object(runner.time, "monotonic", side_effect=[0.0, 2.5])
@patch.object(runner.subprocess, "Popen")
def test_run_claude_raises_hard_timeout(
    mock_popen, mock_monotonic, mock_latest, mock_stop
):
    proc = Mock()
    proc.communicate.side_effect = subprocess.TimeoutExpired(
        "claude",
        runner.POLL_SECONDS,
        output="partial stdout",
        stderr="partial stderr",
    )
    proc.poll.return_value = None
    mock_popen.return_value = proc

    with pytest.raises(ClaudeRunError, match="timed out after 2s") as exc_info:
        run_claude("p", "m", "s", timeout_seconds=2)

    error = exc_info.value
    assert error.kind == "hard_timeout"
    assert error.timeout_seconds == 2
    assert error.stdout_tail == "partial stdout"
    assert error.stderr_tail == "partial stderr"
    mock_stop.assert_called_once_with(proc)


@patch.object(runner, "_stop_process")
@patch.object(runner, "_latest_transcript", return_value=(None, None))
@patch.object(runner.time, "monotonic", side_effect=[0.0, 3.0])
@patch.object(runner.subprocess, "Popen")
def test_run_claude_raises_idle_timeout(
    mock_popen, mock_monotonic, mock_latest, mock_stop
):
    proc = Mock()
    proc.communicate.side_effect = subprocess.TimeoutExpired(
        "claude",
        runner.POLL_SECONDS,
        output="",
        stderr="",
    )
    proc.poll.return_value = None
    mock_popen.return_value = proc

    with pytest.raises(ClaudeRunError, match="idle timeout after 2s") as exc_info:
        run_claude("p", "m", "s", timeout_seconds=100, idle_timeout_seconds=2)

    error = exc_info.value
    assert error.kind == "idle_timeout"
    assert error.idle_timeout_seconds == 2
    mock_stop.assert_called_once_with(proc)


@patch.object(runner.subprocess, "Popen", side_effect=PermissionError("nope"))
def test_run_claude_does_not_catch_unexpected_exceptions(mock_popen):
    with pytest.raises(PermissionError, match="nope"):
        run_claude("p", "m", "s")
