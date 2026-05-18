"""C12 tests: heartbeat_config.py CLI + heartbeat_beacon.sh."""
from __future__ import annotations

import os
import stat
import subprocess
import sys
import textwrap
from pathlib import Path
from unittest import mock

import pytest

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO))
sys.path.insert(0, str(_REPO / "core" / "lib"))
sys.path.insert(0, str(_REPO / "core" / "scripts"))
sys.path.insert(0, str(_REPO / "core" / "skills" / "gstack-harness" / "scripts"))

import heartbeat_config as hc  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@pytest.fixture()
def tmp_home(tmp_path, monkeypatch):
    """Isolated home dir; patch real_user_home to return it."""
    monkeypatch.setattr("heartbeat_config.real_user_home", lambda: tmp_path)
    return tmp_path


def _write_binding(tmp_home: Path, project: str, group_id: str = "<FEISHU_GROUP_ID>", external: bool = False) -> None:
    bdir = tmp_home / ".agents" / "tasks" / project
    bdir.mkdir(parents=True, exist_ok=True)
    (bdir / "PROJECT_BINDING.toml").write_text(
        f'version = 1\nproject = "{project}"\n'
        f'feishu_group_id = "{group_id}"\n'
        f'feishu_group_name = "Test Group"\n'
        f'feishu_external = {"true" if external else "false"}\n'
        f'feishu_bot_account = "koder"\n'
        f'require_mention = false\n'
        f'bound_at = "2026-01-01T00:00:00+00:00"\n',
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# parse_cadence_seconds
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("cadence,expected", [
    ("5min", 300),
    ("10min", 600),
    ("30m", 1800),
    ("1h", 3600),
    ("2h", 7200),
    ("600", 600),
    ("60", 60),
])
def test_parse_cadence_valid(cadence, expected):
    assert hc.parse_cadence_seconds(cadence) == expected


@pytest.mark.parametrize("bad", ["", "abc", "5 min", "-1min"])
def test_parse_cadence_invalid(bad):
    with pytest.raises(ValueError, match="invalid cadence"):
        hc.parse_cadence_seconds(bad)


def test_parse_cadence_raw_int():
    assert hc.parse_cadence_seconds("300") == 300


# ---------------------------------------------------------------------------
# cmd_set + cmd_show round-trip
# ---------------------------------------------------------------------------


def test_set_show_roundtrip(tmp_home):
    rc = hc.main(["set", "--project", "install", "--cadence", "5min",
                  "--template", "[HEARTBEAT_TICK project={project} ts={ts}] patrol",
                  "--feishu-group-id", "<FEISHU_GROUP_ID>"])
    assert rc == 0

    cfg = hc.load_config("install", home=tmp_home)
    assert cfg is not None
    assert cfg["project"] == "install"
    assert cfg["cadence"] == "5min"
    assert cfg["message_template"] == "[HEARTBEAT_TICK project={project} ts={ts}] patrol"
    assert cfg["feishu_group_id"] == "<FEISHU_GROUP_ID>"
    assert cfg["enabled"] is True
    assert cfg["version"] == 1
    assert cfg["created_at"] != ""
    assert cfg["updated_at"] != ""


def test_set_updates_existing(tmp_home):
    hc.main(["set", "--project", "install", "--cadence", "5min",
             "--feishu-group-id", "<FEISHU_GROUP_ID>"])
    cfg1 = hc.load_config("install", home=tmp_home)
    created_at = cfg1["created_at"]

    hc.main(["set", "--project", "install", "--cadence", "10min"])
    cfg2 = hc.load_config("install", home=tmp_home)
    assert cfg2["cadence"] == "10min"
    assert cfg2["created_at"] == created_at  # preserved on update
    assert cfg2["updated_at"] >= created_at


def test_set_enabled_false(tmp_home):
    hc.main(["set", "--project", "install", "--cadence", "5min",
             "--feishu-group-id", "oc_x", "--enabled", "false"])
    cfg = hc.load_config("install", home=tmp_home)
    assert cfg["enabled"] is False


def test_set_rejects_invalid_cadence(tmp_home, capsys):
    rc = hc.main(["set", "--project", "install", "--cadence", "abc",
                  "--feishu-group-id", "oc_x"])
    assert rc != 0
    captured = capsys.readouterr()
    assert "invalid cadence" in captured.err


# ---------------------------------------------------------------------------
# Auto-pull feishu_group_id from PROJECT_BINDING.toml
# ---------------------------------------------------------------------------


def test_set_auto_pulls_feishu_group_id(tmp_home):
    _write_binding(tmp_home, "install", group_id="<FEISHU_GROUP_ID>")
    # Patch load_binding to use tmp_home
    with mock.patch("heartbeat_config._resolve_feishu_group_id",
                    return_value="<FEISHU_GROUP_ID>"):
        rc = hc.main(["set", "--project", "install", "--cadence", "5min"])
    assert rc == 0
    cfg = hc.load_config("install", home=tmp_home)
    assert cfg["feishu_group_id"] == "<FEISHU_GROUP_ID>"


def test_set_explicit_group_id_overrides_binding(tmp_home):
    _write_binding(tmp_home, "install", group_id="<FEISHU_GROUP_ID>")
    with mock.patch("heartbeat_config._resolve_feishu_group_id",
                    return_value="<FEISHU_GROUP_ID>"):
        rc = hc.main(["set", "--project", "install", "--cadence", "5min",
                      "--feishu-group-id", "<FEISHU_GROUP_ID>"])
    assert rc == 0
    cfg = hc.load_config("install", home=tmp_home)
    assert cfg["feishu_group_id"] == "<FEISHU_GROUP_ID>"


# ---------------------------------------------------------------------------
# External group warning
# ---------------------------------------------------------------------------


def test_set_warns_on_external_group(tmp_home, capsys):
    with mock.patch("heartbeat_config._warn_if_external") as warn_mock:
        hc.main(["set", "--project", "install", "--cadence", "5min",
                 "--feishu-group-id", "oc_x"])
        assert warn_mock.called
        call_args = warn_mock.call_args
        assert call_args[0][0] == "install"


# ---------------------------------------------------------------------------
# cmd_list
# ---------------------------------------------------------------------------


def test_list_empty(tmp_home, capsys):
    rc = hc.main(["list"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "no heartbeat configs" in out


def test_list_shows_projects(tmp_home, capsys):
    hc.main(["set", "--project", "install", "--cadence", "5min",
             "--feishu-group-id", "oc_a"])
    hc.main(["set", "--project", "other", "--cadence", "1h",
             "--feishu-group-id", "oc_b"])
    rc = hc.main(["list"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "install" in out
    assert "other" in out


# ---------------------------------------------------------------------------
# render-plist
# ---------------------------------------------------------------------------


def test_render_plist_stdout(tmp_home, capsys):
    hc.main(["set", "--project", "install", "--cadence", "10min",
             "--feishu-group-id", "oc_x"])
    rc = hc.main(["render-plist", "--project", "install"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "com.clawseat.heartbeat.install" in out
    assert "<integer>600</integer>" in out
    assert "heartbeat_beacon.sh" in out
    assert "StartInterval" in out


def test_render_plist_to_file(tmp_home, tmp_path):
    hc.main(["set", "--project", "install", "--cadence", "5min",
             "--feishu-group-id", "oc_x"])
    out_file = tmp_path / "test.plist"
    rc = hc.main(["render-plist", "--project", "install",
                  "--output", str(out_file)])
    assert rc == 0
    assert out_file.exists()
    xml = out_file.read_text()
    assert "com.clawseat.heartbeat.install" in xml
    assert "<integer>300</integer>" in xml


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS only")
def test_render_plist_valid_xml(tmp_home, tmp_path):
    """plutil -lint must accept the generated plist."""
    hc.main(["set", "--project", "install", "--cadence", "5min",
             "--feishu-group-id", "oc_x"])
    out_file = tmp_path / "test.plist"
    hc.main(["render-plist", "--project", "install", "--output", str(out_file)])
    result = subprocess.run(
        ["plutil", "-lint", str(out_file)],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, f"plutil error: {result.stderr}"


def test_render_plist_missing_config(tmp_home, capsys):
    rc = hc.main(["render-plist", "--project", "nonexistent"])
    assert rc != 0
    assert "no config" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# validate
# ---------------------------------------------------------------------------


def test_validate_valid_config(tmp_home, capsys):
    hc.main(["set", "--project", "install", "--cadence", "5min",
             "--feishu-group-id", "oc_x"])
    rc = hc.main(["validate", "--project", "install"])
    assert rc == 0
    assert "valid" in capsys.readouterr().out


def test_validate_missing_group_id(tmp_home, capsys):
    hc.main(["set", "--project", "install", "--cadence", "5min"])
    # Force group_id to empty
    cfg = hc.load_config("install", home=tmp_home)
    cfg["feishu_group_id"] = ""
    hc._write_config(cfg, hc.config_path("install", home=tmp_home))
    rc = hc.main(["validate", "--project", "install"])
    assert rc != 0
    assert "feishu_group_id" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# heartbeat_beacon.sh via subprocess
# ---------------------------------------------------------------------------


@pytest.fixture()
def stub_lark_cli(tmp_path):
    """Write a stub lark-cli that logs its argv and exits 0."""
    stub = tmp_path / "stub_lark-cli"
    log = tmp_path / "stub_lark_cli.log"
    stub.write_text(
        f"#!/usr/bin/env bash\necho \"$@\" >> {log}\nexit 0\n",
        encoding="utf-8",
    )
    stub.chmod(stub.stat().st_mode | stat.S_IEXEC)
    return stub, log


def _write_heartbeat_toml(home: Path, project: str, group_id: str,
                          template: str, enabled: bool = True) -> Path:
    hdir = home / ".agents" / "heartbeat"
    hdir.mkdir(parents=True, exist_ok=True)
    p = hdir / f"{project}.toml"
    p.write_text(
        f'version = 1\n'
        f'project = "{project}"\n'
        f'enabled = {"true" if enabled else "false"}\n'
        f'cadence = "5min"\n'
        f'feishu_group_id = "{group_id}"\n'
        f'message_template = "{template}"\n'
        f'created_at = "2026-01-01T00:00:00+00:00"\n'
        f'updated_at = "2026-01-01T00:00:00+00:00"\n',
        encoding="utf-8",
    )
    return p


def _run_beacon(project: str, lark_cli_path: str, tmp_home: Path) -> subprocess.CompletedProcess:
    beacon = _REPO / "core" / "scripts" / "heartbeat_beacon.sh"
    env = {**os.environ, "HOME": str(tmp_home), "LARK_CLI_OVERRIDE": lark_cli_path}
    return subprocess.run(
        ["bash", str(beacon), project],
        capture_output=True, text=True, env=env, timeout=10,
    )


def test_beacon_reads_toml_and_invokes_lark_cli(tmp_path, stub_lark_cli):
    stub_path, log_path = stub_lark_cli
    _write_heartbeat_toml(
        tmp_path, "install", "<FEISHU_GROUP_ID>",
        "[HEARTBEAT_TICK project={project} ts={ts}] patrol",
    )
    result = _run_beacon("install", str(stub_path), tmp_path)
    assert result.returncode == 0, result.stderr
    logged = log_path.read_text()
    assert "im" in logged
    assert "+messages-send" in logged
    assert "--as" in logged
    assert "user" in logged
    assert "--chat-id" in logged
    assert "<FEISHU_GROUP_ID>" in logged
    assert "--text" in logged
    assert "[HEARTBEAT_TICK project=install" in logged


def test_beacon_substitutes_project_and_ts(tmp_path, stub_lark_cli):
    stub_path, log_path = stub_lark_cli
    _write_heartbeat_toml(
        tmp_path, "myproject", "oc_xyz",
        "[HEARTBEAT_TICK project={project} ts={ts}] test",
    )
    result = _run_beacon("myproject", str(stub_path), tmp_path)
    assert result.returncode == 0
    logged = log_path.read_text()
    assert "project=myproject" in logged
    # ts format: 2026-...T...Z
    assert "ts=20" in logged
    assert "{project}" not in logged
    assert "{ts}" not in logged


def test_beacon_exits_nonzero_on_missing_config(tmp_path, stub_lark_cli):
    stub_path, _ = stub_lark_cli
    result = _run_beacon("nosuchproject", str(stub_path), tmp_path)
    assert result.returncode != 0
    assert "no config" in result.stderr


def test_beacon_exits_nonzero_on_send_failure(tmp_path, tmp_path_factory):
    # Use a failing stub
    stub_dir = tmp_path_factory.mktemp("stub_fail")
    stub = stub_dir / "lark-cli"
    stub.write_text("#!/usr/bin/env bash\nexit 1\n", encoding="utf-8")
    stub.chmod(stub.stat().st_mode | stat.S_IEXEC)

    _write_heartbeat_toml(tmp_path, "install", "oc_x", "[TICK project={project} ts={ts}]")
    result = _run_beacon("install", str(stub), tmp_path)
    assert result.returncode != 0
    assert "send failed" in result.stderr


def test_beacon_skips_when_disabled(tmp_path, stub_lark_cli):
    stub_path, log_path = stub_lark_cli
    _write_heartbeat_toml(tmp_path, "install", "oc_x",
                          "[TICK project={project} ts={ts}]", enabled=False)
    result = _run_beacon("install", str(stub_path), tmp_path)
    assert result.returncode == 0
    assert not log_path.exists()  # stub was never called


# ---------------------------------------------------------------------------
# Concurrency: two beacons for different projects don't collide
# ---------------------------------------------------------------------------


def test_beacon_concurrency_different_projects(tmp_path, tmp_path_factory):
    """Two simultaneous beacons for different projects use separate configs."""
    stubs = []
    for i in range(2):
        d = tmp_path_factory.mktemp(f"stub{i}")
        s = d / "lark-cli"
        lg = d / "log"
        s.write_text(
            f"#!/usr/bin/env bash\necho \"$@\" >> {lg}\nexit 0\n",
            encoding="utf-8",
        )
        s.chmod(s.stat().st_mode | stat.S_IEXEC)
        stubs.append((s, lg))

    projects = ["alpha", "beta"]
    homes = [tmp_path_factory.mktemp(f"home{i}") for i in range(2)]
    for i, proj in enumerate(projects):
        _write_heartbeat_toml(homes[i], proj, f"oc_{proj}",
                              f"[TICK project={{project}} ts={{ts}}] {proj}")

    beacon = _REPO / "core" / "scripts" / "heartbeat_beacon.sh"
    procs = []
    for i, proj in enumerate(projects):
        env = {**os.environ, "HOME": str(homes[i]),
               "LARK_CLI_OVERRIDE": str(stubs[i][0])}
        p = subprocess.Popen(
            ["bash", str(beacon), proj],
            env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        procs.append(p)

    for p in procs:
        p.wait(timeout=10)
        assert p.returncode == 0

    for i, proj in enumerate(projects):
        logged = stubs[i][1].read_text()
        assert f"oc_{proj}" in logged
        assert proj in logged
