from dataclasses import dataclass, fields
from pathlib import Path

import yaml


@dataclass
class RalphConfig:
    worker_model: str = "opus"
    reviewer_model: str = "sonnet"
    max_iterations: int = 10
    task: str | None = None


def load_config(path: str | Path) -> RalphConfig:
    """Load config from a YAML file. Missing keys use defaults."""
    path = Path(path)
    if not path.exists():
        return RalphConfig()
    with open(path) as f:
        data = yaml.safe_load(f) or {}
    kwargs = {f.name: data[f.name] for f in fields(RalphConfig) if f.name in data}
    if "max_iterations" in kwargs:
        kwargs["max_iterations"] = int(kwargs["max_iterations"])
    return RalphConfig(**kwargs)
