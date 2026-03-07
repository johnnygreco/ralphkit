import re
import secrets
from datetime import datetime

JOB_ID_PREFIX = "rk-"


def make_job_id(task: str) -> str:
    """Generate a human-readable, unique job ID."""
    slug = re.sub(r"[^a-z0-9]+", "-", task.lower())[:30].strip("-") or "job"
    ts = datetime.now().strftime("%m%d-%H%M%S")
    rand = secrets.token_hex(2)  # 4 hex chars
    return f"{JOB_ID_PREFIX}{slug}-{ts}-{rand}"
