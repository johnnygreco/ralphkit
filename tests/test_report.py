import json

from ralphkit.report import RunReport, _parse_shortstat, print_report


def test_record_step_basic():
    report = RunReport()
    report.record_step(step_name="worker", model="opus", phase="loop", duration_s=10.0)
    assert len(report.steps) == 1
    assert report.steps[0].step_name == "worker"
    assert report.steps[0].model == "opus"
    assert report.steps[0].phase == "loop"
    assert report.steps[0].duration_s == 10.0
    assert report.steps[0].num_turns is None
    assert report.steps[0].model_usage is None


def test_record_step_with_model_usage():
    claude_out = {
        "num_turns": 5,
        "session_id": "abc-123",
        "is_error": False,
        "duration_api_ms": 3000,
        "modelUsage": {
            "claude-opus-4-6": {
                "inputTokens": 100,
                "outputTokens": 50,
                "cacheReadInputTokens": 200,
                "cacheCreationInputTokens": 300,
            }
        },
    }
    report = RunReport()
    report.record_step(
        step_name="worker",
        model="opus",
        phase="loop",
        duration_s=5.0,
        claude_output=claude_out,
    )
    s = report.steps[0]
    assert s.num_turns == 5
    assert s.session_id == "abc-123"
    assert s.is_error is False
    assert s.duration_api_ms == 3000
    assert s.model_usage == claude_out["modelUsage"]


def test_record_step_with_failure_fields():
    report = RunReport()
    report.record_step(
        step_name="worker",
        model="opus",
        phase="loop",
        status="timeout",
        duration_s=5.0,
        iteration=2,
        error_kind="hard_timeout",
        error_message="timed out",
        timeout_seconds=1800,
        idle_timeout_seconds=120,
        diagnostics_path="/tmp/diag.json",
        claude_transcript_path="/tmp/transcript.jsonl",
        lines_added=3,
        lines_deleted=1,
    )
    step = report.steps[0]
    assert step.status == "timeout"
    assert step.iteration == 2
    assert step.error_kind == "hard_timeout"
    assert step.error_message == "timed out"
    assert step.timeout_seconds == 1800
    assert step.idle_timeout_seconds == 120
    assert step.diagnostics_path == "/tmp/diag.json"
    assert step.claude_transcript_path == "/tmp/transcript.jsonl"
    assert step.lines_added == 3
    assert step.lines_deleted == 1


def test_record_step_missing_fields():
    claude_out = {"num_turns": 2}
    report = RunReport()
    report.record_step(
        step_name="w",
        model="m",
        phase="pipe",
        duration_s=1.0,
        claude_output=claude_out,
    )
    s = report.steps[0]
    assert s.num_turns == 2
    assert s.session_id is None
    assert s.is_error is None
    assert s.duration_api_ms is None
    assert s.model_usage is None


def test_token_usage_by_model_aggregation():
    report = RunReport()
    report.record_step(
        step_name="w",
        model="opus",
        phase="loop",
        duration_s=1.0,
        claude_output={
            "modelUsage": {"claude-opus-4-6": {"inputTokens": 100, "outputTokens": 50}}
        },
    )
    report.record_step(
        step_name="r",
        model="sonnet",
        phase="loop",
        duration_s=1.0,
        claude_output={
            "modelUsage": {
                "claude-sonnet-4-6": {"inputTokens": 200, "outputTokens": 30}
            }
        },
    )
    usage = report.token_usage_by_model()
    assert usage["claude-opus-4-6"]["inputTokens"] == 100
    assert usage["claude-sonnet-4-6"]["outputTokens"] == 30


def test_token_usage_by_model_same_model():
    report = RunReport()
    for _ in range(2):
        report.record_step(
            step_name="w",
            model="opus",
            phase="loop",
            duration_s=1.0,
            claude_output={
                "modelUsage": {
                    "claude-opus-4-6": {"inputTokens": 100, "outputTokens": 50}
                }
            },
        )
    usage = report.token_usage_by_model()
    assert usage["claude-opus-4-6"]["inputTokens"] == 200
    assert usage["claude-opus-4-6"]["outputTokens"] == 100


def test_total_turns():
    report = RunReport()
    report.record_step(
        step_name="a",
        model="m",
        phase="loop",
        duration_s=1.0,
        claude_output={"num_turns": 3},
    )
    report.record_step(
        step_name="b", model="m", phase="loop", duration_s=1.0, claude_output=None
    )
    report.record_step(
        step_name="c",
        model="m",
        phase="loop",
        duration_s=1.0,
        claude_output={"num_turns": 7},
    )
    assert report.total_turns() == 10


def test_estimated_cost_excludes_cached_from_input():
    """inputTokens includes cache hits/writes; cost should not double-count them."""
    report = RunReport()
    report.record_step(
        step_name="w",
        model="opus",
        phase="loop",
        duration_s=1.0,
        claude_output={
            "modelUsage": {
                "claude-opus-4-6": {
                    "inputTokens": 1_000_000,
                    "outputTokens": 0,
                    "cacheReadInputTokens": 600_000,
                    "cacheCreationInputTokens": 200_000,
                }
            }
        },
    )
    cost = report.estimated_cost_usd()
    # Non-cached input: 1M - 600K - 200K = 200K tokens
    # Expected: 200K * 15/1M + 600K * 1.5/1M + 200K * 18.75/1M
    #         = 3.0 + 0.9 + 3.75 = 7.65
    expected = (200_000 * 15.0 + 600_000 * 1.5 + 200_000 * 18.75) / 1_000_000
    assert abs(cost - expected) < 0.001


def test_to_dict_complete():
    report = RunReport()
    report.outcome = "COMPLETE"
    report.iterations_completed = 2
    report.total_duration_s = 120.0
    report.record_step(
        step_name="w",
        model="opus",
        phase="loop",
        duration_s=60.0,
        iteration=1,
        claude_output={"num_turns": 5, "modelUsage": {"opus": {"inputTokens": 100}}},
        lines_added=10,
        lines_deleted=2,
    )
    d = report.to_dict()
    assert d["outcome"] == "COMPLETE"
    assert d["iterations_completed"] == 2
    assert d["total_duration_s"] == 120.0
    assert d["total_turns"] == 5
    assert len(d["steps"]) == 1
    assert d["steps"][0]["step_name"] == "w"
    assert d["steps"][0]["lines_added"] == 10
    assert "token_usage_by_model" in d
    # Must be JSON-serializable
    json.dumps(d)


def test_save_writes_json(tmp_path):
    report = RunReport()
    report.outcome = "COMPLETE"
    report.total_duration_s = 10.0
    report.record_step(step_name="w", model="opus", phase="loop", duration_s=5.0)
    out = tmp_path / "report.json"
    report.save(out)

    data = json.loads(out.read_text())
    assert data["outcome"] == "COMPLETE"
    assert len(data["steps"]) == 1


def test_report_round_trip_preserves_failure_summary(tmp_path):
    report = RunReport()
    report.outcome = "ERROR"
    report.iterations_completed = 2
    report.items_completed = 1
    report.items_total = 3
    report.total_duration_s = 12.0
    report.failure_summary = {
        "step_name": "worker",
        "phase": "loop",
        "status": "timeout",
        "error_kind": "hard_timeout",
        "error_message": "timed out",
        "diagnostics_path": "/tmp/diag.json",
    }
    report.record_step(
        step_name="worker",
        model="opus",
        phase="loop",
        status="timeout",
        duration_s=5.0,
        iteration=1,
        diagnostics_path="/tmp/diag.json",
    )

    path = tmp_path / "report.json"
    report.save(path)
    loaded = RunReport.load(path)

    assert loaded.outcome == "ERROR"
    assert loaded.iterations_completed == 2
    assert loaded.items_completed == 1
    assert loaded.items_total == 3
    assert loaded.failure_summary == report.failure_summary
    assert loaded.steps[0].status == "timeout"
    assert loaded.steps[0].diagnostics_path == "/tmp/diag.json"


def test_parse_shortstat_full():
    assert _parse_shortstat(" 3 files changed, 10 insertions(+), 5 deletions(-)") == (
        10,
        5,
    )


def test_parse_shortstat_insertions_only():
    assert _parse_shortstat(" 1 file changed, 5 insertions(+)") == (5, 0)


def test_parse_shortstat_deletions_only():
    assert _parse_shortstat(" 1 file changed, 3 deletions(-)") == (0, 3)


def test_parse_shortstat_empty():
    assert _parse_shortstat("") == (0, 0)


def test_print_report_no_crash(capsys):
    # Empty report
    report = RunReport()
    report.outcome = "COMPLETE"
    print_report(report)
    out = capsys.readouterr().out
    assert "RUN REPORT" in out

    # Populated report
    report.record_step(
        step_name="w",
        model="opus",
        phase="loop",
        duration_s=10.0,
        iteration=1,
        claude_output={
            "num_turns": 3,
            "modelUsage": {"opus": {"inputTokens": 100, "outputTokens": 50}},
        },
        lines_added=5,
        lines_deleted=2,
    )
    print_report(report)
    out = capsys.readouterr().out
    assert "RUN REPORT" in out
    assert "COMPLETE" in out
    assert "Steps" in out
