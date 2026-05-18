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
_read_jsonl = _HELPERS._read_jsonl


def _run_install(
    tmp_path: Path,
    *,
    dry_run: bool,
    pane_snapshots: list[str] | None = None,
    steady_pane_text: str | None = None,
) -> tuple[subprocess.CompletedProcess[str], Path, Path, Path, Path]:
    root, home, launcher_log, tmux_log, py_stubs = _fake_install_root(tmp_path)
    agent_admin_log = tmp_path / "agent_admin.jsonl"
    iterm_payload_log = tmp_path / "iterm_payload.jsonl"
    agentctl_log = tmp_path / "agentctl.log"
    pane_dir = tmp_path / "tmux-panes"
    brief_path = home / ".agents" / "tasks" / "kickoff50" / "patrol" / "handoffs" / "memory-bootstrap.md"
    if pane_snapshots is not None or steady_pane_text is not None:
        pane_dir.mkdir(parents=True, exist_ok=True)
        session_name = "kickoff50-memory-claude"
        for index, pane_text in enumerate(pane_snapshots or [], start=1):
            (pane_dir / f"{session_name}.{index}.txt").write_text(
                pane_text.replace("{BRIEF_PATH}", str(brief_path)),
                encoding="utf-8",
            )
        if steady_pane_text is not None:
            (pane_dir / f"{session_name}.txt").write_text(
                steady_pane_text.replace("{BRIEF_PATH}", str(brief_path)),
                encoding="utf-8",
            )
    args = ["bash", str(root / "scripts" / "install.sh")]
    if dry_run:
        args.append("--dry-run")
    args.extend([
        "--project",
        "kickoff50",
        "--template",
        "clawseat-creative",
        "--provider",
        "minimax",
    ])

    result = subprocess.run(
        args,
        input="" if dry_run else "\n",
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
            "AGENTCTL_LOG": str(agentctl_log),
            "TMUX_LOG_FILE": str(tmux_log),
            "AGENT_ADMIN_LOG": str(agent_admin_log),
            "ITERM_PAYLOAD_LOG": str(iterm_payload_log),
            "TMUX_PANE_DIR": str(pane_dir),
        },
        check=False,
    )
    return result, launcher_log, tmux_log, home, agentctl_log


def test_install_dry_run_does_not_send_phase_a_kickoff(tmp_path: Path) -> None:
    result, _, _, _, agentctl_log = _run_install(tmp_path, dry_run=True)

    combined = result.stdout + result.stderr
    assert result.returncode == 0, result.stderr
    assert "Step 9.5: auto-send Phase-A kickoff prompt" not in combined
    assert "读 " not in combined
    assert "spawn engineer seat 要 one-at-a-time" not in combined
    assert "IF ANCESTOR IS IDLE, COPY AND PASTE THIS:" not in combined
    assert not agentctl_log.exists()


def test_install_persists_phase_a_kickoff_after_tui_ready(tmp_path: Path) -> None:
    brief_stub = (
        "读 {BRIEF_PATH} 开始 Phase-A。"
        "按 brief 顺序执行 B0-B7，每步向我汇报或 CLI prompt 我确认。不要 fan-out specialist seat；"
        "spawn engineer seat 要 one-at-a-time。"
    )
    result, launcher_log, tmux_log, home, agentctl_log = _run_install(
        tmp_path,
        dry_run=False,
        pane_snapshots=[
            "",
            "Browser didn't open? Use the url below to sign in",
            "Type your message",
            brief_stub,
        ],
        steady_pane_text=brief_stub,
    )

    combined = result.stdout + result.stderr
    expected_brief = home / ".agents" / "tasks" / "kickoff50" / "patrol" / "handoffs" / "memory-bootstrap.md"
    kickoff_path = home / ".agents" / "tasks" / "kickoff50" / "patrol" / "handoffs" / "memory-kickoff.txt"
    guide_path = home / ".agents" / "tasks" / "kickoff50" / "OPERATOR-START-HERE.md"
    kickoff = (
        f"读 {expected_brief} 开始 Phase-A。按 brief 顺序执行 B0-B7，每步向我汇报或 CLI prompt 我确认。"
        "不要 fan-out specialist seat；spawn engineer seat 要 one-at-a-time。"
    )

    assert result.returncode == 0, result.stderr
    assert "Step 9.5: persist Phase-A kickoff prompt to memory-kickoff.txt" in combined
    assert "auto-send Phase-A kickoff prompt" not in combined
    assert "Phase-A kickoff delivered" not in combined
    assert "Phase-A kickoff submitted" not in combined
    assert "ClawSeat install complete / 安装已完成" in combined
    assert "Choose one to start Phase-A / 三选一启动 Phase-A" in combined
    assert str(kickoff_path) in combined
    assert expected_brief.is_file()
    assert kickoff_path.read_text(encoding="utf-8") == kickoff + "\n"
    assert guide_path.is_file()
    guide_text = guide_path.read_text(encoding="utf-8")
    assert "install.sh 不再自动发送 Phase-A kickoff" in guide_text
    assert str(kickoff_path) in guide_text
    assert not agentctl_log.exists()

    tmux_output = tmux_log.read_text(encoding="utf-8")
    assert "capture-pane -t =kickoff50-ancestor-claude" not in tmux_output
    assert "send-keys -l -t kickoff50-ancestor-claude" not in tmux_output

    records = _read_jsonl(launcher_log)
    assert [record["session"] for record in records] == ["kickoff50-memory-claude"]


def test_install_writes_operator_triggered_kickoff_without_auto_send(tmp_path: Path) -> None:
    result, _, tmux_log, home, _ = _run_install(
        tmp_path,
        dry_run=False,
        steady_pane_text="Quick safety check:",
    )

    combined = result.stdout + result.stderr
    expected_brief = home / ".agents" / "tasks" / "kickoff50" / "patrol" / "handoffs" / "memory-bootstrap.md"
    kickoff_path = home / ".agents" / "tasks" / "kickoff50" / "patrol" / "handoffs" / "memory-kickoff.txt"
    kickoff = (
        f"读 {expected_brief} 开始 Phase-A。按 brief 顺序执行 B0-B7，每步向我汇报或 CLI prompt 我确认。"
        "不要 fan-out specialist seat；spawn engineer seat 要 one-at-a-time。"
    )

    assert result.returncode == 0, result.stderr
    assert "Step 9.5: persist Phase-A kickoff prompt to memory-kickoff.txt" in combined
    assert "Auto-send could not verify kickoff delivery" not in combined
    assert "Phase-A kickoff auto-send skipped or failed" not in combined
    assert "ClawSeat install complete / 安装已完成" in combined
    assert str(kickoff_path) in combined
    assert kickoff_path.read_text(encoding="utf-8") == kickoff + "\n"

    tmux_output = tmux_log.read_text(encoding="utf-8")
    assert "capture-pane -t =kickoff50-ancestor-claude" not in tmux_output
    assert "send-keys -l -t kickoff50-ancestor-claude" not in tmux_output


def test_install_does_not_probe_spinner_before_operator_trigger(tmp_path: Path) -> None:
    result, _, tmux_log, home, _ = _run_install(
        tmp_path,
        dry_run=False,
        pane_snapshots=["Type your message"],
        steady_pane_text="✶ Whisking…",
    )

    combined = result.stdout + result.stderr

    assert result.returncode == 0, result.stderr
    assert "Step 9.5: persist Phase-A kickoff prompt to memory-kickoff.txt" in combined
    assert "auto-send Phase-A kickoff prompt" not in combined
    assert "Phase-A kickoff submitted" not in combined
    assert "Auto-send could not verify kickoff delivery" not in combined
    assert (
        home / ".agents" / "tasks" / "kickoff50" / "patrol" / "handoffs" / "memory-kickoff.txt"
    ).is_file()

    tmux_output = tmux_log.read_text(encoding="utf-8")
    assert "capture-pane -t =kickoff50-ancestor-claude" not in tmux_output
    assert "send-keys -l -t kickoff50-ancestor-claude" not in tmux_output
