#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from _common import (
    HarnessProfile,
    load_profile,
    load_toml,
    notify,
    read_text,
    run_command,
    utc_now_iso,
)


VALID_STALL_STATES = {"STALLED", "BLOCKED", "DECISION_NEEDED", "DRIFT", "CRASHED"}
RESOURCE_BLOCK_REASONS = {"usage_limit", "capacity"}
LEARNING_COOLDOWN_SECONDS = 12 * 60 * 60


@dataclass
class SeatSnapshot:
    seat: str
    status: str
    detail: str
    todo_path: Path
    delivery_path: Path
    todo_task_id: str | None
    delivery_task_id: str | None


def normalize_detail(detail: str) -> str:
    cleaned = detail.strip()
    if cleaned.startswith("(") and cleaned.endswith(")"):
        cleaned = cleaned[1:-1].strip()
    return cleaned.replace(" ", "_").lower()


def status_label(snapshot: SeatSnapshot) -> str:
    if snapshot.detail:
        return f"{snapshot.status} {snapshot.detail}".strip()
    return snapshot.status


def patrol_learning_log(profile: HarnessProfile) -> Path:
    return profile.tasks_root / "patrol" / "learnings.jsonl"


def patrol_learning_state(profile: HarnessProfile) -> Path:
    return profile.tasks_root / "patrol" / "learnings_state.json"


def load_learning_state(profile: HarnessProfile) -> dict[str, float]:
    path = patrol_learning_state(profile)
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        return {}
    if not isinstance(payload, dict):
        return {}
    state: dict[str, float] = {}
    for key, value in payload.items():
        try:
            state[str(key)] = float(value)
        except (TypeError, ValueError):
            continue
    return state


def write_learning_state(profile: HarnessProfile, state: dict[str, float]) -> None:
    path = patrol_learning_state(profile)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def record_learning(
    profile: HarnessProfile,
    *,
    kind: str,
    seat: str,
    task_id: str | None,
    status: str,
    detail: str,
    lesson: str,
    recommendation: str,
    evidence: str,
) -> bool:
    fingerprint_basis = {
        "kind": kind,
        "project": profile.project_name,
        "seat": seat,
        "task_id": task_id or "",
        "status": status,
        "detail": detail,
        "lesson": lesson,
    }
    fingerprint = hashlib.sha256(
        json.dumps(fingerprint_basis, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()[:16]
    now = time.time()
    state = load_learning_state(profile)
    last_seen = state.get(fingerprint)
    if last_seen is not None and now - last_seen < LEARNING_COOLDOWN_SECONDS:
        return False

    entry = {
        "timestamp": utc_now_iso(),
        "fingerprint": fingerprint,
        "project": profile.project_name,
        "kind": kind,
        "seat": seat,
        "task_id": task_id,
        "status": status,
        "detail": detail,
        "lesson": lesson,
        "recommendation": recommendation,
        "evidence": evidence,
    }
    log_path = patrol_learning_log(profile)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")
    state[fingerprint] = now
    write_learning_state(profile, state)
    return True


def blocker_guidance(snapshot: SeatSnapshot, *, active_owner: bool) -> str | None:
    reason = normalize_detail(snapshot.detail)
    if reason == "usage_limit":
        if active_owner:
            return "检测到额度/订阅阻塞；若无法立即恢复，应升级给用户并考虑改派或切换 provider/model。"
        return "检测到额度/订阅阻塞；请优先判断是等待额度恢复、改派，还是切换 provider/model。"
    if reason == "capacity":
        if active_owner:
            return "检测到容量阻塞；若短时不恢复，应调整队列或升级给用户。"
        return "检测到容量阻塞；请优先决定是等待恢复、重发，还是改派。"
    return None


def collect_learning_notes(
    profile: HarnessProfile,
    snapshots: dict[str, SeatSnapshot],
    task_statuses: dict[str, str],
) -> list[str]:
    notes: list[str] = []
    for seat, snapshot in snapshots.items():
        reason = normalize_detail(snapshot.detail)
        active_task_id = snapshot.todo_task_id or snapshot.delivery_task_id

        if snapshot.status == "BLOCKED" and reason in RESOURCE_BLOCK_REASONS and not should_ignore(
            snapshot.todo_task_id,
            task_statuses,
        ):
            learned = record_learning(
                profile,
                kind="resource_blocker",
                seat=seat,
                task_id=active_task_id,
                status=snapshot.status,
                detail=reason,
                lesson=(
                    f"{seat} 命中 {reason} 会直接打断任务链，巡检不应把它当作普通 stalled/idle。"
                ),
                recommendation="优先改派、rebind provider/model，或明确等待额度/容量恢复。",
                evidence=status_label(snapshot),
            )
            if learned:
                notes.append(
                    f"- 新经验教训已记录：{seat} 命中 {reason} 会直接打断任务链，后续巡检应优先建议改派/rebind/等待恢复。"
                )

        if should_ignore(snapshot.todo_task_id, task_statuses) and snapshot.status in VALID_STALL_STATES:
            learned = record_learning(
                profile,
                kind="stale_state_after_completion",
                seat=seat,
                task_id=snapshot.todo_task_id,
                status=snapshot.status,
                detail=reason,
                lesson="当 TASKS.md 已 completed 时，巡检应优先相信 durable task facts，而不是陈旧 pane 状态。",
                recommendation="优先检查 TASKS.md / Consumed ACK，再决定是否继续催办。",
                evidence=status_label(snapshot),
            )
            if learned:
                notes.append(
                    f"- 新经验教训已记录：{seat} 的 pane 状态与 completed 事实冲突；以后应优先相信 durable docs。"
                )

        if snapshot.status == "DELIVERED" and snapshot.delivery_task_id:
            acked = consumed_ack_exists(profile, task_id=snapshot.delivery_task_id, source=seat)
            if acked:
                learned = record_learning(
                    profile,
                    kind="stale_delivery_after_ack",
                    seat=seat,
                    task_id=snapshot.delivery_task_id,
                    status=snapshot.status,
                    detail=reason,
                    lesson="当 planner 已写 durable Consumed ACK 时，不应再把 delivered seat 视为待催办。",
                    recommendation="优先读取 active loop owner 的 TODO/Consumed 记录，再决定是否提醒。",
                    evidence=status_label(snapshot),
                )
                if learned:
                    notes.append(
                        f"- 新经验教训已记录：{seat} 的 delivery 已被 durable ACK；后续巡检不应重复催消费。"
                    )
    return notes


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generic patrol supervisor for gstack-harness profiles.")
    parser.add_argument("--profile", required=True, help="Path to the project profile TOML.")
    parser.add_argument("--send", action="store_true", help="Send reminders to the active loop owner.")
    parser.add_argument("--force", action="store_true", help="Bypass cooldown suppression.")
    parser.add_argument("--delivered-threshold-minutes", type=int, default=30)
    parser.add_argument("--stalled-threshold-minutes", type=int, default=20)
    parser.add_argument("--cooldown-minutes", type=int, default=60)
    return parser.parse_args()


def read_task_id(path: Path) -> str | None:
    if not path.exists():
        return None
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("task_id:"):
            return line.split(":", 1)[1].strip() or None
    return None


def file_age_minutes(path: Path) -> int:
    if not path.exists():
        return 0
    return int(max(0, time.time() - path.stat().st_mtime) // 60)


def load_task_statuses(profile: HarnessProfile) -> dict[str, str]:
    statuses: dict[str, str] = {}
    if not profile.tasks_doc.exists():
        return statuses
    for line in profile.tasks_doc.read_text(encoding="utf-8").splitlines():
        if not line.startswith("|") or line.startswith("| ID ") or line.startswith("|----"):
            continue
        parts = [part.strip() for part in line.strip().strip("|").split("|")]
        if len(parts) < 4:
            continue
        task_id, _, _, status = parts[:4]
        statuses[task_id] = status.lower()
    return statuses


def run_status(profile: HarnessProfile) -> list[str]:
    result = subprocess.run(
        [str(profile.status_script)],
        cwd=str(profile.repo_root),
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "status script failed")
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def parse_status(profile: HarnessProfile, lines: list[str]) -> dict[str, SeatSnapshot]:
    snapshots: dict[str, SeatSnapshot] = {}
    for line in lines:
        if ":" not in line:
            continue
        seat, rest = line.split(":", 1)
        seat = seat.strip()
        if seat not in profile.seats:
            continue
        parts = rest.strip().split(" ", 1)
        status = parts[0].strip()
        detail = parts[1].strip() if len(parts) > 1 else ""
        todo_path = profile.todo_path(seat)
        delivery_path = profile.delivery_path(seat)
        snapshots[seat] = SeatSnapshot(
            seat=seat,
            status=status,
            detail=detail,
            todo_path=todo_path,
            delivery_path=delivery_path,
            todo_task_id=read_task_id(todo_path),
            delivery_task_id=read_task_id(delivery_path),
        )
    return snapshots


def should_ignore(task_id: str | None, task_statuses: dict[str, str]) -> bool:
    if not task_id:
        return True
    return task_statuses.get(task_id) == "completed"


def consumed_ack_exists(profile: HarnessProfile, *, task_id: str, source: str) -> bool:
    todo_text = read_text(profile.todo_path(profile.active_loop_owner))
    needle = f"Consumed: {task_id} from {source} at"
    return needle in todo_text


def build_reminders(
    profile: HarnessProfile,
    snapshots: dict[str, SeatSnapshot],
    task_statuses: dict[str, str],
    *,
    delivered_threshold: int,
    stalled_threshold: int,
) -> tuple[list[str], list[str]]:
    reminders: list[str] = []
    notes: list[str] = []
    for seat, snapshot in snapshots.items():
        if seat == profile.active_loop_owner:
            if should_ignore(snapshot.todo_task_id, task_statuses):
                continue
            age = file_age_minutes(snapshot.todo_path)
            if snapshot.status in VALID_STALL_STATES and (
                snapshot.status in {"BLOCKED", "DECISION_NEEDED", "CRASHED"} or age >= stalled_threshold
            ):
                task_id = snapshot.todo_task_id or "unknown-task"
                guidance = blocker_guidance(snapshot, active_owner=True)
                message = f"- {seat} 当前为 {status_label(snapshot)}，active TODO={task_id}，已挂起约 {age} 分钟。"
                if guidance:
                    message += guidance
                else:
                    message += "请先消费当前链路并写出下一跳。"
                reminders.append(message)
            continue

        if snapshot.delivery_task_id and not should_ignore(snapshot.delivery_task_id, task_statuses):
            acked = consumed_ack_exists(profile, task_id=snapshot.delivery_task_id, source=seat)
            age = file_age_minutes(snapshot.delivery_path)
            if snapshot.status == "DELIVERED" and not acked and age >= delivered_threshold:
                reminders.append(
                    f"- {seat} 已交付 {snapshot.delivery_task_id}，但 `{profile.active_loop_owner}` 还未写 durable Consumed ACK，已等待约 {age} 分钟。请阅读 DELIVERY.md 并决定下一跳。"
                )
                continue
            if snapshot.status == "DELIVERED" and acked:
                notes.append(f"- {seat} 的交付 {snapshot.delivery_task_id} 已被 `{profile.active_loop_owner}` durable ACK。")
                continue

        if snapshot.status in VALID_STALL_STATES and not should_ignore(snapshot.todo_task_id, task_statuses):
            age = file_age_minutes(snapshot.todo_path)
            if snapshot.status in {"BLOCKED", "DECISION_NEEDED"} or age >= stalled_threshold:
                task_id = snapshot.todo_task_id or "unknown-task"
                guidance = blocker_guidance(snapshot, active_owner=False)
                message = f"- {seat} 当前为 {status_label(snapshot)}，TODO={task_id} 已挂起约 {age} 分钟。"
                if guidance:
                    message += guidance
                else:
                    message += "请确认是否需要重发、改派或继续推进。"
                reminders.append(message)
    return reminders, notes


def state_file(profile: HarnessProfile) -> Path:
    return profile.tasks_root / "patrol" / "frontstage_reminder_state.txt"


def should_suppress(profile: HarnessProfile, payload: str, cooldown_minutes: int, *, force: bool) -> bool:
    if force:
        return False
    path = state_file(profile)
    if not path.exists():
        return False
    try:
        last_ts_raw, last_payload = path.read_text(encoding="utf-8").split("\n", 1)
        last_ts = float(last_ts_raw.strip())
    except (ValueError, OSError, UnicodeDecodeError):
        return False
    if time.time() - last_ts > cooldown_minutes * 60:
        return False
    return last_payload.strip() == payload.strip()


def record_payload(profile: HarnessProfile, payload: str) -> None:
    path = state_file(profile)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"{time.time()}\n{payload}\n", encoding="utf-8")


_CONTEXT_THRESHOLD = 0.80


def check_context_near_limit(profile: HarnessProfile) -> list[str]:
    """Scan heartbeat receipts for seats approaching context limit.

    Emits seat.context_near_limit events via state.db when pct >= 0.80.
    Returns warning lines for the patrol payload (never raises).
    """
    warnings: list[str] = []
    for seat in profile.seats:
        receipt_path = profile.heartbeat_receipt_for(seat)
        if not receipt_path.exists():
            continue
        receipt = load_toml(receipt_path)
        if not receipt:
            continue
        raw_pct = receipt.get("token_usage_pct")
        if raw_pct is None:
            continue
        try:
            pct = float(raw_pct)
        except (TypeError, ValueError):
            continue
        if pct < _CONTEXT_THRESHOLD:
            continue
        source = str(receipt.get("token_usage_source", "unknown"))
        measured_at = str(receipt.get("token_usage_measured_at", ""))
        try:
            from core.lib.state import open_db, record_event  # noqa: PLC0415
            with open_db() as conn:
                record_event(
                    conn,
                    "seat.context_near_limit",
                    profile.project_name,
                    seat=seat,
                    pct=pct,
                    source=source,
                    measured_at=measured_at,
                    receipt_path=str(receipt_path),
                )
        except Exception as exc:
            print(
                f"warn: state.db unavailable for seat.context_near_limit event: {exc}",
                file=sys.stderr,
            )
        pct_pct = int(pct * 100)
        warnings.append(
            f"- {seat} context 使用率约 {pct_pct}%（来源：{source}），接近上限。建议检查是否需要 /clear 或 swap session。"
        )
    return warnings


def main() -> int:
    args = parse_args()
    profile = load_profile(args.profile)
    lines = run_status(profile)
    snapshots = parse_status(profile, lines)
    task_statuses = load_task_statuses(profile)
    learning_notes = collect_learning_notes(profile, snapshots, task_statuses)
    context_warnings = check_context_near_limit(profile)
    reminders, notes = build_reminders(
        profile,
        snapshots,
        task_statuses,
        delivered_threshold=args.delivered_threshold_minutes,
        stalled_threshold=args.stalled_threshold_minutes,
    )
    notes = learning_notes + notes
    reminders = context_warnings + reminders
    if not reminders:
        if notes:
            print("\n".join(notes))
        print("HEARTBEAT_OK")
        return 0

    payload = (
        "监督提醒：\n"
        f"检测到项目 `{profile.project_name}` 的 active loop 需要你处理。\n\n"
        + "\n".join(reminders)
    )
    if notes:
        payload += "\n\n观察备注：\n" + "\n".join(notes)

    if should_suppress(profile, payload, args.cooldown_minutes, force=args.force):
        print("HEARTBEAT_OK")
        return 0

    if args.send:
        result = notify(profile, profile.active_loop_owner, payload)
        if result.returncode != 0:
            print(result.stderr.strip() or result.stdout.strip() or "send failed", file=sys.stderr)
            return result.returncode or 1
        record_payload(profile, payload)
        print(f"reminded {profile.active_loop_owner}")
        return 0

    print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
