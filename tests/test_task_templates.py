from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
TASK_TEMPLATES = REPO_ROOT / "templates" / "tasks"


def test_task_templates_exist_for_built_in_workflows():
    expected = {
        "build.md",
        "fix.md",
        "research.md",
        "plan.md",
        "big-swing.md",
    }
    assert {p.name for p in TASK_TEMPLATES.iterdir() if p.suffix == ".md"} == expected


def test_build_template_is_workflow_agnostic():
    text = (TASK_TEMPLATES / "build.md").read_text()
    assert "## Goal" in text
    assert "## Acceptance Criteria" in text
    assert "`build` already handles planning, implementation, and cleanup" in text


def test_fix_template_captures_expected_bug_report_fields():
    text = (TASK_TEMPLATES / "fix.md").read_text()
    for section in (
        "## Bug Summary",
        "## Expected Behavior",
        "## Actual Behavior",
        "## Reproduction",
        "## Acceptance Criteria",
    ):
        assert section in text


def test_research_and_plan_templates_define_default_output_names():
    research = (TASK_TEMPLATES / "research.md").read_text()
    plan = (TASK_TEMPLATES / "plan.md").read_text()
    assert "research-report.md" in research
    assert "implementation-plan.md" in plan


def test_big_swing_template_calls_out_full_pipeline_ownership():
    text = (TASK_TEMPLATES / "big-swing.md").read_text()
    assert "## Risks And Watchouts" in text
    assert "`big-swing` already owns that sequence" in text
