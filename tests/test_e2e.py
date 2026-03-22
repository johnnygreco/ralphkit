"""End-to-end integration tests for the ralphkit CLI.

These tests invoke the real CLI through subprocess, using a fake ``claude``
binary that returns canned JSON responses.  Everything else runs for real:
CLI parsing, Typer dispatch, engine orchestration, state management, config
loading, prompt rendering, and report generation.

Each test gets its own temp directory for state so tests are fully isolated.

**Not covered (requires real infrastructure):**

- ``--host local`` / ``--host <remote>`` (tmux/SSH job submission)
- ``jobs``, ``logs``, ``cancel`` commands (require tmux sessions)
- Handoff files, progress.md, RALPH-BLOCKED.md (written by claude, not engine)
"""

import json
import os
import stat
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

# Resolve the ralphkit binary from the same venv as the test runner.
_VENV_BIN = str(Path(sys.executable).parent)
_RALPHKIT = str(Path(_VENV_BIN) / "ralphkit")

# ---------------------------------------------------------------------------
# Fixtures & helpers
# ---------------------------------------------------------------------------

_FAKE_CLAUDE = textwrap.dedent("""\
    #!/usr/bin/env python3
    import json
    print(json.dumps({
        "result": "fake response",
        "cost_usd": 0.001,
        "duration_ms": 100,
        "duration_api_ms": 50,
        "num_turns": 1,
        "session_id": "fake-session",
        "is_error": False,
    }))
""")


@pytest.fixture(scope="session")
def fake_claude_dir(tmp_path_factory):
    """Create a directory containing a fake ``claude`` binary (once per session)."""
    bin_dir = tmp_path_factory.mktemp("bin")
    claude_bin = bin_dir / "claude"
    claude_bin.write_text(_FAKE_CLAUDE)
    claude_bin.chmod(claude_bin.stat().st_mode | stat.S_IEXEC)
    return bin_dir


@pytest.fixture(scope="session")
def env(fake_claude_dir):
    """Environment with the fake ``claude`` at the front of PATH and venv bin."""
    e = os.environ.copy()
    e["PATH"] = str(fake_claude_dir) + ":" + _VENV_BIN + ":" + e.get("PATH", "")
    e.pop("FORCE_COLOR", None)
    return e


def _rk(args: list[str], env: dict, **kwargs):
    """Run ``ralphkit`` as a subprocess and return the CompletedProcess."""
    return subprocess.run(
        [_RALPHKIT] + args,
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
        **kwargs,
    )


def _read_report(state_dir: Path) -> dict:
    """Read report.json from the first (or only) run in a state directory."""
    run_dir = next((state_dir / "runs").iterdir())
    return json.loads((run_dir / "report.json").read_text())


_SIMPLE_PIPE_YAML = textwrap.dedent("""\
    pipe:
      - step_name: step1
        task_prompt: "Do work on {state_dir}/task.md"
        system_prompt: "You are helpful."
""")


def _write_pipe_config(tmp_path: Path) -> Path:
    """Write a simple single-step pipe config and return its path."""
    cfg = tmp_path / "pipe.yaml"
    cfg.write_text(_SIMPLE_PIPE_YAML)
    return cfg


# ---------------------------------------------------------------------------
# Basic CLI surface
# ---------------------------------------------------------------------------


class TestCLISurface:
    def test_help(self, env):
        r = _rk(["--help"], env)
        assert r.returncode == 0
        for cmd in ("build", "pipe", "loop"):
            assert cmd in r.stdout

    def test_version(self, env):
        r = _rk(["--version"], env)
        assert r.returncode == 0
        assert "ralphkit" in r.stdout

    def test_no_args_shows_help(self, env):
        r = _rk([], env)
        assert "Usage" in r.stdout
        assert "build" in r.stdout

    def test_unknown_command(self, env):
        r = _rk(["nonexistent"], env)
        assert r.returncode != 0


# ---------------------------------------------------------------------------
# Migration shims (removed commands)
# ---------------------------------------------------------------------------


class TestMigrationShims:
    def test_run_shows_removal_message(self, env):
        r = _rk(["run", "anything"], env)
        assert r.returncode != 0
        combined = (r.stdout + r.stderr).lower()
        assert "removed" in combined
        assert "build" in combined

    def test_submit_shows_removal_message(self, env):
        r = _rk(["submit", "anything"], env)
        assert r.returncode != 0
        combined = (r.stdout + r.stderr).lower()
        assert "removed" in combined
        assert "--host" in combined


# ---------------------------------------------------------------------------
# Pipe workflows (foreground)
# ---------------------------------------------------------------------------


# (Pipe workflow tests removed — fix, research, plan, big-swing commands dropped)


# ---------------------------------------------------------------------------
# Custom pipe via YAML config
# ---------------------------------------------------------------------------


class TestCustomPipe:
    def test_pipe_with_config(self, env, tmp_path):
        state_dir = tmp_path / "state"
        config = tmp_path / "pipe.yaml"
        config.write_text(
            textwrap.dedent("""\
            pipe:
              - step_name: greet
                task_prompt: "Say hello"
                system_prompt: "You are a greeter."
              - step_name: farewell
                task_prompt: "Say goodbye"
                system_prompt: "You are polite."
        """)
        )
        r = _rk(
            [
                "pipe",
                "test task",
                "-c",
                str(config),
                "-f",
                "--state-dir",
                str(state_dir),
            ],
            env,
        )
        assert r.returncode == 0

        report = _read_report(state_dir)
        assert report["outcome"] == "PIPE_COMPLETE"
        assert [s["step_name"] for s in report["steps"]] == ["greet", "farewell"]

    def test_pipe_requires_config(self, env):
        r = _rk(["pipe", "task", "-f"], env)
        assert r.returncode != 0

    def test_loop_requires_config(self, env):
        r = _rk(["loop", "task", "-f"], env)
        assert r.returncode != 0


# ---------------------------------------------------------------------------
# Custom loop via YAML config
# ---------------------------------------------------------------------------


class TestCustomLoop:
    def test_loop_with_config_and_plan(self, env, tmp_path):
        """loop command with YAML config + pre-made plan runs the full lifecycle."""
        state_dir = tmp_path / "state"
        config = tmp_path / "loop.yaml"
        config.write_text(
            textwrap.dedent("""\
            loop:
              - step_name: my_worker
                task_prompt: "Do the work"
                system_prompt: "You are a worker."
            cleanup:
              - step_name: my_reviewer
                task_prompt: "Review the work"
                system_prompt: "You are a reviewer."
        """)
        )
        plan = tmp_path / "tickets.json"
        plan.write_text(
            json.dumps({"items": [{"id": 1, "title": "only item", "done": True}]})
        )
        r = _rk(
            [
                "loop",
                "task",
                "-c",
                str(config),
                "--plan",
                str(plan),
                "--max-iterations",
                "1",
                "-f",
                "--state-dir",
                str(state_dir),
            ],
            env,
        )
        assert r.returncode == 0

        report = _read_report(state_dir)
        assert report["outcome"] == "COMPLETE"

        # Custom step names from YAML config were used
        step_names = [s["step_name"] for s in report["steps"]]
        assert "my_worker" in step_names
        assert "my_reviewer" in step_names

        # Worker ran in loop phase, reviewer ran in cleanup phase
        phases = {s["step_name"]: s["phase"] for s in report["steps"]}
        assert phases["my_worker"] == "loop"
        assert phases["my_reviewer"] == "cleanup"

        # Both steps called fake claude
        for s in report["steps"]:
            assert s["session_id"] == "fake-session"


# ---------------------------------------------------------------------------
# Build (loop) workflow
# ---------------------------------------------------------------------------


class TestBuildLoop:
    def test_completed_plan(self, env, tmp_path):
        """Build with all items done: runs worker + cleanup, then exits COMPLETE.

        Even with all items done, the engine runs 1 full iteration (calling
        fake claude for the worker step), checks all_done, then runs cleanup.
        """
        state_dir = tmp_path / "state"
        plan = tmp_path / "tickets.json"
        plan.write_text(
            json.dumps(
                {
                    "items": [
                        {"id": 1, "title": "item one", "done": True},
                        {"id": 2, "title": "item two", "done": True},
                    ]
                }
            )
        )
        r = _rk(
            [
                "build",
                "test feature",
                "-f",
                "--state-dir",
                str(state_dir),
                "--plan",
                str(plan),
                "--max-iterations",
                "1",
            ],
            env,
        )
        assert r.returncode == 0

        run_dir = next((state_dir / "runs").iterdir())

        # Plan items tracked correctly
        report = json.loads((run_dir / "report.json").read_text())
        assert report["outcome"] == "COMPLETE"
        assert report["items_completed"] == 2
        assert report["items_total"] == 2
        assert report["iterations_completed"] == 1

        # Worker ran (loop phase) and cleanup ran (cleanup phase)
        phases = [s["phase"] for s in report["steps"]]
        assert "loop" in phases
        assert "cleanup" in phases

        # All steps actually called fake claude
        for s in report["steps"]:
            assert s["session_id"] == "fake-session"

        # State files written
        assert (run_dir / "iteration.txt").read_text() == "1"
        assert (run_dir / "tickets.json").is_file()
        assert (run_dir / "task.md").is_file()

    def test_max_iterations_reached(self, env, tmp_path):
        """Incomplete plan hits max iterations: worker runs, cleanup runs, exit 1."""
        state_dir = tmp_path / "state"
        plan = tmp_path / "tickets.json"
        plan.write_text(
            json.dumps({"items": [{"id": 1, "title": "never done", "done": False}]})
        )
        r = _rk(
            [
                "build",
                "test feature",
                "-f",
                "--state-dir",
                str(state_dir),
                "--plan",
                str(plan),
                "--max-iterations",
                "1",
            ],
            env,
        )
        assert r.returncode == 1
        assert "Max iterations" in r.stdout

        report = _read_report(state_dir)
        assert report["outcome"] == "MAX_ITERATIONS"
        assert report["items_completed"] == 0
        assert report["items_total"] == 1

        # Worker and cleanup both ran
        phases = [s["phase"] for s in report["steps"]]
        assert "loop" in phases
        assert "cleanup" in phases
        for s in report["steps"]:
            assert s["session_id"] == "fake-session"

    def test_plan_only(self, env, tmp_path):
        """--plan-only copies plan to state dir and exits without running loop."""
        state_dir = tmp_path / "state"
        plan = tmp_path / "tickets.json"
        plan.write_text(
            json.dumps({"items": [{"id": 1, "title": "only item", "done": False}]})
        )
        r = _rk(
            [
                "build",
                "test feature",
                "-f",
                "--state-dir",
                str(state_dir),
                "--plan",
                str(plan),
                "--plan-only",
            ],
            env,
        )
        assert r.returncode == 0

        run_dir = next((state_dir / "runs").iterdir())
        saved_plan = json.loads((run_dir / "tickets.json").read_text())
        assert len(saved_plan["items"]) == 1

        report = json.loads((run_dir / "report.json").read_text())
        assert report["outcome"] == "PLAN_ONLY"
        assert report["steps"] == []

    def test_planning_fails_gracefully(self, env, tmp_path):
        """Without --plan, planner runs but fake claude can't write tickets.json."""
        state_dir = tmp_path / "state"
        r = _rk(
            ["build", "test feature", "-f", "--state-dir", str(state_dir)],
            env,
        )
        assert r.returncode == 1
        combined = r.stdout + r.stderr
        assert "Planning failed" in combined or "tickets.json" in combined

    def test_invalid_plan_rejected(self, env, tmp_path):
        """Plan with empty items list is rejected."""
        state_dir = tmp_path / "state"
        plan = tmp_path / "tickets.json"
        plan.write_text(json.dumps({"items": []}))
        r = _rk(
            [
                "build",
                "task",
                "-f",
                "--state-dir",
                str(state_dir),
                "--plan",
                str(plan),
            ],
            env,
        )
        assert r.returncode != 0

    def test_plan_missing_fields_rejected(self, env, tmp_path):
        """Plan items missing required fields (id, title, done) are rejected."""
        state_dir = tmp_path / "state"
        plan = tmp_path / "tickets.json"
        plan.write_text(json.dumps({"items": [{"id": 1}]}))  # missing title, done
        r = _rk(
            [
                "build",
                "task",
                "-f",
                "--state-dir",
                str(state_dir),
                "--plan",
                str(plan),
            ],
            env,
        )
        assert r.returncode != 0


# ---------------------------------------------------------------------------
# Task resolution (.md files)
# ---------------------------------------------------------------------------


class TestTaskResolution:
    def test_reads_md_file(self, env, tmp_path):
        state_dir = tmp_path / "state"
        cfg = _write_pipe_config(tmp_path)
        task_file = tmp_path / "bug.md"
        task_file.write_text("# Bug Report\nThe widget is broken.")
        r = _rk(
            [
                "pipe",
                str(task_file),
                "-c",
                str(cfg),
                "-f",
                "--state-dir",
                str(state_dir),
            ],
            env,
        )
        assert r.returncode == 0

        run_dir = next((state_dir / "runs").iterdir())
        content = (run_dir / "task.md").read_text()
        assert "Bug Report" in content
        assert "widget is broken" in content

    def test_missing_md_used_as_literal(self, env, tmp_path):
        """A .md path that doesn't exist is used as a literal string."""
        state_dir = tmp_path / "state"
        cfg = _write_pipe_config(tmp_path)
        r = _rk(
            [
                "pipe",
                "nonexistent.md",
                "-c",
                str(cfg),
                "-f",
                "--state-dir",
                str(state_dir),
            ],
            env,
        )
        assert r.returncode == 0

        run_dir = next((state_dir / "runs").iterdir())
        assert (run_dir / "task.md").read_text() == "nonexistent.md"


# ---------------------------------------------------------------------------
# State management
# ---------------------------------------------------------------------------


class TestStateManagement:
    def test_sequential_runs_increment(self, env, tmp_path):
        """Each run creates a new numbered directory; symlink tracks latest."""
        state_dir = tmp_path / "state"
        cfg = _write_pipe_config(tmp_path)
        _rk(["pipe", "first", "-c", str(cfg), "-f", "--state-dir", str(state_dir)], env)
        _rk(
            ["pipe", "second", "-c", str(cfg), "-f", "--state-dir", str(state_dir)], env
        )

        runs = sorted((state_dir / "runs").iterdir())
        assert len(runs) == 2
        assert runs[0].name == "001"
        assert runs[1].name == "002"

        current = state_dir / "current"
        assert current.is_symlink()
        assert current.resolve() == runs[1].resolve()

    def test_report_records_step_metadata(self, env, tmp_path):
        """Report captures model, phase, timing, and session_id for each step."""
        state_dir = tmp_path / "state"
        cfg = _write_pipe_config(tmp_path)
        _rk(
            ["pipe", "bug", "-c", str(cfg), "-f", "--state-dir", str(state_dir)],
            env,
        )

        report = _read_report(state_dir)
        assert len(report["steps"]) == 1
        for step in report["steps"]:
            assert step["phase"] == "pipe"
            assert step["model"] is not None
            assert step["duration_s"] >= 0
            assert step["num_turns"] == 1
            assert step["session_id"] == "fake-session"


# ---------------------------------------------------------------------------
# runs command
# ---------------------------------------------------------------------------


class TestRunsCommand:
    def test_empty(self, env, tmp_path):
        state_dir = tmp_path / "empty_state"
        state_dir.mkdir()
        r = _rk(["runs", "--state-dir", str(state_dir)], env)
        assert r.returncode == 0
        assert "No runs found" in r.stdout

    def test_lists_completed_runs(self, env, tmp_path):
        """After running a pipe, ``runs`` lists it with task preview."""
        state_dir = tmp_path / "state"
        cfg = _write_pipe_config(tmp_path)
        _rk(
            [
                "pipe",
                "find the bug",
                "-c",
                str(cfg),
                "-f",
                "--state-dir",
                str(state_dir),
            ],
            env,
        )
        r = _rk(["runs", "--state-dir", str(state_dir)], env)
        assert r.returncode == 0
        assert "001" in r.stdout
        assert "find the bug" in r.stdout

    def test_shows_plan_progress(self, env, tmp_path):
        """After a build run, ``runs`` shows plan item counts."""
        state_dir = tmp_path / "state"
        plan = tmp_path / "tickets.json"
        plan.write_text(
            json.dumps(
                {
                    "items": [
                        {"id": 1, "title": "a", "done": True},
                        {"id": 2, "title": "b", "done": True},
                    ]
                }
            )
        )
        _rk(
            [
                "build",
                "feature",
                "-f",
                "--state-dir",
                str(state_dir),
                "--plan",
                str(plan),
                "--max-iterations",
                "1",
            ],
            env,
        )
        r = _rk(["runs", "--state-dir", str(state_dir)], env)
        assert r.returncode == 0
        assert "2/2" in r.stdout


# ---------------------------------------------------------------------------
# Confirmation prompt
# ---------------------------------------------------------------------------


class TestConfirmation:
    def test_abort_on_no(self, env, tmp_path):
        """Without -f, answering 'n' aborts before running any steps."""
        state_dir = tmp_path / "state"
        cfg = _write_pipe_config(tmp_path)
        r = _rk(
            ["pipe", "task", "-c", str(cfg), "--state-dir", str(state_dir)],
            env,
            input="n\n",
        )
        assert r.returncode != 0

        # State dir is created (setup runs before prompt), but no report
        run_dir = next((state_dir / "runs").iterdir())
        assert not (run_dir / "report.json").is_file()

    def test_proceed_on_yes(self, env, tmp_path):
        """Without -f, answering 'y' runs the full workflow."""
        state_dir = tmp_path / "state"
        cfg = _write_pipe_config(tmp_path)
        r = _rk(
            ["pipe", "task", "-c", str(cfg), "--state-dir", str(state_dir)],
            env,
            input="y\n",
        )
        assert r.returncode == 0

        report = _read_report(state_dir)
        assert report["outcome"] == "PIPE_COMPLETE"


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


class TestValidation:
    def test_working_dir_without_host(self, env):
        r = _rk(["build", "bug", "-f", "--working-dir", "/tmp/x"], env)
        assert r.returncode != 0
        combined = r.stdout + r.stderr
        assert "--host" in combined

    def test_ralph_version_without_host(self, env):
        r = _rk(["build", "bug", "-f", "--ralph-version", "0.5.0"], env)
        assert r.returncode != 0
        combined = r.stdout + r.stderr
        assert "--host" in combined

    def test_build_missing_task(self, env):
        r = _rk(["build"], env)
        assert r.returncode != 0

    def test_build_missing_task_no_args(self, env):
        r = _rk(["build"], env)
        assert r.returncode != 0


# ---------------------------------------------------------------------------
# Option forwarding
# ---------------------------------------------------------------------------


class TestOptionForwarding:
    def test_default_model_override(self, env, tmp_path):
        """--default-model propagates through to every step in the report."""
        state_dir = tmp_path / "state"
        cfg = _write_pipe_config(tmp_path)
        r = _rk(
            [
                "pipe",
                "bug",
                "-c",
                str(cfg),
                "-f",
                "--state-dir",
                str(state_dir),
                "--default-model",
                "sonnet",
            ],
            env,
        )
        assert r.returncode == 0

        report = _read_report(state_dir)
        for step in report["steps"]:
            assert step["model"] == "sonnet"

    def test_max_iterations_override(self, env, tmp_path):
        """--max-iterations limits loop iterations."""
        state_dir = tmp_path / "state"
        plan = tmp_path / "tickets.json"
        plan.write_text(
            json.dumps({"items": [{"id": 1, "title": "task", "done": False}]})
        )
        r = _rk(
            [
                "build",
                "task",
                "-f",
                "--state-dir",
                str(state_dir),
                "--plan",
                str(plan),
                "--max-iterations",
                "2",
            ],
            env,
        )
        assert r.returncode == 1

        report = _read_report(state_dir)
        assert report["iterations_completed"] == 2

    def test_state_dir_override(self, env, tmp_path):
        """--state-dir directs all state to the specified directory."""
        custom_dir = tmp_path / "custom_state"
        cfg = _write_pipe_config(tmp_path)
        r = _rk(
            ["pipe", "bug", "-c", str(cfg), "-f", "--state-dir", str(custom_dir)],
            env,
        )
        assert r.returncode == 0
        assert (custom_dir / "runs" / "001" / "report.json").is_file()

    def test_per_step_model_in_config(self, env, tmp_path):
        """Per-step model override in YAML config is used instead of default."""
        state_dir = tmp_path / "state"
        config = tmp_path / "pipe.yaml"
        config.write_text(
            textwrap.dedent("""\
            pipe:
              - step_name: fast_step
                task_prompt: "Do something fast"
                system_prompt: "Be fast."
                model: haiku
              - step_name: smart_step
                task_prompt: "Do something smart"
                system_prompt: "Be smart."
        """)
        )
        r = _rk(
            [
                "pipe",
                "task",
                "-c",
                str(config),
                "-f",
                "--state-dir",
                str(state_dir),
                "--default-model",
                "sonnet",
            ],
            env,
        )
        assert r.returncode == 0

        report = _read_report(state_dir)
        models = {s["step_name"]: s["model"] for s in report["steps"]}
        assert models["fast_step"] == "haiku"  # per-step override
        assert models["smart_step"] == "sonnet"  # falls back to --default-model
