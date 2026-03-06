from ralphkit.state import StateDir


# ── Tests that use StateDir(tmp_path) without setup() ──────────────


def test_write_and_read_task(tmp_path):
    state = StateDir(tmp_path)
    state.write_task("do the thing")
    assert (tmp_path / "task.md").read_text() == "do the thing"


def test_write_and_read_iteration(tmp_path):
    state = StateDir(tmp_path)
    state.write_iteration(3)
    assert (tmp_path / "iteration.md").read_text() == "3"


def test_read_review_result_strips(tmp_path):
    state = StateDir(tmp_path)
    (tmp_path / "review-result.md").write_text("  SHIP\n")
    assert state.read_review_result() == "SHIP"


def test_read_missing_returns_none(tmp_path):
    state = StateDir(tmp_path)
    assert state.read_review_result() is None
    assert state.read_work_summary() is None
    assert state.read_review_feedback() is None
    assert state.is_blocked() is None


def test_clean_removes_state_files(tmp_path):
    state = StateDir(tmp_path)
    for name in [
        "review-result.md",
        "review-feedback.md",
        "work-summary.md",
        "work-complete.md",
        "RALPH-BLOCKED.md",
    ]:
        (tmp_path / name).write_text("x")
    state.clean()
    for name in [
        "review-result.md",
        "review-feedback.md",
        "work-summary.md",
        "work-complete.md",
        "RALPH-BLOCKED.md",
    ]:
        assert not (tmp_path / name).exists()


def test_clean_preserves_task_and_iteration(tmp_path):
    state = StateDir(tmp_path)
    (tmp_path / "task.md").write_text("task")
    (tmp_path / "iteration.md").write_text("1")
    state.clean()
    assert (tmp_path / "task.md").read_text() == "task"
    assert (tmp_path / "iteration.md").read_text() == "1"


def test_clean_for_next_iteration(tmp_path):
    state = StateDir(tmp_path)
    (tmp_path / "work-complete.md").write_text("done")
    (tmp_path / "review-result.md").write_text("REVISE")
    (tmp_path / "work-summary.md").write_text("summary")
    (tmp_path / "review-feedback.md").write_text("feedback")
    state.clean_for_next_iteration()
    # These should be removed
    assert not (tmp_path / "work-complete.md").exists()
    assert not (tmp_path / "review-result.md").exists()
    assert not (tmp_path / "work-summary.md").exists()
    # Feedback should be preserved for next worker iteration
    assert (tmp_path / "review-feedback.md").read_text() == "feedback"


def test_is_blocked(tmp_path):
    state = StateDir(tmp_path)
    assert state.is_blocked() is None
    (tmp_path / "RALPH-BLOCKED.md").write_text("blocked reason")
    assert state.is_blocked() == "blocked reason"


def test_clean_idempotent(tmp_path):
    state = StateDir(tmp_path)
    state.clean()  # no files exist, should not raise


def test_clean_for_next_iteration_idempotent(tmp_path):
    state = StateDir(tmp_path)
    state.clean_for_next_iteration()  # no files exist, should not raise


def test_read_work_summary_returns_content(tmp_path):
    state = StateDir(tmp_path)
    (tmp_path / "work-summary.md").write_text("  summary\n")
    assert state.read_work_summary() == "  summary\n"  # not stripped


def test_read_review_feedback_returns_content(tmp_path):
    state = StateDir(tmp_path)
    (tmp_path / "review-feedback.md").write_text("  feedback\n")
    assert state.read_review_feedback() == "  feedback\n"  # not stripped


def test_read_task_returns_content(tmp_path):
    state = StateDir(tmp_path)
    (tmp_path / "task.md").write_text("my task")
    assert state.read_task() == "my task"


def test_read_task_returns_none_when_missing(tmp_path):
    state = StateDir(tmp_path)
    assert state.read_task() is None


# ── Default path ───────────────────────────────────────────────────


def test_default_state_dir_path():
    state = StateDir()
    assert str(state.root) == ".ralphkit"
    assert str(state.path) == ".ralphkit"


# ── Run directory management (setup()) ─────────────────────────────


def test_setup_creates_runs_directory(tmp_path):
    state = StateDir(tmp_path / "state")
    state.setup()
    assert (state.root / "runs").is_dir()
    assert state.path.is_dir()
    assert state.path.name == "001"


def test_setup_creates_sequential_runs(tmp_path):
    root = tmp_path / "state"
    state1 = StateDir(root)
    state1.setup()
    assert state1.path.name == "001"

    state2 = StateDir(root)
    state2.setup()
    assert state2.path.name == "002"


def test_current_symlink_points_to_latest(tmp_path):
    root = tmp_path / "state"
    state = StateDir(root)
    state.setup()
    link = root / "current"
    assert link.is_symlink()
    assert link.resolve() == state.path.resolve()

    # Second run updates the symlink
    state2 = StateDir(root)
    state2.setup()
    assert link.resolve() == state2.path.resolve()


def test_active_path_returns_current_link(tmp_path):
    root = tmp_path / "state"
    state = StateDir(root)
    state.setup()
    assert state.active_path == root / "current"


def test_list_runs_returns_ordered(tmp_path):
    root = tmp_path / "state"
    state = StateDir(root)
    state.setup()  # 001
    StateDir(root).setup()  # 002
    StateDir(root).setup()  # 003

    runs = state.list_runs()
    assert [r.name for r in runs] == ["001", "002", "003"]


def test_list_runs_empty(tmp_path):
    state = StateDir(tmp_path / "state")
    assert state.list_runs() == []


def test_next_run_number_skips_nonnumeric(tmp_path):
    root = tmp_path / "state"
    runs_dir = root / "runs"
    runs_dir.mkdir(parents=True)
    (runs_dir / "notes").mkdir()
    (runs_dir / "001").mkdir()
    (runs_dir / "tmp").mkdir()

    state = StateDir(root)
    assert state._next_run_number() == 2


def test_setup_writes_to_run_dir(tmp_path):
    """After setup(), write_task writes into the run directory."""
    root = tmp_path / "state"
    state = StateDir(root)
    state.setup()
    state.write_task("hello")
    assert (state.path / "task.md").read_text() == "hello"
    assert state.path.parent == root / "runs"


# ── Single-invocation invariant ─────────────────────────────────────


def test_setup_creates_exactly_one_run_directory(tmp_path):
    """setup() must create exactly one numbered run directory."""
    root = tmp_path / "state"
    state = StateDir(root)
    state.setup()
    runs = list((root / "runs").iterdir())
    assert len(runs) == 1
    assert runs[0].name == "001"


def test_iterations_do_not_create_run_directories(tmp_path):
    """write_iteration + clean_for_next_iteration must not create new run dirs."""
    root = tmp_path / "state"
    state = StateDir(root)
    state.setup()

    for i in range(1, 4):
        state.write_iteration(i)
        state.write_task("task")
        (state.path / "review-result.md").write_text("REVISE")
        (state.path / "work-summary.md").write_text("did stuff")
        (state.path / "work-complete.md").write_text("done")
        state.clean_for_next_iteration()

    runs = list((root / "runs").iterdir())
    assert len(runs) == 1
    assert runs[0].name == "001"


def test_full_lifecycle_single_run_directory(tmp_path):
    """Simulates a full loop: setup, multiple iterations, all state ops. One run dir."""
    root = tmp_path / "state"
    state = StateDir(root)
    state.setup()
    state.write_task("build the thing")

    # Iteration 1: REVISE
    state.write_iteration(1)
    (state.path / "work-summary.md").write_text("started")
    (state.path / "review-result.md").write_text("REVISE")
    (state.path / "review-feedback.md").write_text("needs tests")
    assert state.read_review_result() == "REVISE"
    assert state.read_review_feedback() == "needs tests"
    state.clean_for_next_iteration()
    # Feedback preserved for next iteration
    assert state.read_review_feedback() == "needs tests"

    # Iteration 2: SHIP
    state.write_iteration(2)
    (state.path / "work-summary.md").write_text("added tests")
    (state.path / "review-result.md").write_text("SHIP")
    assert state.read_review_result() == "SHIP"

    # Still exactly one run directory
    runs = [d for d in (root / "runs").iterdir() if d.is_dir()]
    assert len(runs) == 1
    assert runs[0].name == "001"
    # Task persists across iterations
    assert state.read_task() == "build the thing"


# ── State isolation between runs ────────────────────────────────────


def test_state_isolation_between_runs(tmp_path):
    """Each invocation gets its own run directory with independent state."""
    root = tmp_path / "state"

    state1 = StateDir(root)
    state1.setup()
    state1.write_task("task one")
    (state1.path / "work-summary.md").write_text("summary one")

    state2 = StateDir(root)
    state2.setup()
    state2.write_task("task two")

    # Run 001 data is untouched
    assert (root / "runs" / "001" / "task.md").read_text() == "task one"
    assert (root / "runs" / "001" / "work-summary.md").read_text() == "summary one"
    # Run 002 has its own data
    assert (root / "runs" / "002" / "task.md").read_text() == "task two"
    assert not (root / "runs" / "002" / "work-summary.md").exists()
    # Only two run directories
    runs = sorted(d.name for d in (root / "runs").iterdir() if d.is_dir())
    assert runs == ["001", "002"]


# ── Symlink consistency ─────────────────────────────────────────────


def test_symlink_and_run_dir_are_consistent(tmp_path):
    """Files written through the symlink are readable from the run dir and vice versa."""
    root = tmp_path / "state"
    state = StateDir(root)
    state.setup()

    # Write through the real run dir path
    state.write_task("hello from run dir")
    # Read through the symlink
    symlink_task = (root / "current" / "task.md").read_text()
    assert symlink_task == "hello from run dir"

    # Write through the symlink
    (root / "current" / "work-summary.md").write_text("hello from symlink")
    # Read through the real run dir path
    assert state.read_work_summary() == "hello from symlink"
