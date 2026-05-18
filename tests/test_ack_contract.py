from __future__ import annotations

import subprocess
import sys
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
ACK_CONTRACT = REPO / "core" / "skills" / "gstack-harness" / "scripts" / "ack_contract.py"


def _make_profile(tmp_path: Path) -> tuple[Path, Path]:
    tasks_root = tmp_path / "tasks" / "test-project"
    workspace_root = tmp_path / "workspaces" / "test-project"
    handoff_dir = tasks_root / "patrol" / "handoffs"
    for seat in ("planner", "builder"):
        (tasks_root / seat).mkdir(parents=True, exist_ok=True)
        (workspace_root / seat).mkdir(parents=True, exist_ok=True)
    profile = tmp_path / "profile.toml"
    profile.write_text(
        "\n".join(
            [
                'version = 1',
                'profile_name = "test-profile"',
                'template_name = "gstack-harness"',
                'project_name = "test-project"',
                f'repo_root = "{REPO}"',
                f'tasks_root = "{tasks_root}"',
                f'project_doc = "{tasks_root / "PROJECT.md"}"',
                f'tasks_doc = "{tasks_root / "TASKS.md"}"',
                f'status_doc = "{tasks_root / "STATUS.md"}"',
                f'send_script = "{REPO / "core" / "shell-scripts" / "send-and-verify.sh"}"',
                f'status_script = "{tasks_root / "patrol" / "check-status.sh"}"',
                f'patrol_script = "{tasks_root / "patrol" / "patrol-supervisor.sh"}"',
                f'agent_admin = "{REPO / "core" / "scripts" / "agent_admin.py"}"',
                f'workspace_root = "{workspace_root}"',
                f'handoff_dir = "{handoff_dir}"',
                'heartbeat_owner = "koder"',
                'active_loop_owner = "planner"',
                'default_notify_target = "planner"',
                f'heartbeat_receipt = "{workspace_root / "koder" / "HEARTBEAT_RECEIPT.toml"}"',
                'seats = ["planner", "builder"]',
                'heartbeat_seats = []',
                '',
                '[seat_roles]',
                'planner = "planner-dispatcher"',
                'builder = "builder"',
                '',
            ]
        ),
        encoding="utf-8",
    )
    return profile, workspace_root


def test_ack_contract_writes_receipt(tmp_path: Path) -> None:
    profile, workspace_root = _make_profile(tmp_path)
    seat = "builder"
    contract_path = workspace_root / seat / "WORKSPACE_CONTRACT.toml"
    contract_path.write_text(
        'version = 1\ncontract_fingerprint = "fingerprint-123"\n',
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            str(ACK_CONTRACT),
            "--profile",
            str(profile),
            "--seat",
            seat,
            "--ack-source",
            "unit-test",
            "--note",
            "checked",
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    receipt_path = workspace_root / seat / "WORKSPACE_CONTRACT_RECEIPT.toml"
    assert receipt_path.exists()
    body = receipt_path.read_text(encoding="utf-8")
    assert 'seat_id = "builder"' in body
    assert 'project = "test-project"' in body
    assert 'contract_fingerprint = "fingerprint-123"' in body
    assert 'ack_source = "unit-test"' in body
    assert 'status = "acknowledged"' in body
