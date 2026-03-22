from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
TASK_TEMPLATES = REPO_ROOT / "templates" / "tasks"


def test_build_template_exists():
    assert (TASK_TEMPLATES / "build.md").is_file()


def test_build_template_is_workflow_agnostic():
    text = (TASK_TEMPLATES / "build.md").read_text()
    assert "## Goal" in text
    assert "## Acceptance Criteria" in text
    assert "`build` already handles planning, implementation, and cleanup" in text
