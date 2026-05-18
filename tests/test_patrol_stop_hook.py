from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path


_REPO = Path(__file__).resolve().parents[1]
_HOOK = _REPO / "core" / "skills" / "patrol" / "scripts" / "hooks" / "patrol-stop-hook.sh"


def _write_feishu(tmp_path: Path) -> tuple[Path, Path]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "feishu.log"
    feishu = bin_dir / "feishu"
    feishu.write_text(
        "#!/usr/bin/env bash\nprintf '%s\\n' \"$*\" >> \"$FEISHU_LOG\"\n",
        encoding="utf-8",
    )
    feishu.chmod(0o755)
    return bin_dir, log


def _run_hook(tmp_path: Path, message: str) -> tuple[subprocess.CompletedProcess[str], Path]:
    bin_dir, log = _write_feishu(tmp_path)
    env = os.environ.copy()
    env.update({"PATH": f"{bin_dir}:{env.get('PATH', '')}", "FEISHU_LOG": str(log), "HOME": str(tmp_path)})
    payload = {"last_assistant_message": message, "hook_event_name": "Stop"}
    proc = subprocess.run(
        ["bash", str(_HOOK)],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        env=env,
        cwd=_REPO,
        check=False,
    )
    return proc, log


def test_marker_detection_valid(tmp_path: Path) -> None:
    proc, log = _run_hook(
        tmp_path,
        "[PATROL-NOTIFY:project=install,scope=patrol,high=1,medium=2,low=3]",
    )
    assert proc.returncode == 0
    assert "high=1 medium=2 low=3" in log.read_text(encoding="utf-8")


def test_marker_detection_missing(tmp_path: Path) -> None:
    proc, log = _run_hook(tmp_path, "nothing to notify")
    assert proc.returncode == 0
    assert not log.exists()


def test_marker_malformed_returns_zero(tmp_path: Path) -> None:
    proc, log = _run_hook(tmp_path, "[PATROL-NOTIFY:project=install,badtoken]")
    assert proc.returncode == 0
    assert not log.exists()


def test_summary_card_path_resolution(tmp_path: Path) -> None:
    summary = tmp_path / ".agents" / "memory" / "projects" / "install" / "patrol" / "_summary.md"
    summary.parent.mkdir(parents=True)
    summary.write_text("# QA Summary\nAll clear.\n", encoding="utf-8")
    proc, log = _run_hook(
        tmp_path,
        "[QA-NOTIFY:project=install,scope=test,high=0,medium=0,low=1]",
    )
    assert proc.returncode == 0
    assert "QA Summary" in log.read_text(encoding="utf-8")


def test_marker_includes_session_and_project(tmp_path: Path) -> None:
    proc, log = _run_hook(
        tmp_path,
        "[PATROL-NOTIFY:project=install,scope=patrol,high=0,medium=0,low=0]",
    )
    text = log.read_text(encoding="utf-8")
    assert proc.returncode == 0
    assert "[PATROL scope=patrol]" in text
    assert "_via Patrol @" in text
    assert "project=install" in text
    assert "session=" in text
