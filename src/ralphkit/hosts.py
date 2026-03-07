from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass
class HostConfig:
    name: str
    hostname: str
    user: str | None = None
    working_dir: str | None = None
    ralph_command: str = "ralph"
    env: dict[str, str] | None = None


def _config_path() -> Path:
    return Path.home() / ".config" / "ralphkit" / "hosts.yaml"


def load_hosts_config(
    path: Path | None = None,
) -> tuple[str | None, dict[str, HostConfig]]:
    """Load hosts config from YAML file.

    Returns (default_host_name, {name: HostConfig}).
    """
    config_file = path or _config_path()
    if not config_file.exists():
        return None, {}

    with open(config_file) as f:
        data = yaml.safe_load(f) or {}

    valid_keys = {"default", "hosts"}
    unknown = set(data) - valid_keys
    if unknown:
        from ralphkit.ui import err_console

        err_console.print(
            f"[warning]Warning: unknown hosts config keys ignored: {', '.join(sorted(unknown))}[/]"
        )

    default = data.get("default")
    raw_hosts = data.get("hosts", {})
    if not isinstance(raw_hosts, dict):
        raise ValueError("'hosts' must be a mapping of name -> host config")

    host_map: dict[str, HostConfig] = {}
    valid_host_keys = {"hostname", "user", "working_dir", "ralph_command", "env"}
    for name, cfg in raw_hosts.items():
        if not isinstance(cfg, dict):
            raise ValueError(f"Host '{name}' config must be a mapping")
        if "hostname" not in cfg:
            raise ValueError(f"Host '{name}' is missing required field 'hostname'")

        unknown_host = set(cfg) - valid_host_keys
        if unknown_host:
            from ralphkit.ui import err_console

            err_console.print(
                f"[warning]Warning: host '{name}' has unknown keys: {', '.join(sorted(unknown_host))}[/]"
            )

        env = cfg.get("env")
        if env is not None:
            if not isinstance(env, dict):
                raise ValueError(f"Host '{name}' env must be a mapping of key: value")
            env = {str(k): str(v) for k, v in env.items()}

        host_map[name] = HostConfig(
            name=name,
            hostname=cfg["hostname"],
            user=cfg.get("user"),
            working_dir=cfg.get("working_dir"),
            ralph_command=cfg.get("ralph_command", "ralph"),
            env=env,
        )

    if default and default not in host_map:
        raise ValueError(
            f"Default host '{default}' not found in hosts config.\n"
            f"  Available: {', '.join(sorted(host_map))}"
        )

    return default, host_map


def resolve_host(name: str, path: Path | None = None) -> HostConfig:
    """Resolve a host name to its config. Raises SystemExit with helpful message."""
    default, host_map = load_hosts_config(path)

    if not host_map:
        raise SystemExit(
            "No hosts configured. Create ~/.config/ralphkit/hosts.yaml\n"
            "  See: ralph hosts --help"
        )

    if name not in host_map:
        raise SystemExit(
            f"Unknown host '{name}'.\n  Available: {', '.join(sorted(host_map))}"
        )

    return host_map[name]
