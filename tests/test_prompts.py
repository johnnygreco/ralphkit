import pytest

from ralphkit.config import StepConfig
from ralphkit.prompts import (
    PLAN_DESIGN_SYSTEM_PROMPT,
    RESEARCH_REPORT_SYSTEM_PROMPT,
    make_big_swing_config,
    make_build_config,
    make_fix_config,
    make_plan_config,
    make_research_config,
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


# ── Pipe-workflow factories (parametrized) ───────────────────────

PIPE_FACTORIES = [
    (make_fix_config, ["diagnose", "fix", "verify"]),
    (make_research_config, ["explore", "synthesize", "report"]),
    (make_plan_config, ["analyze", "design"]),
    (
        make_big_swing_config,
        ["research", "plan", "build", "review", "fix", "verify"],
    ),
]


@pytest.mark.parametrize(
    "factory, expected_names",
    PIPE_FACTORIES,
    ids=["fix", "research", "plan", "big_swing"],
)
class TestPipeFactoryBasics:
    def test_step_count(self, factory, expected_names):
        steps = factory()
        assert len(steps) == len(expected_names)

    def test_step_names(self, factory, expected_names):
        steps = factory()
        assert [s.step_name for s in steps] == expected_names

    def test_all_step_config_instances(self, factory, expected_names):
        for step in factory():
            assert isinstance(step, StepConfig)

    def test_task_prompts_contain_state_dir(self, factory, expected_names):
        for step in factory():
            assert "{state_dir}" in step.task_prompt

    def test_system_prompts_non_empty(self, factory, expected_names):
        for step in factory():
            assert step.system_prompt


# ── Handoff file consistency ─────────────────────────────────────


def _handoff_name(a: str, b: str) -> str:
    return f"handoff__{a}__to__{b}"


# Factories where consecutive steps hand off via files.
# make_build_config is excluded because its steps don't chain through handoff files.
HANDOFF_FACTORIES = [
    (make_fix_config, ["diagnose", "fix", "verify"]),
    (make_research_config, ["explore", "synthesize", "report"]),
    (make_plan_config, ["analyze", "design"]),
    (
        make_big_swing_config,
        ["research", "plan", "build", "review", "fix", "verify"],
    ),
]


@pytest.mark.parametrize(
    "factory, names",
    HANDOFF_FACTORIES,
    ids=["fix", "research", "plan", "big_swing"],
)
class TestHandoffConsistency:
    def test_writer_references_handoff_file(self, factory, names):
        """Step A's task_prompt mentions writing the handoff file to step B."""
        steps = factory()
        for i in range(len(steps) - 1):
            handoff = _handoff_name(names[i], names[i + 1])
            assert handoff in steps[i].task_prompt, (
                f"Step '{names[i]}' should reference {handoff} in its task_prompt"
            )

    def test_reader_references_handoff_file(self, factory, names):
        """Step B's task_prompt mentions reading the handoff file from step A."""
        steps = factory()
        for i in range(1, len(steps)):
            handoff = _handoff_name(names[i - 1], names[i])
            assert handoff in steps[i].task_prompt, (
                f"Step '{names[i]}' should reference {handoff} in its task_prompt"
            )


# ── Cross-cutting: every factory's prompts contain {state_dir} ──

ALL_FACTORIES = [
    make_build_config,
    make_fix_config,
    make_research_config,
    make_plan_config,
    make_big_swing_config,
]


def _all_steps():
    """Yield (factory_name, step) across every factory."""
    for factory in ALL_FACTORIES:
        result = factory()
        if isinstance(result, dict):
            for group in result.values():
                for step in group:
                    yield factory.__name__, step
        else:
            for step in result:
                yield factory.__name__, step


@pytest.mark.parametrize(
    "factory_name, step",
    list(_all_steps()),
    ids=[f"{fn}-{s.step_name}" for fn, s in _all_steps()],
)
def test_all_prompts_have_state_dir(factory_name, step):
    assert "{state_dir}" in step.task_prompt, (
        f"{factory_name}/{step.step_name} task_prompt missing {{state_dir}}"
    )
    assert step.system_prompt, (
        f"{factory_name}/{step.step_name} has empty system_prompt"
    )


def test_research_report_has_default_output_filename():
    assert "research-report.md" in RESEARCH_REPORT_SYSTEM_PROMPT


def test_plan_design_has_default_output_filename():
    assert "implementation-plan.md" in PLAN_DESIGN_SYSTEM_PROMPT
