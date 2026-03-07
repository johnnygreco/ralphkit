from ralphkit.jobs import make_job_id


def test_make_job_id_starts_with_rk_prefix():
    result = make_job_id("deploy the app")
    assert result.startswith("rk-")


def test_make_job_id_special_characters_produce_valid_slug():
    result = make_job_id("Fix bug #42 in api/v2!!")
    # slug part is between first "rk-" prefix and the timestamp
    parts = result.split("-")
    # All slug parts should be alphanumeric (no special chars)
    slug_parts = parts[1:-4]  # skip "rk" prefix and ts/rand suffix
    for part in slug_parts:
        assert part.isalnum(), f"Slug part '{part}' contains non-alphanumeric chars"


def test_make_job_id_empty_ish_string_uses_fallback():
    result = make_job_id("!!@@##$$")
    assert result.startswith("rk-job-")


def test_make_job_id_uniqueness():
    id1 = make_job_id("same task")
    id2 = make_job_id("same task")
    assert id1 != id2


def test_make_job_id_slug_truncated_to_30_chars():
    long_task = "a" * 100
    result = make_job_id(long_task)
    # Extract slug: everything between "rk-" and the timestamp segment
    # Format: rk-{slug}-{MMDD}-{HHMMSS}-{hex4}
    without_prefix = result[3:]  # remove "rk-"
    # slug ends before the timestamp, which is 4 digits dash 6 digits dash 4 hex
    # Find slug by removing the last 3 dash-separated parts (MMDD, HHMMSS, hex)
    parts = without_prefix.rsplit("-", 3)
    slug = parts[0]
    assert len(slug) <= 30
