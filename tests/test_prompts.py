from ralphkit.config import StepConfig
from ralphkit.prompts import (
    DEFAULT_CLEANUP_SYSTEM_PROMPT,
    DEFAULT_PLANNER_SYSTEM_PROMPT,
    DEFAULT_WORKER_SYSTEM_PROMPT,
    make_build_config,
)


# ── make_build_config ────────────────────────────────────────────


class TestMakeBuildConfig:
    def test_returns_loop_and_cleanup_keys(self):
        cfg = make_build_config()
        assert set(cfg.keys()) == {"loop", "cleanup"}

    def test_loop_contains_worker_step(self):
        steps = make_build_config()["loop"]
        assert len(steps) == 1
        assert steps[0].step_name == "worker"

    def test_cleanup_contains_review_step(self):
        steps = make_build_config()["cleanup"]
        assert len(steps) == 1
        assert steps[0].step_name == "review"

    def test_all_steps_are_step_config(self):
        cfg = make_build_config()
        for step in cfg["loop"] + cfg["cleanup"]:
            assert isinstance(step, StepConfig)

    def test_prompts_contain_state_dir_placeholder(self):
        cfg = make_build_config()
        for step in cfg["loop"] + cfg["cleanup"]:
            assert "{state_dir}" in step.task_prompt
            assert step.system_prompt  # non-empty


# ── Prompt content checks ────────────────────────────────────────


def test_worker_prompt_mentions_ralph_complete():
    assert "RALPH-COMPLETE.md" in DEFAULT_WORKER_SYSTEM_PROMPT


def test_worker_prompt_mentions_verify_failure():
    assert "verify_failure.txt" in DEFAULT_WORKER_SYSTEM_PROMPT


def test_worker_prompt_has_progress_anti_patterns():
    assert "Do NOT paste test output" in DEFAULT_WORKER_SYSTEM_PROMPT
    assert "Do NOT list completed items" in DEFAULT_WORKER_SYSTEM_PROMPT


def test_planner_prompt_has_state_dir():
    assert "{state_dir}" in DEFAULT_PLANNER_SYSTEM_PROMPT


def test_cleanup_prompt_has_state_dir():
    assert "{state_dir}" in DEFAULT_CLEANUP_SYSTEM_PROMPT
