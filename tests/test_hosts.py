import pytest

from ralphkit.hosts import load_hosts_config, resolve_host


def test_load_hosts_config_valid(tmp_path):
    cfg = tmp_path / "hosts.yaml"
    cfg.write_text(
        """\
default: dev
hosts:
  dev:
    hostname: dev.example.com
    user: deploy
    working_dir: /opt/app
  staging:
    hostname: staging.example.com
"""
    )
    default, hosts = load_hosts_config(cfg)
    assert default == "dev"
    assert len(hosts) == 2
    assert hosts["dev"].name == "dev"
    assert hosts["dev"].hostname == "dev.example.com"
    assert hosts["dev"].user == "deploy"
    assert hosts["dev"].working_dir == "/opt/app"
    assert hosts["dev"].ralph_command == "ralph"
    assert hosts["dev"].env is None
    assert hosts["staging"].hostname == "staging.example.com"
    assert hosts["staging"].user is None


def test_load_hosts_config_missing_file(tmp_path):
    default, hosts = load_hosts_config(tmp_path / "nonexistent.yaml")
    assert default is None
    assert hosts == {}


def test_load_hosts_config_missing_hostname(tmp_path):
    cfg = tmp_path / "hosts.yaml"
    cfg.write_text(
        """\
hosts:
  broken:
    user: deploy
"""
    )
    with pytest.raises(ValueError, match="Host 'broken' is missing required field 'hostname'"):
        load_hosts_config(cfg)


def test_load_hosts_config_warns_unknown_top_keys(tmp_path, capsys):
    cfg = tmp_path / "hosts.yaml"
    cfg.write_text(
        """\
bogus: true
hosts:
  dev:
    hostname: dev.example.com
"""
    )
    load_hosts_config(cfg)
    assert "unknown hosts config keys ignored: bogus" in capsys.readouterr().err


def test_load_hosts_config_warns_unknown_host_keys(tmp_path, capsys):
    cfg = tmp_path / "hosts.yaml"
    cfg.write_text(
        """\
hosts:
  dev:
    hostname: dev.example.com
    mystery: value
"""
    )
    load_hosts_config(cfg)
    assert "host 'dev' has unknown keys: mystery" in capsys.readouterr().err


def test_load_hosts_config_default_not_in_hosts(tmp_path):
    cfg = tmp_path / "hosts.yaml"
    cfg.write_text(
        """\
default: prod
hosts:
  dev:
    hostname: dev.example.com
"""
    )
    with pytest.raises(ValueError, match="Default host 'prod' not found"):
        load_hosts_config(cfg)


def test_resolve_host_returns_config(tmp_path):
    cfg = tmp_path / "hosts.yaml"
    cfg.write_text(
        """\
hosts:
  dev:
    hostname: dev.example.com
    user: deploy
"""
    )
    host = resolve_host("dev", cfg)
    assert host.name == "dev"
    assert host.hostname == "dev.example.com"
    assert host.user == "deploy"


def test_resolve_host_unknown_name(tmp_path):
    cfg = tmp_path / "hosts.yaml"
    cfg.write_text(
        """\
hosts:
  dev:
    hostname: dev.example.com
"""
    )
    with pytest.raises(SystemExit, match="Unknown host 'prod'"):
        resolve_host("prod", cfg)


def test_resolve_host_no_config(tmp_path):
    with pytest.raises(SystemExit, match="No hosts configured"):
        resolve_host("dev", tmp_path / "nonexistent.yaml")


def test_load_hosts_config_with_env(tmp_path):
    cfg = tmp_path / "hosts.yaml"
    cfg.write_text(
        """\
hosts:
  dev:
    hostname: dev.example.com
    env:
      FOO: bar
      BAZ: qux
"""
    )
    _, hosts = load_hosts_config(cfg)
    assert hosts["dev"].env == {"FOO": "bar", "BAZ": "qux"}


def test_load_hosts_config_ralph_command_override(tmp_path):
    cfg = tmp_path / "hosts.yaml"
    cfg.write_text(
        """\
hosts:
  dev:
    hostname: dev.example.com
    ralph_command: /usr/local/bin/ralph
"""
    )
    _, hosts = load_hosts_config(cfg)
    assert hosts["dev"].ralph_command == "/usr/local/bin/ralph"


def test_load_hosts_config_hosts_not_mapping(tmp_path):
    cfg = tmp_path / "hosts.yaml"
    cfg.write_text(
        """\
hosts:
  - hostname: dev.example.com
"""
    )
    with pytest.raises(ValueError, match="'hosts' must be a mapping"):
        load_hosts_config(cfg)


def test_load_hosts_config_host_entry_not_mapping(tmp_path):
    cfg = tmp_path / "hosts.yaml"
    cfg.write_text(
        """\
hosts:
  dev: just-a-string
"""
    )
    with pytest.raises(ValueError, match="Host 'dev' config must be a mapping"):
        load_hosts_config(cfg)
