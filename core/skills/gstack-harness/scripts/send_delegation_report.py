#!/usr/bin/env python3
# Identity-aware delegation report sender.
#
# Supports lark-cli identity selection via `--as user|bot|auto`.
# - user: explicit user OAuth send
# - bot: explicit bot/app send
# - auto: omit `--as` and let lark-cli choose the active auth context
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys

from _common import (
    FeishuGroupResolutionError,
    _classify_send_failure,
    _lark_cli_cwd,
    _lark_cli_env,
    build_delegation_report_text,
    resolve_feishu_group_strict,
    run_command_with_env,
    stable_dispatch_nonce,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Send an OC_DELEGATION_REPORT_V1 message to Feishu with an explicit lark-cli identity."
    )
    parser.add_argument("--project", required=False, help="Project name.")
    parser.add_argument(
        "--lane",
        required=False,
        default="planning",
        help="Delegation lane: planning | builder | reviewer | patrol | designer | frontstage.",
    )
    parser.add_argument("--task-id", required=False, help="Task id.")
    parser.add_argument(
        "--dispatch-nonce",
        help="Stable nonce for the active delegation. Defaults to a hash of project/lane/task-id.",
    )
    parser.add_argument(
        "--report-status",
        required=False,
        default="in_progress",
        help="in_progress | done | needs_decision | blocked",
    )
    parser.add_argument(
        "--decision-hint",
        required=False,
        default="proceed",
        choices=["hold", "proceed", "ask_user", "retry", "escalate", "close"],
        help="hold | proceed | ask_user | retry | escalate | close",
    )
    parser.add_argument(
        "--user-gate",
        required=False,
        default="none",
        help="none | optional | required",
    )
    parser.add_argument(
        "--next-action",
        required=False,
        default="consume_closeout",
        help="wait | consume_closeout | ask_user | retry_current_lane | surface_blocker | finalize_chain",
    )
    parser.add_argument("--summary", required=False, default="(no summary)", help="Single-line machine-readable summary.")
    parser.add_argument(
        "--human-summary",
        help="Optional human-readable tail shown after the structured envelope.",
    )
    parser.add_argument("--chat-id", help="Feishu group chat id. Defaults to the configured primary group.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the formatted delegation report without sending it.",
    )
    parser.add_argument(
        "--check-auth",
        action="store_true",
        help="Only check lark-cli auth status and exit. No message is sent.",
    )
    parser.add_argument(
        "--as",
        dest="identity",
        choices=["user", "bot", "auto"],
        default="auto",
        help="lark-cli identity: user (OAuth) | bot (appSecret) | auto (default)",
    )
    return parser.parse_args()


def _read_lark_auth_status(
    lark_cli: str,
    *,
    identity: str,
) -> tuple[dict[str, str] | None, dict[str, str] | None]:
    cmd = [lark_cli]
    if identity != "auto":
        cmd.extend(["--as", identity])
    cmd.extend(["auth", "status"])
    result = run_command_with_env(
        cmd,
        cwd=_lark_cli_cwd(),
        env=_lark_cli_env(),
    )
    # Workaround for lark-cli versions that don't support `--as bot/user`.
    # If the flag is unknown, retry without it — lark-cli will default to bot.
    if result.returncode != 0 and identity != "auto" and "unknown flag" in result.stderr.lower():
        fallback_cmd = [lark_cli, "auth", "status"]
        result = run_command_with_env(
            fallback_cmd,
            cwd=_lark_cli_cwd(),
            env=_lark_cli_env(),
        )
    if result.returncode != 0:
        return None, {
            "status": "error",
            "reason": f"lark-cli auth status failed (rc={result.returncode}): {result.stderr.strip()}",
            "fix": "lark-cli auth login",
        }
    stdout = result.stdout.strip()
    try:
        auth_info = json.loads(stdout)
    except (TypeError, ValueError):
        return None, {
            "status": "error",
            "reason": f"unexpected lark-cli auth output: {stdout[:200]}",
            "fix": "lark-cli auth login",
        }
    if not isinstance(auth_info, dict):
        return None, {
            "status": "error",
            "reason": f"unexpected lark-cli auth output: {stdout[:200]}",
            "fix": "lark-cli auth login",
        }
    return auth_info, None


def _check_lark_auth(identity: str) -> dict[str, str]:
    lark_cli = shutil.which("lark-cli")
    if not lark_cli:
        return {
            "status": "missing",
            "reason": "lark-cli not found in PATH",
            "fix": "brew install larksuite/cli/lark-cli",
            "requested_as": identity,
        }
    auth_info, err = _read_lark_auth_status(lark_cli, identity=identity)
    if err is not None:
        err["requested_as"] = identity
        return err
    if auth_info is None:
        return {
            "status": "error",
            "reason": "lark-cli auth status returned no info",
            "fix": "lark-cli auth login",
            "requested_as": identity,
        }

    token_status = str(auth_info.get("tokenStatus", "unknown"))
    auth_identity = str(auth_info.get("identity", "unknown"))
    user_name = str(auth_info.get("userName", ""))
    if token_status == "valid":
        payload: dict[str, str] = {
            "status": "ok",
            "reason": "auth token is valid",
            "identity": auth_identity,
            "requested_as": identity,
        }
        if user_name:
            payload["userName"] = user_name
        return payload
    if token_status == "needs_refresh":
        payload = {
            "status": "ok",
            "reason": (
                "access_token expired; refresh_token still valid "
                "(lark-cli will auto-refresh on next API call)"
            ),
            "identity": auth_identity,
            "requested_as": identity,
            "warning": "needs_refresh",
        }
        if user_name:
            payload["userName"] = user_name
        return payload
    if token_status == "expired":
        return {
            "status": "expired",
            "reason": "refresh_token past 7d window (no calls for >7 days)",
            "fix": "lark-cli auth login  (in a terminal with a browser)",
            "identity": auth_identity,
            "requested_as": identity,
        }
    # Bot identity may not report tokenStatus at all; treat unknown as valid
    # when a confirmed bot identity is present.
    if auth_identity == "bot" and token_status == "unknown":
        return {
            "status": "ok",
            "reason": "bot identity confirmed (tokenStatus not applicable for bot)",
            "identity": auth_identity,
            "requested_as": identity,
        }
    return {
        "status": "error",
        "reason": f"unexpected token status: {token_status}",
        "fix": "lark-cli auth login",
        "identity": auth_identity,
        "requested_as": identity,
    }


def _send_feishu_message(
    message: str,
    *,
    group_id: str | None = None,
    project: str | None = None,
    identity: str,
    pre_check_auth: bool = False,
) -> dict[str, str]:
    payload: dict[str, str] = {"message": message.strip(), "requested_as": identity}
    resolved_source = "explicit:--chat-id" if group_id else ""
    resolved_group_id = (group_id or "").strip()
    if not resolved_group_id:
        try:
            resolved_group_id, resolved_source = resolve_feishu_group_strict(project or "")
        except FeishuGroupResolutionError as exc:
            payload["status"] = "failed"
            payload["reason"] = "no_project_binding"
            payload["detail"] = str(exc)
            payload["project"] = str(project or "")
            payload["attempted_sources"] = "|".join(exc.attempted_sources)
            payload["fix"] = (
                "pass --chat-id, set CLAWSEAT_FEISHU_GROUP_ID, or create "
                "~/.agents/tasks/<project>/PROJECT_BINDING.toml "
                "(C1 guardrail — refuse to guess group)"
            )
            return payload

    payload["group_id"] = resolved_group_id
    payload["group_source"] = resolved_source
    lark_cli = shutil.which("lark-cli")
    if not lark_cli:
        payload["status"] = "failed"
        payload["reason"] = "lark_cli_missing"
        payload["fix"] = "brew install larksuite/cli/lark-cli"
        return payload

    if pre_check_auth:
        auth = PLACEHOLDER(identity)
        if auth["status"] != "ok":
            payload["status"] = "failed"
            payload["reason"] = f"auth_{auth['status']}"
            payload["fix"] = auth.get("fix", "lark-cli auth login")
            payload["auth_detail"] = auth.get("reason", "")
            payload["auth_identity"] = auth.get("identity", "")
            payload["requested_as"] = identity
            return payload

    cmd = [lark_cli]
    if identity != "auto":
        cmd.extend(["--as", identity])
    cmd.extend(["im", "+messages-send"])
    cmd.extend(["--chat-id", resolved_group_id, "--text", message])
    result = run_command_with_env(
        cmd,
        cwd=_lark_cli_cwd(),
        env=_lark_cli_env(),
    )
    # Workaround for lark-cli versions that don't support `--as bot/user`.
    # If the flag is unknown, retry without it — lark-cli will default to bot.
    if result.returncode != 0 and identity != "auto" and "unknown flag" in result.stderr.lower():
        fallback_cmd = [lark_cli, "im", "+messages-send", "--chat-id", resolved_group_id, "--text", message]
        result = run_command_with_env(
            fallback_cmd,
            cwd=_lark_cli_cwd(),
            env=_lark_cli_env(),
        )
    payload["transport"] = f"lark-cli-{identity}"
    payload["returncode"] = str(result.returncode)
    if result.stdout.strip():
        payload["stdout"] = result.stdout.strip()
    if result.stderr.strip():
        payload["stderr"] = result.stderr.strip()
    if result.returncode == 0:
        payload["status"] = "sent"
    else:
        payload["status"] = "failed"
        reason, fix = _classify_send_failure(result.stderr)
        payload["reason"] = reason
        payload["fix"] = fix
    return payload


def main() -> int:
    args = parse_args()

    if os.environ.get("CLAWSEAT_FEISHU_ENABLED", "1") == "0":
        print(json.dumps({"status": "skipped", "reason": "CLAWSEAT_FEISHU_ENABLED=0"}, ensure_ascii=False), flush=True)
        return 0

    # Auth-check-only mode: verify lark-cli is available and auth is valid.
    if args.check_auth:
        result = _check_lark_auth(args.identity)
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 0 if result.get("status") == "ok" else 1

    # Normal send mode — only --project is required; all other fields have argparse defaults.
    if not args.project:
        print("error: --project is required when sending a delegation report", flush=True)
        return 2

    dispatch_nonce = args.dispatch_nonce or stable_dispatch_nonce(
        args.project,
        args.lane,
        args.task_id,
    )
    message = build_delegation_report_text(
        project=args.project,
        lane=args.lane,
        task_id=args.task_id,
        dispatch_nonce=dispatch_nonce,
        report_status=args.report_status,
        decision_hint=args.decision_hint,
        user_gate=args.user_gate,
        next_action=args.next_action,
        summary=args.summary,
        human_summary=args.human_summary,
    )
    # Resolve the target group up-front so dry-run AND real sends agree on
    # a single visible destination. Without --chat-id we do strict
    # resolution and refuse to continue on miss (C1 guardrail: never guess).
    if args.chat_id:
        resolved_group_id = args.chat_id.strip()
        resolved_source = "explicit:--chat-id"
    else:
        try:
            resolved_group_id, resolved_source = resolve_feishu_group_strict(args.project)
        except FeishuGroupResolutionError as exc:
            print(
                f"error: cannot resolve Feishu group for project={args.project!r}: {exc}",
                file=sys.stderr,
            )
            return 2

    print(
        f"delegation-report: project={args.project} -> group={resolved_group_id} "
        f"(source={resolved_source})",
        file=sys.stderr,
    )
    if args.dry_run:
        print(message)
        return 0

    result = _send_feishu_message(
        message,
        group_id=resolved_group_id,
        project=args.project,
        identity=args.identity,
        pre_check_auth=False,
    )
    # silent-ok audit: status≠sent returns exit 1, caller surfaces failure via return code
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result.get("status") == "sent" else 1


if __name__ == "__main__":
    raise SystemExit(main())
