import subprocess
from unittest.mock import patch

import pytest

from ralphkit.runner import TIMEOUT_SECONDS, run_claude


def test_timeout_seconds_constant():
    assert TIMEOUT_SECONDS == 900


@patch("ralphkit.runner.subprocess.run")
def test_run_claude_calls_subprocess_with_correct_args(mock_run):
    run_claude("do stuff", "opus", "be helpful")
    mock_run.assert_called_once()
    args, kwargs = mock_run.call_args
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


@patch("ralphkit.runner.subprocess.run")
def test_run_claude_passes_subprocess_options(mock_run):
    run_claude("p", "m", "s")
    _, kwargs = mock_run.call_args
    assert kwargs["stdout"] is subprocess.PIPE
    assert kwargs["stderr"] is subprocess.DEVNULL
    assert kwargs["check"] is True
    assert kwargs["timeout"] == TIMEOUT_SECONDS


@patch("ralphkit.runner.subprocess.run")
def test_run_claude_env_includes_disable_auto_memory(mock_run):
    run_claude("p", "m", "s")
    env = mock_run.call_args[1]["env"]
    assert env["CLAUDE_CODE_DISABLE_AUTO_MEMORY"] == "1"


@patch("ralphkit.runner.subprocess.run")
def test_run_claude_env_inherits_os_environ(mock_run, monkeypatch):
    monkeypatch.setenv("RALPHKIT_TEST_VAR", "hello")
    run_claude("p", "m", "s")
    env = mock_run.call_args[1]["env"]
    assert env["RALPHKIT_TEST_VAR"] == "hello"


@patch("ralphkit.runner.subprocess.run")
def test_run_claude_env_overrides_existing_disable_auto_memory(mock_run, monkeypatch):
    monkeypatch.setenv("CLAUDE_CODE_DISABLE_AUTO_MEMORY", "0")
    run_claude("p", "m", "s")
    env = mock_run.call_args[1]["env"]
    assert env["CLAUDE_CODE_DISABLE_AUTO_MEMORY"] == "1"


@patch("ralphkit.runner.subprocess.run")
def test_run_claude_success_returns_parsed_json(mock_run):
    mock_run.return_value = subprocess.CompletedProcess(
        args=[], returncode=0, stdout=b'{"type":"result","num_turns":1}'
    )
    result = run_claude("p", "m", "s")
    assert result == {"type": "result", "num_turns": 1}


@patch("ralphkit.runner.subprocess.run")
def test_run_claude_returns_none_on_invalid_json(mock_run):
    mock_run.return_value = subprocess.CompletedProcess(
        args=[], returncode=0, stdout=b"not json"
    )
    assert run_claude("p", "m", "s") is None


@patch("ralphkit.runner.subprocess.run")
def test_run_claude_returns_none_on_empty_stdout(mock_run):
    mock_run.return_value = subprocess.CompletedProcess(
        args=[], returncode=0, stdout=b""
    )
    assert run_claude("p", "m", "s") is None


@patch("ralphkit.runner.subprocess.run", side_effect=FileNotFoundError)
def test_run_claude_raises_on_file_not_found(mock_run):
    with pytest.raises(RuntimeError, match="'claude' command not found"):
        run_claude("p", "m", "s")


@patch(
    "ralphkit.runner.subprocess.run",
    side_effect=subprocess.TimeoutExpired("claude", 900),
)
def test_run_claude_raises_on_timeout(mock_run):
    with pytest.raises(RuntimeError, match="timed out after 900s"):
        run_claude("p", "m", "s")


@pytest.mark.parametrize("code", [1, 42])
def test_run_claude_raises_on_called_process_error(code):
    with patch(
        "ralphkit.runner.subprocess.run",
        side_effect=subprocess.CalledProcessError(code, "claude"),
    ):
        with pytest.raises(RuntimeError, match=f"exited with code {code}"):
            run_claude("p", "m", "s")


@patch("ralphkit.runner.subprocess.run", side_effect=PermissionError("nope"))
def test_run_claude_does_not_catch_unexpected_exceptions(mock_run):
    with pytest.raises(PermissionError):
        run_claude("p", "m", "s")
