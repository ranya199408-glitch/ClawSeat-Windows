#!/usr/bin/env python3
"""End-to-end smoke test for the gstack-harness dispatch + closeout flow.

Renders a synthetic profile in a throwaway tmpdir, then exercises dispatch
→ completion → ACK, canonical review-verdict enforcement, console rendering,
and the heartbeat-seat gate. Fails loudly on any shape drift so regressions
in the harness transport surface surface here before they hit a live project.
Run with no arguments to execute the full suite.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import tempfile
import sys
import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parent
REPO_ROOT = ROOT.parents[4]
# The checked-in REPO_ROOT resolves one level above the actual repo root in
# the standard checkout layout (ROOT.parents[3] is `…/ClawSeat`). The helper
# below is the only new consumer we add in this file, so we resolve the
# template path independently rather than risk shifting REPO_ROOT under the
# existing callers (pre-existing REPO_ROOT drift is out of scope for this
# change — see R2-TEMPLATE-001).
TEMPLATE_PATH = ROOT.parents[3] / "core" / "templates" / "gstack-harness" / "template.toml"


def template_engineers() -> list[dict[str, object]]:
    data = tomllib.loads(TEMPLATE_PATH.read_text(encoding="utf-8"))
    return [engineer for engineer in data.get("engineers", []) if isinstance(engineer, dict)]


def template_engineer_ids() -> list[str]:
    """Enumerate every engineer id declared in the canonical harness template.

    The selftest scaffolds one task dir per seat; enumerating from the template
    keeps this list in lockstep with the authoritative roster so a newly
    added engineer stanza (e.g. builder-2) never silently falls out of the
    self-test's setup path.
    """
    return [str(engineer["id"]) for engineer in template_engineers()]


def template_seat_roles() -> dict[str, str]:
    return {
        str(engineer["id"]): str(engineer.get("role", "specialist"))
        for engineer in template_engineers()
        if engineer.get("id")
    }


def template_heartbeat_owner() -> str:
    for engineer in template_engineers():
        if str(engineer.get("role", "")).strip() == "frontstage-supervisor":
            return str(engineer["id"])
    seats = template_engineer_ids()
    if not seats:
        raise RuntimeError(f"template has no engineers: {TEMPLATE_PATH}")
    return seats[0]


def run(*args: str, expect: int = 0, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)
    result = subprocess.run(
        [sys.executable, *args],
        text=True,
        capture_output=True,
        env=merged_env,
        check=False,
    )
    if result.returncode != expect:
        raise RuntimeError(
            f"command failed: {' '.join(args)}\n"
            f"exit={result.returncode}\n"
            f"stdout={result.stdout}\n"
            f"stderr={result.stderr}"
        )
    return result


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def main() -> int:
    temp_root = Path(tempfile.mkdtemp(prefix="gstack-harness-selftest-"))
    try:
        template_seats = template_engineer_ids()
        heartbeat_owner = template_heartbeat_owner()
        seat_roles = template_seat_roles()
        backend_seats = [seat for seat in template_seats if seat != heartbeat_owner]
        repo_root = temp_root / "repo"
        tasks_root = repo_root / ".tasks"
        handoff_dir = tasks_root / "patrol" / "handoffs"
        for seat in template_seats:
            (tasks_root / seat).mkdir(parents=True, exist_ok=True)
        handoff_dir.mkdir(parents=True, exist_ok=True)

        write(tasks_root / "PROJECT.md", "# Project\n")
        write(
            tasks_root / "TASKS.md",
            "# Tasks\n\n| ID | Title | Owner | Status | Notes |\n|----|-------|-------|--------|-------|\n",
        )
        write(tasks_root / "STATUS.md", "# Status\n")

        status_script = temp_root / "status.sh"
        write(
            status_script,
            "#!/bin/sh\n"
            "echo \"planner: WORKING\"\n"
            "echo \"reviewer-1: IDLE\"\n",
        )
        status_script.chmod(0o755)

        patrol_script = temp_root / "patrol.py"
        write(patrol_script, "print('no reminders')\n")

        heartbeat_receipt = temp_root / "workspaces" / "clawseat" / heartbeat_owner / "HEARTBEAT_RECEIPT.toml"
        write(heartbeat_receipt, "installed = true\n")

        openclaw_home = temp_root / ".openclaw"
        feishu_send_log = temp_root / "feishu-send.log"
        lark_cli_log = temp_root / "lark-cli.log"
        fake_bin = temp_root / "bin"
        fake_bin.mkdir(parents=True, exist_ok=True)
        feishu_send_script = (
            openclaw_home / "skills" / "claude-desktop" / "script" / "feishu-send.sh"
        )
        fake_lark_cli = fake_bin / "lark-cli"
        write(
            openclaw_home / "openclaw.json",
            json.dumps(
                {
                    "channels": {
                        "feishu": {
                            "defaultAccount": "main",
                            "groups": {
                                "<FEISHU_GROUP_ID>": {
                                    "requireMention": False,
                                    "tools": {"allow": ["group:openclaw"]},
                                }
                            },
                            "accounts": {
                                "main": {"groups": {"*": {"tools": {"allow": ["group:messaging"]}}}}
                            },
                        }
                    }
                },
                indent=2,
                ensure_ascii=False,
            ),
        )
        write(
            feishu_send_script,
            "#!/bin/sh\n"
            "printf '%s\\n' \"$*\" >> \"$FEISHU_SEND_LOG\"\n"
            "echo \"[feishu-send] OK → $2\"\n",
        )
        feishu_send_script.chmod(0o755)
        write(
            fake_lark_cli,
            "#!/bin/sh\n"
            "printf '%s\\n' \"$*\" >> \"$LARK_CLI_LOG\"\n"
            "if [ \"$1\" = \"auth\" ] && [ \"$2\" = \"status\" ]; then\n"
            "  cat <<'EOF'\n"
            "{\"identity\":\"user\",\"tokenStatus\":\"valid\",\"userName\":\"selftest\"}\n"
            "EOF\n"
            "  exit 0\n"
            "fi\n"
            "if [ \"$1\" = \"im\" ] && [ \"$2\" = \"+messages-send\" ]; then\n"
            "  cat <<'EOF'\n"
            "{\"status\":\"sent\",\"message_id\":\"message-id-selftest\"}\n"
            "EOF\n"
            "  exit 0\n"
            "fi\n"
            "echo \"unsupported fake lark-cli invocation: $*\" >&2\n"
            "exit 1\n",
        )
        fake_lark_cli.chmod(0o755)
        feishu_env = {
            "OPENCLAW_HOME": str(openclaw_home),
            "OPENCLAW_CONFIG_PATH": str(openclaw_home / "openclaw.json"),
            "CLAWSEAT_FEISHU_SEND_SH": str(feishu_send_script),
            "FEISHU_SEND_LOG": str(feishu_send_log),
            "AGENT_HOME": str(temp_root / "agent-home"),
            "PATH": f"{fake_bin}:{os.environ['PATH']}",
            "LARK_CLI_LOG": str(lark_cli_log),
        }

        profile = temp_root / "clawseat.toml"
        write(
            profile,
            "\n".join(
                [
                    'version = 1',
                    'profile_name = "clawseat-selftest"',
                    'template_name = "gstack-harness"',
                    'project_name = "clawseat-selftest"',
                    f'repo_root = "{repo_root}"',
                    f'tasks_root = "{tasks_root}"',
                    f'project_doc = "{tasks_root / "PROJECT.md"}"',
                    f'tasks_doc = "{tasks_root / "TASKS.md"}"',
                    f'status_doc = "{tasks_root / "STATUS.md"}"',
                    'send_script = "/usr/bin/true"',
                    f'status_script = "{status_script}"',
                    f'patrol_script = "{patrol_script}"',
                    f'agent_admin = "{REPO_ROOT / "core" / "scripts" / "agent_admin.py"}"',
                    f'workspace_root = "{temp_root / "workspaces" / "clawseat"}"',
                    f'handoff_dir = "{handoff_dir}"',
                    f'heartbeat_owner = "{heartbeat_owner}"',
                    'active_loop_owner = "planner"',
                    'default_notify_target = "planner"',
                    f'heartbeat_receipt = "{heartbeat_receipt}"',
                    f"seats = {json.dumps(template_seats)}",
                    f'heartbeat_seats = ["{heartbeat_owner}"]',
                    '',
                    '[seat_roles]',
                    *[
                        f'{seat} = "{role}"'
                        for seat, role in seat_roles.items()
                    ],
                    '',
                ]
            ),
        )

        workspace_root = temp_root / "workspaces" / "clawseat"
        frontstage_workspace = workspace_root / heartbeat_owner
        frontstage_workspace.mkdir(parents=True, exist_ok=True)
        write(
            frontstage_workspace / "WORKSPACE_CONTRACT.toml",
            "\n".join(
                [
                    'version = 1',
                    f'seat_id = "{heartbeat_owner}"',
                    'project = "clawseat-selftest"',
                    f'role = "{seat_roles[heartbeat_owner]}"',
                    'contract_fingerprint = "selftest-contract-fingerprint"',
                    "",
                ]
            ),
        )

        dispatch_task = ROOT / "dispatch_task.py"
        notify_seat = ROOT / "notify_seat.py"
        complete_handoff = ROOT / "complete_handoff.py"
        verify_handoff = ROOT / "verify_handoff.py"
        render_console = ROOT / "render_console.py"
        provision_heartbeat = ROOT / "provision_heartbeat.py"
        ack_contract = ROOT / "ack_contract.py"

        run(
            str(dispatch_task),
            "--profile",
            str(profile),
            "--source",
            "planner",
            "--target",
            "reviewer-1",
            "--task-id",
            "FE-SMOKE",
            "--title",
            "Smoke task",
            "--objective",
            "Review the change set",
            "--test-policy",
            "UPDATE",
            env=feishu_env,
        )
        todo_text = (tasks_root / "reviewer-1" / "TODO.md").read_text(encoding="utf-8")
        if "source: planner" not in todo_text or "reply_to: planner" not in todo_text:
            raise RuntimeError("dispatch TODO missing source/reply_to fields")
        dispatch_receipt = json.loads(
            (handoff_dir / "FE-SMOKE__planner__reviewer-1.json").read_text(encoding="utf-8")
        )
        if dispatch_receipt.get("feishu_group_broadcast", {}).get("reason") != "legacy_group_broadcast_disabled":
            raise RuntimeError("dispatch unexpectedly used the legacy Feishu group broadcast path")

        run(
            str(notify_seat),
            "--profile",
            str(profile),
            "--source",
            heartbeat_owner,
            "--target",
            "planner",
            "--task-id",
            "FE-NOTICE",
            "--kind",
            "unblock",
            "--reply-to",
            heartbeat_owner,
            "--message",
            "Resume the mainline and consume the repaired chain.",
        )
        notice_receipt = json.loads(
            (handoff_dir / f"FE-NOTICE__{heartbeat_owner}__planner.json").read_text(encoding="utf-8")
        )
        if notice_receipt["kind"] != "unblock":
            raise RuntimeError("notify_seat did not write the expected receipt kind")

        run(
            str(ack_contract),
            "--profile",
            str(profile),
            "--seat",
            heartbeat_owner,
            "--ack-source",
            "selftest",
        )
        contract_receipt = (frontstage_workspace / "WORKSPACE_CONTRACT_RECEIPT.toml").read_text(encoding="utf-8")
        if 'contract_fingerprint = "selftest-contract-fingerprint"' not in contract_receipt:
            raise RuntimeError("ack_contract missing contract fingerprint")
        if 'ack_source = "selftest"' not in contract_receipt:
            raise RuntimeError("ack_contract missing ack source")

        stale_dispatch = run(
            str(verify_handoff),
            "--profile",
            str(profile),
            "--task-id",
            "FE-OTHER",
            "--source",
            "planner",
            "--target",
            "reviewer-1",
            "--json",
            expect=1,
        )
        stale_dispatch_payload = json.loads(stale_dispatch.stdout)
        if stale_dispatch_payload["assigned"]:
            raise RuntimeError("verify_handoff incorrectly marked a stale dispatch as assigned")

        run(
            str(verify_handoff),
            "--profile",
            str(profile),
            "--task-id",
            "FE-SMOKE",
            "--source",
            "planner",
            "--target",
            "reviewer-1",
            expect=1,
        )

        missing_verdict = subprocess.run(
            [
                sys.executable,
                str(complete_handoff),
                "--profile",
                str(profile),
                "--source",
                "reviewer-1",
                "--target",
                "planner",
                "--task-id",
                "FE-SMOKE",
                "--title",
                "Review result",
                "--summary",
                "Looks good.",
            ],
            text=True,
            capture_output=True,
            check=False,
        )
        if missing_verdict.returncode == 0:
            raise RuntimeError("reviewer-1 completion unexpectedly succeeded without canonical verdict")

        run(
            str(complete_handoff),
            "--profile",
            str(profile),
            "--source",
            "reviewer-1",
            "--target",
            "planner",
            "--task-id",
            "FE-SMOKE",
            "--title",
            "Review result",
            "--summary",
            "Looks good.",
            "--verdict",
            "APPROVED",
            env=feishu_env,
        )
        delivery_text = (tasks_root / "reviewer-1" / "DELIVERY.md").read_text(encoding="utf-8")
        if "owner: reviewer-1" not in delivery_text or "target: planner" not in delivery_text:
            raise RuntimeError("delivery missing owner/target fields")

        missing_frontstage_disposition = subprocess.run(
            [
                sys.executable,
                str(complete_handoff),
                "--profile",
                str(profile),
                "--source",
                "planner",
                "--target",
                heartbeat_owner,
                "--task-id",
                "FE-CLOSEOUT",
                "--title",
                "Planner closeout",
                "--summary",
                "Chain is done.",
            ],
            text=True,
            capture_output=True,
            check=False,
        )
        if missing_frontstage_disposition.returncode == 0:
            raise RuntimeError("planner closeout unexpectedly succeeded without frontstage disposition")

        run(
            str(complete_handoff),
            "--profile",
            str(profile),
            "--source",
            "planner",
            "--target",
            heartbeat_owner,
            "--task-id",
            "FE-CLOSEOUT",
            "--title",
            "Planner closeout",
            "--summary",
            "Review and QA passed. We can keep moving.",
            "--frontstage-disposition",
            "AUTO_ADVANCE",
            "--user-summary",
            "Review and QA passed. We can keep moving.",
            env=feishu_env,
        )
        planner_delivery = (tasks_root / "planner" / "DELIVERY.md").read_text(encoding="utf-8")
        if "FrontstageDisposition: AUTO_ADVANCE" not in planner_delivery:
            raise RuntimeError("planner closeout missing FrontstageDisposition")
        if "UserSummary: Review and QA passed. We can keep moving." not in planner_delivery:
            raise RuntimeError("planner closeout missing UserSummary")
        frontstage_todo = (tasks_root / heartbeat_owner / "TODO.md").read_text(encoding="utf-8")
        if "## [pending] FE-CLOSEOUT" not in frontstage_todo:
            raise RuntimeError("planner closeout did not refresh frontstage TODO")
        if "reply_to: planner" not in frontstage_todo:
            raise RuntimeError("frontstage TODO missing reply_to for planner closeout")
        if "FrontstageDisposition: AUTO_ADVANCE" not in frontstage_todo:
            raise RuntimeError("frontstage TODO missing disposition summary")
        planner_receipt = json.loads(
            (handoff_dir / f"FE-CLOSEOUT__planner__{heartbeat_owner}.json").read_text(encoding="utf-8")
        )
        if planner_receipt.get("frontstage_disposition") != "AUTO_ADVANCE":
            raise RuntimeError("planner closeout receipt missing frontstage disposition")
        if "notify_message" not in planner_receipt:
            raise RuntimeError("planner closeout receipt missing notify evidence")
        if "todo_path" not in planner_receipt:
            raise RuntimeError("planner closeout receipt missing frontstage todo path")
        if planner_receipt.get("feishu_delegation_report", {}).get("status") != "sent":
            raise RuntimeError("planner closeout did not send OC_DELEGATION_REPORT_V1 successfully")
        if "feishu_group_broadcast" in planner_receipt:
            raise RuntimeError("planner closeout unexpectedly touched the legacy Feishu group broadcast path")
        if feishu_send_log.exists() and feishu_send_log.read_text(encoding="utf-8").strip():
            raise RuntimeError("legacy Feishu broadcast hook should be disabled by default")
        if not lark_cli_log.exists() or "--as user im +messages-send" not in lark_cli_log.read_text(encoding="utf-8"):
            raise RuntimeError("user-identity Feishu report did not invoke lark-cli as expected")

        run(
            str(verify_handoff),
            "--profile",
            str(profile),
            "--task-id",
            "FE-SMOKE",
            "--source",
            "reviewer-1",
            "--target",
            "planner",
            expect=1,
        )

        run(
            str(complete_handoff),
            "--profile",
            str(profile),
            "--source",
            "reviewer-1",
            "--target",
            "planner",
            "--task-id",
            "FE-SMOKE",
            "--ack-only",
        )

        healthy = run(
            str(verify_handoff),
            "--profile",
            str(profile),
            "--task-id",
            "FE-SMOKE",
            "--source",
            "reviewer-1",
            "--target",
            "planner",
            "--json",
        )
        heartbeat_skip = run(
            str(provision_heartbeat),
            "--profile",
            str(profile),
            "--seat",
            "planner",
            "--dry-run",
        )
        console = run(str(render_console), "--profile", str(profile), "--json")
        console_payload = json.loads(console.stdout)
        if console_payload["heartbeat"]["configured"]:
            raise RuntimeError("render_console incorrectly treated an unverified heartbeat receipt as configured")
        if console_payload.get("seat_sets", {}).get("roster") != template_seats:
            raise RuntimeError("render_console seat_sets.roster drifted from the expected roster")
        if console_payload.get("seat_sets", {}).get("backend") != backend_seats:
            raise RuntimeError("render_console seat_sets.backend drifted from the expected backend seats")
        if console_payload.get("seat_sets", {}).get("default_start") != [
            heartbeat_owner,
        ]:
            raise RuntimeError("render_console seat_sets.default_start drifted from the expected autostart view")
        for seat in template_seats:
            todo_path = tasks_root / seat / "TODO.md"
            if not todo_path.exists():
                raise RuntimeError(f"materialize_profile_runtime did not seed TODO for {seat}")

        result = {
            "temp_root": str(temp_root),
            "healthy_handoff": json.loads(healthy.stdout),
            "heartbeat_skip": heartbeat_skip.stdout.strip(),
            "console": console_payload,
            "missing_verdict_error": (missing_verdict.stderr or missing_verdict.stdout).strip(),
            "missing_frontstage_disposition_error": (
                missing_frontstage_disposition.stderr or missing_frontstage_disposition.stdout
            ).strip(),
            "notice_receipt": notice_receipt,
            "dispatch_todo": todo_text,
            "delivery_text": delivery_text,
            "planner_delivery": planner_delivery,
        }
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


def parse_args() -> argparse.Namespace:
    """Minimal argparse layer so `--help` / `-h` short-circuit before main().

    The selftest itself takes no flags today; this parser exists only to
    surface usage text and avoid tripping the full harness smoke run (which
    depends on lark-cli auth + Feishu binding) just to read docs.
    """
    parser = argparse.ArgumentParser(
        description=(
            "Self-test the gstack-harness dispatch + closeout flow against a "
            "synthetic profile. No flags — running with no arguments executes "
            "the full suite."
        ),
    )
    return parser.parse_args()


if __name__ == "__main__":
    parse_args()  # consumes --help / -h before main() can crash on env deps
    raise SystemExit(main())
