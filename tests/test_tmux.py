from ralphkit.tmux import build_job_script, parse_session_list


def test_build_job_script_basic_output():
    script = build_job_script("rk-test-0307-120000-abcd", "ralph run pipe.yml")
    assert script.startswith("#!/usr/bin/env bash\n")
    assert "set -uo pipefail" in script
    assert 'tee "$LOG_FILE"' in script
    assert "RC=${PIPESTATUS[0]}" in script
    assert 'LOG_FILE="$LOG_DIR/rk-test-0307-120000-abcd.log"' in script


def test_build_job_script_with_working_dir():
    script = build_job_script(
        "rk-test-0307-120000-abcd", "ralph run pipe.yml", working_dir="/tmp/work"
    )
    assert "cd /tmp/work || exit 1" in script or "cd '/tmp/work' || exit 1" in script


def test_build_job_script_without_optional_args():
    script = build_job_script("rk-test-0307-120000-abcd", "ralph run pipe.yml")
    assert "cd " not in script


def test_build_job_script_exports_path():
    script = build_job_script("rk-test-0307-120000-abcd", "ralph run pipe.yml")
    assert 'export PATH="$HOME/.local/bin' in script


def test_parse_session_list_empty_string():
    assert parse_session_list("") == []


def test_parse_session_list_rk_prefixed_sessions():
    output = "rk-deploy-0307-1200-ab12\t1709812800\t1709812900\t0\n"
    result = parse_session_list(output)
    assert len(result) == 1
    assert result[0]["name"] == "rk-deploy-0307-1200-ab12"
    assert result[0]["created"] == "1709812800"
    assert result[0]["activity"] == "1709812900"
    assert result[0]["pane_dead"] == "0"


def test_parse_session_list_filters_non_rk_sessions():
    output = (
        "rk-job1-0307-1200-ab12\t1709812800\t1709812900\t0\n"
        "my-other-session\t1709812800\t1709812900\t0\n"
        "rk-job2-0307-1201-cd34\t1709812801\t1709812901\t1\n"
    )
    result = parse_session_list(output)
    assert len(result) == 2
    assert result[0]["name"] == "rk-job1-0307-1200-ab12"
    assert result[1]["name"] == "rk-job2-0307-1201-cd34"


def test_parse_session_list_handles_partial_fields():
    output = "rk-minimal-0307-1200-ab12\n"
    result = parse_session_list(output)
    assert len(result) == 1
    assert result[0]["name"] == "rk-minimal-0307-1200-ab12"
    assert result[0]["created"] is None
    assert result[0]["activity"] is None
    assert result[0]["pane_dead"] is None
