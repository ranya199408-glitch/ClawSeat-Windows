"""C15: dispatch_task.py and complete_handoff.py notify-default-on tests.

Verifies:
- Default dispatch notifies (notified_at populated, notify_message non-null)
- --notify explicit behaves same as default
- --no-notify: notified_at null, notify_message null
- --skip-notify (legacy): same as --no-notify; stderr has deprecation warning
- --notify --no-notify: argparse rejects (mutually exclusive)
- complete_handoff.py parity: same three cases
- Profile heartbeat_transport variations: default notify works regardless
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
_SCRIPTS = _REPO / "core" / "skills" / "gstack-harness" / "scripts"

# ---------------------------------------------------------------------------
# Profile fixture helpers
# ---------------------------------------------------------------------------


def _make_profile(tmp_path: Path, seat: str = "builder-1", heartbeat_transport: str = "tmux") -> tuple[Path, Path, Path]:
    """Return (profile_path, todo_path, handoff_dir)."""
    tasks = tmp_path / "tasks"
    (tasks / seat).mkdir(parents=True)
    handoffs = tmp_path / "handoffs"
    handoffs.mkdir()
    ws = tmp_path / "workspaces"
    ws.mkdir()

    profile = tmp_path / "profile.toml"
    profile.write_text(
        f"""\
version = 1
profile_name = "test-profile"
template_name = "gstack-harness"
project_name = "test"
repo_root = "{tmp_path}"
tasks_root = "{tasks}"
workspace_root = "{ws}"
handoff_dir = "{handoffs}"
project_doc = "{tasks}/PROJECT.md"
tasks_doc = "{tasks}/TASKS.md"
status_doc = "{tasks}/STATUS.md"
send_script = "/bin/echo"
status_script = "/bin/echo"
patrol_script = "/bin/echo"
agent_admin = "/bin/echo"
heartbeat_receipt = "{ws}/koder/HEARTBEAT_RECEIPT.toml"
seats = ["planner", "{seat}"]
heartbeat_seats = []
active_loop_owner = "planner"
default_notify_target = "planner"
heartbeat_owner = "koder"
heartbeat_transport = "{heartbeat_transport}"

[seat_roles]
planner = "planner-dispatcher"
{seat} = "builder"

[dynamic_roster]
materialized_seats = ["planner", "{seat}"]
""",
        encoding="utf-8",
    )
    return profile, tasks / seat / "TODO.md", handoffs


def _dispatch_cmd(
    profile: Path,
    task_id: str,
    target: str = "builder-1",
    extra_flags: list[str] | None = None,
) -> subprocess.CompletedProcess:
    cmd = [
        sys.executable,
        str(_SCRIPTS / "dispatch_task.py"),
        "--profile", str(profile),
        "--source", "planner",
        "--target", target,
        "--task-id", task_id,
        "--title", f"test {task_id}",
        "--objective", "test objective",
        "--test-policy", "UPDATE",
        "--reply-to", "planner",
        *(extra_flags or []),
    ]
    return subprocess.run(cmd, capture_output=True, text=True)


def _complete_cmd(
    profile: Path,
    task_id: str,
    source: str = "builder-1",
    extra_flags: list[str] | None = None,
) -> subprocess.CompletedProcess:
    delivery = Path(profile).parent / "tasks" / source / "DELIVERY.md"
    delivery.parent.mkdir(parents=True, exist_ok=True)
    delivery.write_text(
        f"task_id: {task_id}\nowner: {source}\ntarget: planner\nstatus: completed\n\n# Delivery\nDone.\n",
        encoding="utf-8",
    )
    cmd = [
        sys.executable,
        str(_SCRIPTS / "complete_handoff.py"),
        "--profile", str(profile),
        "--source", source,
        "--target", "planner",
        "--task-id", task_id,
        "--summary", "done",
        "--frontstage-disposition", "USER_DECISION_NEEDED",
        *(extra_flags or []),
    ]
    return subprocess.run(cmd, capture_output=True, text=True)


def _load_dispatch_receipt(handoffs: Path, task_id: str, source: str = "planner", target: str = "builder-1") -> dict:
    matches = list(handoffs.glob(f"{task_id}__{source}__{target}.json"))
    if not matches:
        matches = list(handoffs.glob(f"{task_id}__*.json"))
    assert matches, f"no receipt found for {task_id} in {handoffs}"
    return json.loads(matches[0].read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# dispatch_task.py: default-on notify
# ---------------------------------------------------------------------------


def test_dispatch_default_notifies(tmp_path):
    """No flag given → receipt has notified_at populated."""
    profile, _, handoffs = _make_profile(tmp_path)
    result = _dispatch_cmd(profile, "D-NOTIFY-DEFAULT")
    assert result.returncode == 0, result.stderr
    receipt = _load_dispatch_receipt(handoffs, "D-NOTIFY-DEFAULT")
    assert receipt.get("notified_at") is not None, f"notified_at was null: {receipt}"
    assert receipt.get("notify_message") is not None


def test_dispatch_explicit_notify_flag(tmp_path):
    """--notify explicit behaves same as default."""
    profile, _, handoffs = _make_profile(tmp_path)
    result = _dispatch_cmd(profile, "D-NOTIFY-EXPLICIT", extra_flags=["--notify"])
    assert result.returncode == 0, result.stderr
    receipt = _load_dispatch_receipt(handoffs, "D-NOTIFY-EXPLICIT")
    assert receipt.get("notified_at") is not None


def test_dispatch_no_notify_suppresses(tmp_path):
    """--no-notify → receipt has notified_at=null, notify_message=null."""
    profile, _, handoffs = _make_profile(tmp_path)
    result = _dispatch_cmd(profile, "D-NO-NOTIFY", extra_flags=["--no-notify"])
    assert result.returncode == 0, result.stderr
    receipt = _load_dispatch_receipt(handoffs, "D-NO-NOTIFY")
    assert receipt.get("notified_at") is None, f"expected null notified_at: {receipt}"
    assert receipt.get("notify_message") is None


def test_dispatch_skip_notify_legacy(tmp_path):
    """--skip-notify (legacy) suppresses and emits deprecation warning on stderr."""
    profile, _, handoffs = _make_profile(tmp_path)
    result = _dispatch_cmd(profile, "D-SKIP-LEGACY", extra_flags=["--skip-notify"])
    assert result.returncode == 0, result.stderr
    receipt = _load_dispatch_receipt(handoffs, "D-SKIP-LEGACY")
    assert receipt.get("notified_at") is None, f"expected null notified_at: {receipt}"
    assert "deprecated" in result.stderr, f"expected deprecation warning in stderr: {result.stderr!r}"
    assert "--no-notify" in result.stderr


def test_dispatch_mutually_exclusive_notify_flags(tmp_path):
    """--notify --no-notify: argparse rejects with nonzero exit."""
    profile, _, _ = _make_profile(tmp_path)
    result = _dispatch_cmd(profile, "D-CONFLICT", extra_flags=["--notify", "--no-notify"])
    assert result.returncode != 0, "expected nonzero rc for mutually exclusive flags"


def test_dispatch_skip_notify_and_no_notify_together(tmp_path):
    """--skip-notify --no-notify: both set to 'off', no crash (rc=0)."""
    profile, _, handoffs = _make_profile(tmp_path)
    result = _dispatch_cmd(profile, "D-BOTH-OFF", extra_flags=["--skip-notify", "--no-notify"])
    assert result.returncode == 0, result.stderr
    receipt = _load_dispatch_receipt(handoffs, "D-BOTH-OFF")
    assert receipt.get("notified_at") is None


# ---------------------------------------------------------------------------
# complete_handoff.py: parity
# ---------------------------------------------------------------------------


def test_complete_default_notifies(tmp_path):
    """complete_handoff.py with no flag → notified_at populated."""
    profile, _, handoffs = _make_profile(tmp_path)
    # First dispatch so planner's TODO has the task
    _dispatch_cmd(profile, "C-DEFAULT", extra_flags=["--no-notify"])
    result = _complete_cmd(profile, "C-DEFAULT")
    assert result.returncode == 0, result.stderr
    receipt = _load_dispatch_receipt(handoffs, "C-DEFAULT", source="builder-1", target="planner")
    assert receipt.get("notified_at") is not None, f"notified_at was null: {receipt}"


def test_complete_no_notify_suppresses(tmp_path):
    """complete_handoff.py --no-notify → notified_at null."""
    profile, _, handoffs = _make_profile(tmp_path)
    _dispatch_cmd(profile, "C-NO-NOTIFY", extra_flags=["--no-notify"])
    result = _complete_cmd(profile, "C-NO-NOTIFY", extra_flags=["--no-notify"])
    assert result.returncode == 0, result.stderr
    receipt = _load_dispatch_receipt(handoffs, "C-NO-NOTIFY", source="builder-1", target="planner")
    assert receipt.get("notified_at") is None


def test_complete_skip_notify_legacy(tmp_path):
    """complete_handoff.py --skip-notify suppresses and warns."""
    profile, _, handoffs = _make_profile(tmp_path)
    _dispatch_cmd(profile, "C-SKIP-LEGACY", extra_flags=["--no-notify"])
    result = _complete_cmd(profile, "C-SKIP-LEGACY", extra_flags=["--skip-notify"])
    assert result.returncode == 0, result.stderr
    receipt = _load_dispatch_receipt(handoffs, "C-SKIP-LEGACY", source="builder-1", target="planner")
    assert receipt.get("notified_at") is None
    assert "deprecated" in result.stderr
    assert "--no-notify" in result.stderr


def test_complete_mutually_exclusive_flags(tmp_path):
    """complete_handoff.py --notify --no-notify rejected by argparse."""
    profile, _, _ = _make_profile(tmp_path)
    _dispatch_cmd(profile, "C-CONFLICT", extra_flags=["--no-notify"])
    result = _complete_cmd(profile, "C-CONFLICT", extra_flags=["--notify", "--no-notify"])
    assert result.returncode != 0


# ---------------------------------------------------------------------------
# Regression: heartbeat_transport variations should not suppress default notify
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("transport", ["tmux", "openclaw"])
def test_dispatch_default_notify_regardless_of_transport(tmp_path, transport):
    """Default notify fires regardless of heartbeat_transport value."""
    profile, _, handoffs = _make_profile(tmp_path, heartbeat_transport=transport)
    task_id = f"D-TRANSPORT-{transport or 'empty'}"
    result = _dispatch_cmd(profile, task_id)
    assert result.returncode == 0, result.stderr
    receipt = _load_dispatch_receipt(handoffs, task_id)
    assert receipt.get("notified_at") is not None, (
        f"notified_at was null with heartbeat_transport={transport!r}: {receipt}"
    )
