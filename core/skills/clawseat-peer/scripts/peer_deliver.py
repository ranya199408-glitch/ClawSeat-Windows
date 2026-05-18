#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[4]
_CORE_LIB = _REPO_ROOT / "core" / "lib"
if str(_CORE_LIB) not in sys.path:
    sys.path.insert(0, str(_CORE_LIB))

from real_home import real_user_home  # noqa: E402


HOME = real_user_home()
TASKS_ROOT = HOME / ".agents" / "tasks"
RECEIPT_VERDICT = "SUBMITTED"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _safe_component(value: str, label: str) -> str:
    cleaned = value.strip()
    if not cleaned or cleaned in {".", ".."} or any(sep in cleaned for sep in ("/", "\\")):
        raise SystemExit(f"error: invalid {label}: {value!r}")
    return cleaned


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise SystemExit(f"error: cannot read {path}: {exc}") from exc


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.rstrip() + "\n", encoding="utf-8")


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")


def _frontmatter(mapping: dict[str, object]) -> str:
    lines = ["---"]
    for key, value in mapping.items():
        lines.append(f"{key}: {json.dumps(value, ensure_ascii=False)}")
    lines.append("---")
    return "\n".join(lines)


def _task_placeholder(peer_id: str, task_id: str, status: str, summary: str) -> str:
    return "\n".join(
        [
            _frontmatter(
                {
                    "peer_id": peer_id,
                    "task_id": task_id,
                    "status": status,
                    "summary": summary,
                }
            ),
            "",
            "# Task",
            "",
            "No task brief was supplied to peer_deliver.py.",
            "",
        ]
    )


def _delivery_markdown(peer_id: str, task_id: str, status: str, summary: str, project: str) -> str:
    return "\n".join(
        [
            _frontmatter(
                {
                    "peer_id": peer_id,
                    "task_id": task_id,
                    "status": status,
                    "summary": summary,
                    "project": project,
                    "date": utc_now_iso(),
                }
            ),
            "",
            "# Delivery",
            "",
            "## Summary",
            "",
            summary.strip(),
            "",
        ]
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Write a peer delivery bundle under peer-deliveries/.")
    parser.add_argument("--project", required=True, help="Owning install project.")
    parser.add_argument("--peer-id", required=True, help="Stable peer identifier.")
    parser.add_argument("--task-id", required=True, help="Peer task id.")
    parser.add_argument("--status", required=True, help="Peer delivery status.")
    parser.add_argument("--summary", required=True, help="One-line delivery summary.")
    parser.add_argument("--task-file", help="Optional task brief file to copy into TASK.md.")
    parser.add_argument("--task-text", help="Optional inline task brief to write into TASK.md.")
    parser.add_argument("--receipt-verdict", default=RECEIPT_VERDICT, help="Receipt verdict label.")
    parser.add_argument("--receipt-notes", default="", help="Receipt notes; defaults to summary.")
    parser.add_argument("--heartbeat-state", default="progressing", help="Heartbeat state label.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    project = _safe_component(args.project, "project")
    peer_id = _safe_component(args.peer_id, "peer-id")
    task_id = _safe_component(args.task_id, "task-id")
    status = args.status.strip() or "unknown"
    summary = args.summary.strip() or task_id

    peer_root = TASKS_ROOT / project / "peer-deliveries" / peer_id
    task_dir = peer_root / "tasks" / task_id
    task_dir.mkdir(parents=True, exist_ok=True)

    now = utc_now_iso()
    meta_path = peer_root / "meta.json"
    meta = {
        "peer_id": peer_id,
        "project": project,
        "launched_at": now,
        "updated_at": now,
        "status": "active",
    }
    if meta_path.exists():
        try:
            previous = json.loads(meta_path.read_text(encoding="utf-8"))
            if isinstance(previous, dict):
                meta["launched_at"] = str(previous.get("launched_at") or now)
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            pass
    _write_json(meta_path, meta)

    heartbeat_path = peer_root / "heartbeat.json"
    _write_json(
        heartbeat_path,
        {
            "peer_id": peer_id,
            "project": project,
            "task_id": task_id,
            "state": args.heartbeat_state.strip() or "progressing",
            "heartbeat_at": now,
            "updated_at": now,
        },
    )

    task_md = task_dir / "TASK.md"
    if args.task_text is not None:
        _write_text(task_md, args.task_text)
    elif args.task_file:
        _write_text(task_md, _read_text(Path(args.task_file).expanduser()))
    elif not task_md.exists():
        _write_text(task_md, _task_placeholder(peer_id, task_id, status, summary))

    delivery_path = task_dir / "DELIVERY.md"
    _write_text(delivery_path, _delivery_markdown(peer_id, task_id, status, summary, project))

    receipt_path = task_dir / "receipt.json"
    _write_json(
        receipt_path,
        {
            "acknowledged_by": peer_id,
            "acknowledged_at": now,
            "verdict": args.receipt_verdict.strip() or RECEIPT_VERDICT,
            "notes": (args.receipt_notes.strip() or summary),
        },
    )

    payload = {
        "project": project,
        "peer_id": peer_id,
        "task_id": task_id,
        "status": status,
        "summary": summary,
        "peer_root": str(peer_root),
        "task_dir": str(task_dir),
        "task_md": str(task_md),
        "delivery_md": str(delivery_path),
        "receipt_json": str(receipt_path),
        "heartbeat_json": str(heartbeat_path),
    }
    print(json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
