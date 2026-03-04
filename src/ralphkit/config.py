from dataclasses import dataclass, fields
from pathlib import Path

import yaml

STATE_DIR = ".ralphkit"

VERDICT_SHIP = "SHIP"
VERDICT_REVISE = "REVISE"


@dataclass
class RalphConfig:
    worker_model: str = "opus"
    reviewer_model: str = "sonnet"
    max_iterations: int = 10


def load_config(path: str | Path | None) -> RalphConfig:
    """Load config from a YAML file. Returns defaults when path is None."""
    if path is None:
        return RalphConfig()
    path = Path(path)
    with open(path) as f:
        data = yaml.safe_load(f) or {}
    valid_fields = {f.name for f in fields(RalphConfig)}
    kwargs = {k: data[k] for k in data if k in valid_fields}
    if "max_iterations" in kwargs:
        kwargs["max_iterations"] = int(kwargs["max_iterations"])
    return RalphConfig(**kwargs)
