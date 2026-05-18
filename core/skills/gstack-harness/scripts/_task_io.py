"""Task dispatch/completion file operations — extracted from _common.py."""
from __future__ import annotations

from contextlib import contextmanager
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

from _utils import (
    CONSUMED_RE,
    TASK_ROW_RE,
    ensure_parent,
    read_text,
    utc_now_iso,
    write_json,
    write_text,
)


DISPATCH_LOG_HEADER = "## dispatch log (append-only, last 20)"
DISPATCH_LOG_LIMIT = 20
DISPATCH_LOG_HEAL_NOTE = "<!-- auto-healed by dispatch_task.py -->"


def build_notify_message(
    target_seat: str,
    todo_path: Path,
    task_id: str,
    *,
    source: str,
    reply_to: str,
) -> str:
    return (
        f"{task_id} assigned from {source} to {target_seat}. "
        f"Read {todo_path}. When complete, reply to {reply_to} via DELIVERY + notify."
    )


def build_completion_message(
    task_id: str,
    delivery_path: Path,
    *,
    source: str,
    target: str,
    user_summary: str | None = None,
) -> str:
    base = (
        f"{task_id} complete from {source} to {target}. "
        f"Read {delivery_path} and write a durable Consumed ACK when handled."
    )
    if user_summary and user_summary.strip():
        return f"{base} UserSummary: {user_summary.strip()}"
    return base


def build_notify_payload(
    *,
    source: str,
    target: str,
    message: str,
    kind: str = "notice",
    task_id: str | None = None,
    reply_to: str | None = None,
    project_name: str | None = None,
) -> str:
    """Canonical payload for notify_seat dispatches.

    Shared by both the static (`notify_seat.py`) and dynamic-roster
    (`notify_seat_dynamic.py`) entrypoints so the two cannot drift.
    `project_name` is optional; when provided, the payload is prefixed
    with `[project_name]` (dynamic-roster convention).
    """
    prefix = f"{kind} from {source} to {target}"
    if task_id:
        prefix = f"{task_id} {prefix}"
    suffix = ""
    if reply_to:
        suffix = f" Reply to {reply_to} if follow-up or completion is required."
    core = f"{prefix}: {message.strip()}{suffix}"
    if project_name:
        return f"[{project_name}] {core}"
    return core


def upsert_tasks_row(path: Path, *, task_id: str, title: str, owner: str, status: str, notes: str) -> None:
    existing = read_text(path).splitlines()
    if not existing:
        existing = [
            "# Tasks",
            "",
            "| ID | Title | Owner | Status | Notes |",
            "|----|-------|-------|--------|-------|",
        ]
    new_row = f"| {task_id} | {title} | {owner} | {status} | {notes} |"
    row_index = None
    table_end = None
    for idx, line in enumerate(existing):
        if TASK_ROW_RE.match(line):
            table_end = idx
            if line.startswith(f"| {task_id} |"):
                row_index = idx
        elif table_end is not None and line.strip() and not line.startswith("|"):
            break
    if row_index is not None:
        existing[row_index] = new_row
    else:
        insert_at = table_end + 1 if table_end is not None else len(existing)
        existing.insert(insert_at, new_row)
    write_text(path, "\n".join(existing))


def append_status_note(path: Path, note: str) -> None:
    timestamp = utc_now_iso()
    existing = read_text(path)
    block = f"- {timestamp}: {note}"
    if existing.strip():
        write_text(path, existing.rstrip() + "\n" + block)
    else:
        write_text(path, "# Status\n\n" + block)


def _local_now_iso() -> str:
    return datetime.now().astimezone().replace(microsecond=0).isoformat()


def _atomic_write_text(path: Path, text: str) -> None:
    ensure_parent(path)
    tmp = path.with_name(f"{path.name}.tmp")
    tmp.write_text(text.rstrip() + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _dispatch_log_lock_path(path: Path) -> Path:
    return path.with_name(f"{path.name}.lock")


if os.name == "nt":
    import msvcrt

    @contextmanager
    def _dispatch_log_lock(path: Path):
        lock_path = _dispatch_log_lock_path(path)
        ensure_parent(lock_path)
        with lock_path.open("a+", encoding="utf-8") as lock_file:
            lock_file.seek(0)
            msvcrt.locking(lock_file.fileno(), msvcrt.LK_LOCK, 1)
            try:
                yield
            finally:
                lock_file.seek(0)
                msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
else:
    import fcntl

    @contextmanager
    def _dispatch_log_lock(path: Path):
        lock_path = _dispatch_log_lock_path(path)
        ensure_parent(lock_path)
        with lock_path.open("a+", encoding="utf-8") as lock_file:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _dispatch_log_bounds(lines: list[str]) -> tuple[int, int]:
    header_idx = next(
        (idx for idx, line in enumerate(lines) if line.strip() == DISPATCH_LOG_HEADER),
        -1,
    )
    if header_idx < 0:
        raise ValueError(f"{DISPATCH_LOG_HEADER!r} section missing")
    start = header_idx + 1
    end = len(lines)
    for idx in range(start, len(lines)):
        if lines[idx].startswith("## "):
            end = idx
            break
    return start, end


def _dispatch_log_heal_audit_path(audit_dir: Path, task_id: str) -> Path:
    stamp = utc_now_iso().replace(":", "").replace("-", "").replace("+", "p")
    safe_task_id = re.sub(r"[^A-Za-z0-9._-]+", "-", task_id)
    return audit_dir / f"dispatch-log-heal-{safe_task_id}-{stamp}.json"


def append_status_dispatch_log(
    path: Path,
    line: str,
    *,
    task_id: str | None = None,
    audit_dir: Path | None = None,
) -> bool:
    """Append one line to STATUS.md dispatch log, keeping the newest 20 entries.

    This is deliberately best-effort: callers use it as a noncritical side
    effect after dispatch/ack success. Any failure is reported to stderr and
    returns False so the dispatch channel cannot be broken by STATUS.md drift.
    """
    try:
        with _dispatch_log_lock(path):
            text = read_text(path)
            lines = text.splitlines()
            healed = False
            if DISPATCH_LOG_HEADER not in lines:
                healed = True
                lines = lines + ["", DISPATCH_LOG_HEAL_NOTE, "", DISPATCH_LOG_HEADER]
            start, end = _dispatch_log_bounds(lines)
            entries = [
                item
                for item in lines[start:end]
                if item.strip() and item.strip() != "(none)"
            ]
            entries.append(line)
            entries = entries[-DISPATCH_LOG_LIMIT:]

            new_lines = lines[:start] + [""] + entries
            if end < len(lines):
                new_lines += [""] + lines[end:]
            _atomic_write_text(path, "\n".join(new_lines))
        if healed:
            print("INFO: STATUS.md dispatch-log section auto-healed", file=sys.stderr)
            if audit_dir is not None and task_id:
                write_json(
                    _dispatch_log_heal_audit_path(Path(audit_dir), task_id),
                    {
                        "reason": "section_absent",
                        "task_id": task_id,
                        "status_path": str(path),
                        "healed_at": utc_now_iso(),
                    },
                )
        return True
    except Exception as exc:  # noqa: BLE001 side effect must never break dispatch
        print(f"warn: STATUS.md dispatch log append skipped: {exc}", file=sys.stderr)
        return False


def append_status_dispatch_event(
    path: Path,
    *,
    source: str,
    task_id: str,
    target: str | None = None,
    verdict: str | None = None,
    commit: str | None = None,
    test_policy: str | None = None,
    finding_id: str | None = None,
    hypothesis_counter: int | None = None,
    rca_override: bool = False,
    core_ux: bool = False,
    audit_dir: Path | None = None,
    timestamp: str | None = None,
) -> bool:
    ts = timestamp or _local_now_iso()
    extras = []
    if test_policy:
        extras.append(f"test_policy={test_policy}")
    if finding_id:
        extras.append(f"finding_id={finding_id}")
    if hypothesis_counter is not None:
        extras.append(f"hypothesis_counter={hypothesis_counter}")
    if rca_override:
        extras.append("rca_override=true")
    if core_ux:
        extras.append("core_ux=true")
    if target:
        suffix = f" {' '.join(extras)}" if extras else ""
        line = f"- {ts}: {source} dispatched {task_id} to {target}{suffix}"
    else:
        if verdict:
            extras.append(f"verdict={verdict}")
        if commit:
            extras.append(f"commit={commit}")
        suffix = f" {' '.join(extras)}" if extras else ""
        line = f"- {ts}: {source} ack {task_id}{suffix}"
    return append_status_dispatch_log(path, line, task_id=task_id, audit_dir=audit_dir)


def write_todo(
    path: Path,
    *,
    task_id: str,
    project: str,
    owner: str,
    status: str,
    title: str,
    objective: str,
    source: str,
    reply_to: str,
    test_policy: str | None = None,
) -> None:
    lines = [
        f"task_id: {task_id}",
        f"project: {project}",
        f"owner: {owner}",
        f"status: {status}",
        f"title: {title}",
    ]
    if test_policy:
        lines.append(f"test_policy: {test_policy}")
    text = (
        "\n".join(lines)
        + "\n\n"
        f"# Objective\n\n{objective.strip()}\n\n"
        f"# Dispatch\n\n"
        f"source: {source}\n"
        f"reply_to: {reply_to}\n"
        f"dispatched_at: {utc_now_iso()}\n"
    )
    write_text(path, text)


def write_delivery(
    path: Path,
    *,
    task_id: str,
    owner: str,
    target: str,
    title: str,
    summary: str,
    status: str,
    verdict: str | None = None,
    frontstage_disposition: str | None = None,
    user_summary: str | None = None,
    next_action: str | None = None,
    correlation_id: str | None = None,
    branch: str | None = None,
    commit: str | None = None,
    sweep_count: int | str | None = None,
    core_ux_gate: str | None = None,
) -> None:
    lines = [
        f"task_id: {task_id}",
        f"owner: {owner}",
        f"target: {target}",
        f"status: {status}",
        f"date: {utc_now_iso()}",
    ]
    if correlation_id:
        lines.append(f"correlation_id: {correlation_id}")
    if branch:
        lines.append(f"branch: {branch}")
    if commit:
        lines.append(f"commit: {commit}")
    if sweep_count is not None:
        lines.append(f"sweep_count: {sweep_count}")
    lines += [
        "",
        f"# Delivery: {title}",
        "",
        "## Summary",
        "",
        summary.strip(),
    ]
    if verdict:
        lines.extend(["", f"Verdict: {verdict}"])
    if frontstage_disposition:
        lines.extend(["", f"FrontstageDisposition: {frontstage_disposition}"])
    if user_summary:
        lines.extend(["", f"UserSummary: {user_summary.strip()}"])
    if next_action:
        lines.extend(["", f"NextAction: {next_action.strip()}"])
    if core_ux_gate:
        lines.extend(["", f"core_ux_gate: {core_ux_gate}"])
    write_text(path, "\n".join(lines))


def append_consumed_ack(path: Path, *, task_id: str, source: str) -> str:
    existing = read_text(path)
    for line in existing.splitlines():
        match = CONSUMED_RE.match(line.strip())
        if not match:
            continue
        if match.group("task_id") == task_id and match.group("source") == source:
            return line.strip()
    ack_line = f"Consumed: {task_id} from {source} at {utc_now_iso()}"
    if existing.strip():
        write_text(path, existing.rstrip() + "\n" + ack_line)
    else:
        write_text(path, ack_line)
    return ack_line


def find_consumed_ack(path: Path, *, task_id: str, source: str) -> str | None:
    for line in read_text(path).splitlines():
        match = CONSUMED_RE.match(line.strip())
        if not match:
            continue
        if match.group("task_id") == task_id and match.group("source") == source:
            return line.strip()
    return None


def extract_canonical_verdict(path: Path) -> str | None:
    for line in read_text(path).splitlines():
        if line.startswith("Verdict: "):
            verdict = line.split("Verdict: ", 1)[1].strip()
            return verdict or None
    return None


def extract_prefixed_value(path: Path, prefix: str) -> str | None:
    for line in read_text(path).splitlines():
        if line.startswith(prefix):
            value = line.split(prefix, 1)[1].strip()
            return value or None
    return None


def file_declares_task(path: Path, task_id: str) -> bool:
    return path.exists() and f"task_id: {task_id}" in read_text(path)


def handoff_assigned(
    profile: object,
    *,
    task_id: str,
    source: str,
    target: str,
    kind: str = "dispatch",
    delivery_path: str | None = None,
) -> bool:
    todo_path = profile.todo_path(target)  # type: ignore[attr-defined]
    source_delivery_path = profile.delivery_path(source)  # type: ignore[attr-defined]
    if kind == "completion":
        candidate = Path(delivery_path) if delivery_path else source_delivery_path
        return file_declares_task(candidate, task_id)
    if str(source_delivery_path) == str(delivery_path or ""):
        return file_declares_task(source_delivery_path, task_id)
    return file_declares_task(todo_path, task_id)


def append_task_to_queue(
    path: Path,
    *,
    task_id: str,
    project: str,
    owner: str,
    title: str,
    objective: str,
    source: str,
    reply_to: str,
    skill_refs: list[str] | None = None,
    task_type: str = "unspecified",
    review_required: bool = False,
    correlation_id: str | None = None,
    test_policy: str | None = None,
    core_ux: bool = False,
    finding_id: str | None = None,
    hypothesis_fix_counter: int | None = None,
    hypothesis_fix_counter_exceeded: bool = False,
    rca_override: bool | None = None,
) -> None:
    existing = read_text(path)

    # Backward compat: old format (task_id: header) auto-wrapped as queue head.
    # Special case: task_id: null is a bootstrap placeholder — discard it entirely.
    if existing.strip() and existing.lstrip().startswith("task_id:"):
        old_task_id_match = re.search(r"^task_id: (.+)$", existing, re.MULTILINE)
        old_task_id = old_task_id_match.group(1).strip() if old_task_id_match else "legacy"
        if old_task_id == "null":
            # Bootstrap placeholder — replace with empty queue
            existing = ""
        else:
            existing = f"# Queue: {owner}\n\n## [pending] {old_task_id}\n{existing.strip()}\n"

    has_active = bool(re.search(r"^## \[(pending|queued)\]", existing, re.MULTILINE))
    status = "queued" if has_active else "pending"

    entry_lines = [
        f"## [{status}] {task_id}",
        f"task_id: {task_id}",
        f"title: {title}",
        f"task_type: {task_type}",
        f"review_required: {'true' if review_required else 'false'}",
        f"source: {source}",
        f"reply_to: {reply_to}",
        f"dispatched_at: {utc_now_iso()}",
    ]
    if correlation_id:
        entry_lines.append(f"correlation_id: {correlation_id}")
    if test_policy:
        entry_lines.append(f"test_policy: {test_policy}")
    if core_ux:
        entry_lines.append("core_ux: true")
    if finding_id:
        entry_lines.append(f"finding_id: {finding_id}")
    if hypothesis_fix_counter is not None:
        entry_lines.append(f"hypothesis_fix_counter: {hypothesis_fix_counter}")
        entry_lines.append(
            f"hypothesis_fix_counter_exceeded: {'true' if hypothesis_fix_counter_exceeded else 'false'}"
        )
    if rca_override is not None:
        entry_lines.append(f"rca_override: {'true' if rca_override else 'false'}")
    entry_lines += [
        "",
        "### Objective",
        "",
        objective.strip(),
    ]
    if skill_refs:
        entry_lines += ["", "### Skill Refs", ""] + [f"- {ref}" for ref in skill_refs]

    entry = "\n".join(entry_lines)

    if not existing.strip():
        content = f"# Queue: {owner}\n\n{entry}\n"
    elif "\n# Completed" in existing:
        idx = existing.index("\n# Completed")
        content = existing[:idx].rstrip() + f"\n\n---\n\n{entry}\n" + existing[idx:]
    else:
        content = existing.rstrip() + f"\n\n---\n\n{entry}\n"

    write_text(path, content)


def complete_task_in_queue(
    path: Path,
    *,
    task_id: str,
    summary: str,
) -> str | None:
    """Mark task_id as [completed], activate next [queued] task.
    Returns next task_id if one was activated, else None."""
    content = read_text(path)
    if not content.strip():
        return None

    content, n = re.subn(
        rf"^## \[pending\] {re.escape(task_id)}",
        f"## [completed] {task_id}",
        content,
        flags=re.MULTILINE,
    )
    if n == 0:
        return None

    next_task_id = None
    m = re.search(r"^## \[queued\] (\S+)", content, re.MULTILINE)
    if m:
        next_task_id = m.group(1)
        content = content[: m.start()] + f"## [pending] {next_task_id}" + content[m.end():]

    completed_line = f"- [{utc_now_iso()[:10]}] {task_id} — {summary}"
    if "# Completed" not in content:
        content = content.rstrip() + f"\n\n# Completed\n\n{completed_line}\n"
    else:
        content = content.replace("# Completed\n", f"# Completed\n{completed_line}\n", 1)

    write_text(path, content)
    return next_task_id
