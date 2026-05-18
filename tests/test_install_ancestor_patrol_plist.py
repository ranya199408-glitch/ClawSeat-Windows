from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path


_HELPERS_PATH = Path(__file__).with_name("test_install_isolation.py")
_HELPERS_SPEC = importlib.util.spec_from_file_location("test_install_isolation_helpers", _HELPERS_PATH)
assert _HELPERS_SPEC is not None and _HELPERS_SPEC.loader is not None
_HELPERS = importlib.util.module_from_spec(_HELPERS_SPEC)
_HELPERS_SPEC.loader.exec_module(_HELPERS)

_fake_install_root = _HELPERS._fake_install_root


def test_install_writes_and_bootstraps_ancestor_patrol_plist(tmp_path: Path) -> None:
    """Opt-in path: `--enable-auto-patrol` renders + bootstraps the plist."""
    root, home, launcher_log, tmux_log, py_stubs = _fake_install_root(tmp_path)
    launchctl_log = tmp_path / "launchctl.log"
    plutil_log = tmp_path / "plutil.log"

    result = subprocess.run(
        ["bash", str(root / "scripts" / "install.sh"),
         "--enable-auto-patrol",
         "--project", "patrol50", "--provider", "minimax"],
        input="\n",
        capture_output=True,
        text=True,
        timeout=30,
        env={
            **os.environ,
            "HOME": str(home),
            "CLAWSEAT_REAL_HOME": str(home),
            "PATH": f"{root.parent / 'bin'}{os.pathsep}{os.environ['PATH']}",
            "PYTHONPATH": f"{py_stubs}{os.pathsep}{os.environ.get('PYTHONPATH', '')}",
            "PYTHON_BIN": sys.executable,
            "LOG_FILE": str(launcher_log),
            "TMUX_LOG_FILE": str(tmux_log),
            "LAUNCHCTL_LOG_FILE": str(launchctl_log),
            "PLUTIL_LOG_FILE": str(plutil_log),
        },
        check=False,
    )

    assert result.returncode == 0, result.stderr

    plist_path = home / "Library" / "LaunchAgents" / "com.clawseat.patrol50.patrol.plist"
    assert plist_path.is_file()
    plist_text = plist_path.read_text(encoding="utf-8")

    assert "com.clawseat.patrol50.patrol" in plist_text
    assert "session-name memory --project 'patrol50'" in plist_text
    assert str(root / "core" / "shell-scripts" / "send-and-verify.sh") in plist_text
    assert "{PROJECT}" not in plist_text
    assert "{CADENCE_SECONDS}" not in plist_text
    assert "{CLAWSEAT_ROOT}" not in plist_text
    assert "{LOG_DIR}" not in plist_text
    assert "{TOOL}" not in plist_text
    assert "={PROJECT}-memory-{TOOL}" not in plist_text
    assert (home / ".agents" / "tasks" / "patrol50" / "patrol" / "logs").is_dir()

    launchctl_lines = launchctl_log.read_text(encoding="utf-8").splitlines()
    assert f"bootout gui/{os.getuid()}/com.clawseat.patrol50.patrol" in launchctl_lines
    assert f"bootstrap gui/{os.getuid()} {plist_path}" in launchctl_lines

    plutil_lines = plutil_log.read_text(encoding="utf-8").splitlines()
    assert plutil_lines == [f"-lint {plist_path}"]


def test_install_dry_run_reports_ancestor_patrol_launchagent(tmp_path: Path) -> None:
    """Opt-in dry-run path: `--enable-auto-patrol --dry-run` previews render+bootstrap."""
    root, home, launcher_log, tmux_log, py_stubs = _fake_install_root(tmp_path)

    result = subprocess.run(
        ["bash", str(root / "scripts" / "install.sh"),
         "--enable-auto-patrol", "--dry-run",
         "--project", "patrol51", "--provider", "minimax"],
        capture_output=True,
        text=True,
        timeout=30,
        env={
            **os.environ,
            "HOME": str(home),
            "CLAWSEAT_REAL_HOME": str(home),
            "PATH": f"{root.parent / 'bin'}{os.pathsep}{os.environ['PATH']}",
            "PYTHONPATH": f"{py_stubs}{os.pathsep}{os.environ.get('PYTHONPATH', '')}",
            "PYTHON_BIN": sys.executable,
            "LOG_FILE": str(launcher_log),
            "TMUX_LOG_FILE": str(tmux_log),
        },
        check=False,
    )

    combined = result.stdout + result.stderr
    plist_path = home / "Library" / "LaunchAgents" / "com.clawseat.patrol51.patrol.plist"

    assert result.returncode == 0, result.stderr
    assert f"[dry-run] render {root / 'core' / 'templates' / 'patrol.plist.in'} -> {plist_path}" in combined
    assert f"[dry-run] launchctl bootstrap gui/{os.getuid()} {plist_path}" in combined


def test_install_default_skips_ancestor_patrol_plist(tmp_path: Path) -> None:
    """Default install (no `--enable-auto-patrol`): plist NOT rendered, no bootstrap."""
    root, home, launcher_log, tmux_log, py_stubs = _fake_install_root(tmp_path)
    launchctl_log = tmp_path / "launchctl.log"
    plutil_log = tmp_path / "plutil.log"

    result = subprocess.run(
        ["bash", str(root / "scripts" / "install.sh"),
         "--project", "patrol52", "--provider", "minimax"],
        input="\n",
        capture_output=True,
        text=True,
        timeout=30,
        env={
            **os.environ,
            "HOME": str(home),
            "CLAWSEAT_REAL_HOME": str(home),
            "PATH": f"{root.parent / 'bin'}{os.pathsep}{os.environ['PATH']}",
            "PYTHONPATH": f"{py_stubs}{os.pathsep}{os.environ.get('PYTHONPATH', '')}",
            "PYTHON_BIN": sys.executable,
            "LOG_FILE": str(launcher_log),
            "TMUX_LOG_FILE": str(tmux_log),
            "LAUNCHCTL_LOG_FILE": str(launchctl_log),
            "PLUTIL_LOG_FILE": str(plutil_log),
        },
        check=False,
    )

    assert result.returncode == 0, result.stderr
    combined = result.stdout + result.stderr
    assert "Step 6: auto-patrol disabled" in combined
    assert "--enable-auto-patrol" in combined  # skip note references the flag

    plist_path = home / "Library" / "LaunchAgents" / "com.clawseat.patrol52.patrol.plist"
    assert not plist_path.exists(), "default install must NOT render patrol plist"

    # No launchctl bootstrap for THIS project (other tests may have left their own entries).
    if launchctl_log.exists():
        launchctl_text = launchctl_log.read_text(encoding="utf-8")
        assert f"bootstrap gui/{os.getuid()} {plist_path}" not in launchctl_text
        assert f"com.clawseat.patrol52.patrol" not in launchctl_text or \
            "bootstrap" not in launchctl_text.split("com.clawseat.patrol52.patrol", 1)[0]


def test_install_default_removes_stale_patrol_plist(tmp_path: Path) -> None:
    """Upgrade path: pre-existing plist from an earlier enabled install must be
    torn down when operator reruns a default install without
    `--enable-auto-patrol`. Otherwise the ghost LaunchAgent keeps firing."""
    root, home, launcher_log, tmux_log, py_stubs = _fake_install_root(tmp_path)
    launchctl_log = tmp_path / "launchctl.log"
    plutil_log = tmp_path / "plutil.log"

    # Seed a stale plist as if a previous `--enable-auto-patrol` install ran.
    plist_path = home / "Library" / "LaunchAgents" / "com.clawseat.patrol53.patrol.plist"
    plist_path.parent.mkdir(parents=True, exist_ok=True)
    plist_path.write_text(
        "<?xml version=\"1.0\"?><plist><dict><key>Label</key>"
        "<string>com.clawseat.patrol53.patrol</string>"
        "</dict></plist>\n",
        encoding="utf-8",
    )
    assert plist_path.is_file()

    result = subprocess.run(
        ["bash", str(root / "scripts" / "install.sh"),
         "--project", "patrol53", "--provider", "minimax"],
        input="\n",
        capture_output=True,
        text=True,
        timeout=30,
        env={
            **os.environ,
            "HOME": str(home),
            "CLAWSEAT_REAL_HOME": str(home),
            "PATH": f"{root.parent / 'bin'}{os.pathsep}{os.environ['PATH']}",
            "PYTHONPATH": f"{py_stubs}{os.pathsep}{os.environ.get('PYTHONPATH', '')}",
            "PYTHON_BIN": sys.executable,
            "LOG_FILE": str(launcher_log),
            "TMUX_LOG_FILE": str(tmux_log),
            "LAUNCHCTL_LOG_FILE": str(launchctl_log),
            "PLUTIL_LOG_FILE": str(plutil_log),
        },
        check=False,
    )

    assert result.returncode == 0, result.stderr
    combined = result.stdout + result.stderr
    assert "cleanup: found stale" in combined

    # Plist file removed.
    assert not plist_path.exists(), "stale plist must be removed on default install"

    # launchctl bootout was called for this label.
    launchctl_text = launchctl_log.read_text(encoding="utf-8") if launchctl_log.exists() else ""
    assert f"bootout gui/{os.getuid()}/com.clawseat.patrol53.patrol" in launchctl_text


def test_install_ready_project_rerun_removes_stale_patrol_plist(tmp_path: Path) -> None:
    """The *real* upgrade path: project is already marked phase=ready AND
    has a stale patrol plist from a pre-Round-8 install. A plain rerun
    (no --reinstall, no --enable-auto-patrol) hits the early-exit in
    `ensure_host_deps` BEFORE Step 6 would ever run — so the cleanup
    must happen inside that early-exit branch, not only in Step 6.
    This is the exact scenario the reviewer reproduced on 11cc490."""
    root, home, launcher_log, tmux_log, py_stubs = _fake_install_root(tmp_path)
    launchctl_log = tmp_path / "launchctl.log"
    plutil_log = tmp_path / "plutil.log"

    # Seed STATUS.md as if the project was fully installed before.
    status_dir = home / ".agents" / "tasks" / "patrol55"
    status_dir.mkdir(parents=True, exist_ok=True)
    (status_dir / "STATUS.md").write_text("phase=ready\n", encoding="utf-8")

    # Seed stale plist as if a prior `--enable-auto-patrol` install ran.
    plist_path = home / "Library" / "LaunchAgents" / "com.clawseat.patrol55.patrol.plist"
    plist_path.parent.mkdir(parents=True, exist_ok=True)
    plist_path.write_text(
        "<?xml version=\"1.0\"?><plist><dict><key>Label</key>"
        "<string>com.clawseat.patrol55.patrol</string>"
        "</dict></plist>\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        ["bash", str(root / "scripts" / "install.sh"),
         "--project", "patrol55", "--provider", "minimax"],
        input="\n",
        capture_output=True,
        text=True,
        timeout=30,
        env={
            **os.environ,
            "HOME": str(home),
            "CLAWSEAT_REAL_HOME": str(home),
            "PATH": f"{root.parent / 'bin'}{os.pathsep}{os.environ['PATH']}",
            "PYTHONPATH": f"{py_stubs}{os.pathsep}{os.environ.get('PYTHONPATH', '')}",
            "PYTHON_BIN": sys.executable,
            "LOG_FILE": str(launcher_log),
            "TMUX_LOG_FILE": str(tmux_log),
            "LAUNCHCTL_LOG_FILE": str(launchctl_log),
            "PLUTIL_LOG_FILE": str(plutil_log),
        },
        check=False,
    )

    assert result.returncode == 0, result.stderr
    combined = result.stdout + result.stderr
    # Early-exit message proves we hit the ready-rerun path, not Step 6.
    assert "already installed (phase=ready)" in combined
    # But cleanup ran BEFORE the exit.
    assert "cleanup: found stale" in combined
    # Step 6 (the main install path) did NOT run.
    assert "Step 6: install QA patrol LaunchAgent" not in combined

    # Plist file must be gone.
    assert not plist_path.exists(), (
        "ready-rerun upgrade path must remove stale plist even though "
        "ensure_host_deps exits early before Step 6"
    )

    # launchctl bootout was issued.
    launchctl_text = launchctl_log.read_text(encoding="utf-8") if launchctl_log.exists() else ""
    assert f"bootout gui/{os.getuid()}/com.clawseat.patrol55.patrol" in launchctl_text
