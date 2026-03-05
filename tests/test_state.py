from ralphkit.state import StateDir


def test_setup_creates_directory(tmp_path):
    state = StateDir(tmp_path / "state")
    state.setup()
    assert state.path.is_dir()


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


def test_setup_idempotent(tmp_path):
    state = StateDir(tmp_path / "state")
    state.setup()
    state.setup()  # second call should not raise
    assert state.path.is_dir()


def test_read_work_summary_returns_content(tmp_path):
    state = StateDir(tmp_path)
    (tmp_path / "work-summary.md").write_text("  summary\n")
    assert state.read_work_summary() == "  summary\n"  # not stripped


def test_read_review_feedback_returns_content(tmp_path):
    state = StateDir(tmp_path)
    (tmp_path / "review-feedback.md").write_text("  feedback\n")
    assert state.read_review_feedback() == "  feedback\n"  # not stripped


def test_default_state_dir_path():
    state = StateDir()
    assert str(state.path) == ".ralphkit"
