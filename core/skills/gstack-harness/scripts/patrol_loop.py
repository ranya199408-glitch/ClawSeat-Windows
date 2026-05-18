#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from _common import executable_command, load_profile, materialize_profile_runtime, require_success, run_command
import tomllib


MAX_REWAKES_PER_CYCLE = 5
STALE_THRESHOLD_HOURS = 6
AUTO_SUPERSEDE_AGE_DAYS = 3
REWAKE_COOLDOWN_SECONDS = 21600
SEAT_HEALTH_THRESHOLD_SECONDS = 10 * 60


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the patrol loop for a project profile.")
    parser.add_argument("--profile", required=True, help="Path to the project profile TOML.")
    parser.add_argument("--send", action="store_true", help="Allow reminders to be sent.")
    parser.add_argument(
        "--stale-threshold-hours",
        type=int,
        default=STALE_THRESHOLD_HOURS,
        help="Age in hours before a handoff is considered stale.",
    )
    parser.add_argument(
        "--auto-supersede-age-days",
        type=int,
        default=AUTO_SUPERSEDE_AGE_DAYS,
        help="Age in days before auto-supersede runs.",
    )
    parser.add_argument(
        "--rewake-cooldown-seconds",
        type=int,
        default=REWAKE_COOLDOWN_SECONDS,
        help="Cooldown in seconds before the same stale handoff can be rewoken again.",
    )
    return parser.parse_args()


def run_auto_supersede(profile, *, age_days: int = AUTO_SUPERSEDE_AGE_DAYS) -> None:
    cmd = [
        sys.executable,
        str(profile.agent_admin),
        "task",
        "auto-supersede",
        "--project",
        profile.project_name,
        "--age-days",
        str(age_days),
    ]
    result = run_command(cmd, cwd=profile.repo_root)
    if result.stdout.strip():
        print(result.stdout.strip())
    if result.returncode != 0:
        stderr = result.stderr.strip()
        suffix = f": {stderr}" if stderr else ""
        print(f"warn: task auto-supersede failed{suffix}", file=sys.stderr)


def _tasks_root() -> Path:
    return Path.home() / ".agents" / "tasks"


def _rewake_log_path() -> Path:
    return Path.home() / ".agents" / "logs" / "stale-handoff-rewake.log"


def _seat_unblock_log_path() -> Path:
    return Path.home() / ".agents" / "logs" / "seat-unblock.log"


def _append_seat_unblock_log(
    *,
    project: str,
    seat: str,
    session: str,
    task_id: str,
    action: str,
    reason: str,
    age_seconds: int | None = None,
) -> None:
    log_path = _seat_unblock_log_path()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {
        "ts": time.time(),
        "project": project,
        "seat": seat,
        "session": session,
        "task_id": task_id,
        "action": action,
        "reason": reason,
    }
    if age_seconds is not None:
        payload["age_seconds"] = age_seconds
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def _capture_pane_tail(target: str) -> tuple[bool, str]:
    result = subprocess.run(
        ["tmux", "capture-pane", "-t", target, "-p"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return False, "capture-pane failed"
    tail = "\n".join(result.stdout.splitlines()[-3:]).strip()
    return True, tail


def _tail_busy_reason(tail_text: str) -> tuple[bool, str]:
    if not tail_text:
        return False, "idle"
    if "background terminal running" in tail_text:
        return False, "background terminal running"
    if "Working" in tail_text or "Thinking" in tail_text or "• " in tail_text:
        return True, tail_text
    return False, "idle"


def _seat_blocked_for(target: str, threshold_seconds: int = 600) -> tuple[bool, str]:
    ok, tail_text = _capture_pane_tail(target)
    if not ok:
        return False, tail_text
    blocked, reason = _tail_busy_reason(tail_text)
    if not blocked:
        return False, reason
    return True, reason


def _load_project_engineers(project: str) -> list[str]:
    project_toml = Path.home() / ".agents" / "projects" / project / "project.toml"
    if not project_toml.is_file():
        return []
    try:
        data = tomllib.loads(project_toml.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return []
    engineers = data.get("engineers") or []
    return [str(item) for item in engineers if str(item).strip()]


def _project_sessions(project: str) -> set[str]:
    result = subprocess.run(
        ["tmux", "list-sessions", "-F", "#S"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return set()
    return {line.strip() for line in result.stdout.splitlines() if line.strip()}


def _pending_handoff_age_seconds(project: str, seat: str) -> int | None:
    handoffs_dir = _tasks_root() / project / "patrol" / "handoffs"
    if not handoffs_dir.is_dir():
        return None
    now = time.time()
    ages: list[int] = []
    for json_path in sorted(handoffs_dir.glob("*__*__*.json")):
        if json_path.name.endswith(".consumed") or json_path.with_suffix(".json.consumed").exists():
            continue
        try:
            data = json.loads(json_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            data = {}
        target = str(data.get("target") or json_path.name.rsplit("__", 1)[-1].removesuffix(".json")).strip()
        if target != seat:
            continue
        try:
            stat = json_path.stat()
        except OSError:
            continue
        ages.append(int(now - stat.st_mtime))
    return max(ages) if ages else None


def _unblock_seat(target: str, task_id: str) -> dict[str, Any]:
    subprocess.run(
        ["tmux", "send-keys", "-t", target, "\x03"],
        capture_output=True,
        text=True,
        check=False,
    )
    time.sleep(2)
    blocked, reason = _seat_blocked_for(target)
    return {"target": target, "task_id": task_id, "blocked": blocked, "reason": reason}


def detect_stale_handoffs(project: str, threshold_hours: int = STALE_THRESHOLD_HOURS) -> list[dict[str, Any]]:
    handoffs_dir = _tasks_root() / project / "patrol" / "handoffs"
    if not handoffs_dir.is_dir():
        return []

    now = time.time()
    cutoff = now - threshold_hours * 3600
    stale: list[dict[str, Any]] = []
    for json_path in sorted(handoffs_dir.glob("*__*__*.json")):
        if json_path.name.endswith(".consumed") or json_path.with_suffix(".json.consumed").exists():
            continue
        try:
            stat = json_path.stat()
        except OSError:
            continue
        if stat.st_mtime >= cutoff:
            continue
        try:
            data = json.loads(json_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            data = {}
        age_hours = int((now - stat.st_mtime) / 3600)
        stale.append(
            {
                "task_id": data.get("task_id") or json_path.name.split("__", 1)[0],
                "source": data.get("source") or "<unknown>",
                "target": data.get("target") or "<unknown>",
                "age_hours": age_hours,
                "json_path": str(json_path),
            }
        )
    return stale


def _recent_rewake_keys(
    log_path: Path,
    *,
    now: float,
    cooldown_seconds: int = REWAKE_COOLDOWN_SECONDS,
) -> set[str]:
    if not log_path.exists():
        return set()
    recent: set[str] = set()
    try:
        lines = log_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return set()
    for line in lines:
        parts = line.split("\t")
        if len(parts) < 4:
            continue
        try:
            ts = float(parts[0])
        except ValueError:
            continue
        if now - ts <= cooldown_seconds:
            recent.add(parts[3])
    return recent


def _append_rewake_log(log_path: Path, *, project: str, handoff: dict[str, Any], now: float) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    line = "\t".join(
        [
            f"{now:.3f}",
            project,
            str(handoff.get("target", "<unknown>")),
            str(handoff.get("json_path", "")),
            str(handoff.get("task_id", "<unknown>")),
        ]
    )
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")


def re_wake_stale_handoffs(
    project: str,
    threshold_hours: int = STALE_THRESHOLD_HOURS,
    cooldown_seconds: int = REWAKE_COOLDOWN_SECONDS,
) -> int:
    stale = detect_stale_handoffs(project, threshold_hours=threshold_hours)
    if not stale:
        return 0
    now = time.time()
    log_path = _rewake_log_path()
    recent = _recent_rewake_keys(log_path, now=now, cooldown_seconds=cooldown_seconds)
    send_script = Path.home() / "ClawSeat" / "core" / "shell-scripts" / "send-and-verify.sh"

    sent = 0
    for handoff in stale:
        if sent >= MAX_REWAKES_PER_CYCLE:
            break
        json_path = str(handoff.get("json_path", ""))
        if json_path in recent:
            continue
        target = str(handoff.get("target") or "")
        if not target or target == "<unknown>":
            continue
        blocked, reason = _seat_blocked_for(target)
        if reason == "background terminal running":
            continue
        if blocked:
            age_seconds = int(handoff.get("age_hours", 0)) * 3600
            if age_seconds < SEAT_HEALTH_THRESHOLD_SECONDS:
                continue
            unblock_result = _unblock_seat(target, str(handoff.get("task_id", "<unknown>")))
            _append_seat_unblock_log(
                project=project,
                seat=target,
                session=target,
                task_id=str(handoff.get("task_id", "<unknown>")),
                action="unblock",
                reason=unblock_result["reason"] or reason,
                age_seconds=age_seconds,
            )
            if unblock_result["blocked"]:
                _append_seat_unblock_log(
                    project=project,
                    seat=target,
                    session=target,
                    task_id=str(handoff.get("task_id", "<unknown>")),
                    action="unblock_failed",
                    reason=unblock_result["reason"],
                    age_seconds=age_seconds,
                )
        msg = (
            f"[TASK-QUEUE] 你有未处理的 handoff: {handoff['task_id']}(已 {handoff['age_hours']}h)。\n"
            "请读 TODO.md 头部处理。"
        )
        subprocess.run(
            ["bash", str(send_script), "--project", project, target, msg],
            check=False,
        )
        _append_rewake_log(log_path, project=project, handoff=handoff, now=now)
        sent += 1
    return sent


def _patrol_seat_health(project: str) -> dict[str, Any]:
    engineers = _load_project_engineers(project)
    sessions = _project_sessions(project)
    ok = 0
    blocked = 0
    dead = 0
    for seat in engineers:
        session = f"{project}-{seat}"
        if session not in sessions:
            dead += 1
            _append_seat_unblock_log(
                project=project,
                seat=seat,
                session=session,
                task_id="seat-health",
                action="dead",
                reason="session missing",
            )
            continue
        is_blocked, reason = _seat_blocked_for(session)
        if not is_blocked:
            ok += 1
            continue
        age_seconds = _pending_handoff_age_seconds(project, seat) or 0
        if age_seconds < SEAT_HEALTH_THRESHOLD_SECONDS:
            ok += 1
            continue
        unblock_result = _unblock_seat(session, f"seat-health:{seat}")
        blocked += 1
        _append_seat_unblock_log(
            project=project,
            seat=seat,
            session=session,
            task_id=f"seat-health:{seat}",
            action="health_unblock",
            reason=unblock_result["reason"] or reason,
            age_seconds=age_seconds,
        )
        if unblock_result["blocked"]:
            _append_seat_unblock_log(
                project=project,
                seat=seat,
                session=session,
                task_id=f"seat-health:{seat}",
                action="health_unblock_failed",
                reason=unblock_result["reason"],
                age_seconds=age_seconds,
            )
    summary = f"[SEAT-HEALTH:project={project},ok={ok},blocked={blocked},dead={dead}]"
    return {"ok": ok, "blocked": blocked, "dead": dead, "summary": summary}


def main() -> int:
    args = parse_args()
    profile = load_profile(args.profile)
    materialize_profile_runtime(profile)
    cmd = executable_command(profile.patrol_script)
    if args.send:
        cmd.append("--send")
    result = run_command(cmd, cwd=profile.repo_root)
    require_success(result, "patrol_loop")
    if result.stdout.strip():
        print(result.stdout.strip())
    run_auto_supersede(profile, age_days=args.auto_supersede_age_days)
    seat_health = _patrol_seat_health(profile.project_name)
    rewake_count = re_wake_stale_handoffs(
        profile.project_name,
        threshold_hours=args.stale_threshold_hours,
        cooldown_seconds=args.rewake_cooldown_seconds,
    )
    print(seat_health["summary"])
    if rewake_count:
        print(f"[STALE-HANDOFF-REWAKE:project={profile.project_name},count={rewake_count}]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
