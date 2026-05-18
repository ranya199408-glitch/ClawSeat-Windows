"""Standalone helper functions for the ClawSeat adapter.

These are pure functions (no ``self``) extracted from ``ClawseatAdapter``
to keep the main class file focused on orchestration logic.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from ._adapter_types import AdapterResult, PendingFrontstageItem


# ---------------------------------------------------------------------------
# File-parsing helpers
# ---------------------------------------------------------------------------

def load_toml_like(path: Path) -> dict[str, str]:
    """Parse a minimal TOML-like key=value file (no sections, no arrays)."""
    data: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" not in line:
            continue
        key, raw_value = line.split("=", 1)
        key = key.strip()
        raw_value = raw_value.strip()
        if raw_value.startswith('"') and raw_value.endswith('"'):
            data[key] = raw_value[1:-1]
        elif raw_value in {"true", "false"}:
            data[key] = raw_value
    return data


def parse_brief(path: Path) -> dict[str, str]:
    """Parse a PLANNER_BRIEF.md file into a flat dict."""
    parsed = {
        "title": "",
        "owner": "",
        "status": "",
        "updated": "",
        "frontstage_disposition": "",
        "user_summary": "",
        "requested_operation": "",
        "target_role": "",
        "target_instance": "",
        "template_id": "",
        "reason": "",
        "resume_task": "",
    }
    if not path.exists():
        return parsed
    in_user_summary = False
    summary_lines: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if not parsed["title"] and stripped.startswith("# "):
            parsed["title"] = stripped[2:].strip()
            continue
        for field in (
            "owner",
            "status",
            "updated",
            "frontstage_disposition",
            "requested_operation",
            "target_role",
            "target_instance",
            "template_id",
            "reason",
            "resume_task",
        ):
            prefix = f"{field}:"
            if not parsed[field] and stripped.startswith(prefix):
                parsed[field] = stripped.split(":", 1)[1].strip()
                break
        else:
            if stripped == "## \u7528\u6237\u6458\u8981":
                in_user_summary = True
                continue
            if in_user_summary and stripped.startswith("## "):
                in_user_summary = False
                continue
            if in_user_summary:
                summary_lines.append(stripped)
    parsed["user_summary"] = " ".join(summary_lines).strip()
    return parsed


# ---------------------------------------------------------------------------
# Pending-frontstage helpers
# ---------------------------------------------------------------------------

def parse_pending_item(heading: str, lines: list[str], section: str) -> PendingFrontstageItem:
    """Parse a single pending-frontstage item from its heading and body lines."""
    fields = {
        "id": heading,
        "type": "",
        "related_task": "",
        "summary": "",
        "planner_recommendation": "",
        "koder_default_action": "",
        "user_input_needed": "false",
        "blocking": "false",
        "resolved": "false",
        "resolved_by": "",
        "resolved_at": "",
        "resolution": "",
    }
    options: list[str] = []
    in_options = False
    for raw_line in lines:
        stripped = raw_line.strip()
        if not stripped:
            continue
        if stripped == "options:":
            in_options = True
            continue
        if in_options and stripped.startswith("- "):
            options.append(stripped[2:].strip())
            continue
        if in_options and ":" in stripped:
            in_options = False
        if ":" in stripped:
            key, value = stripped.split(":", 1)
            key = key.strip()
            value = value.strip()
            if key in fields:
                fields[key] = value
    return PendingFrontstageItem(
        item_id=fields["id"] or heading,
        item_type=fields["type"],
        related_task=fields["related_task"],
        summary=fields["summary"],
        planner_recommendation=fields["planner_recommendation"],
        koder_default_action=fields["koder_default_action"],
        user_input_needed=fields["user_input_needed"].lower() == "true",
        blocking=fields["blocking"].lower() == "true",
        options=options,
        resolved=fields["resolved"].lower() == "true",
        resolved_by=fields["resolved_by"],
        resolved_at=fields["resolved_at"],
        resolution=fields["resolution"],
        section=section or "pending",
    )


def parse_pending_frontstage(path: Path) -> list[PendingFrontstageItem]:
    """Parse a PENDING_FRONTSTAGE.md file into a list of items."""
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    section = ""
    current_heading = ""
    current_lines: list[str] = []
    items: list[PendingFrontstageItem] = []

    def flush() -> None:
        nonlocal current_heading, current_lines
        if not current_heading:
            return
        items.append(parse_pending_item(current_heading, current_lines, section))
        current_heading = ""
        current_lines = []

    for line in lines:
        stripped = line.strip()
        if stripped == "## \u5f85\u5904\u7406\u4e8b\u9879":
            flush()
            section = "pending"
            continue
        if stripped == "## \u5df2\u5f52\u6863":
            flush()
            section = "archived"
            continue
        if stripped.startswith("### "):
            flush()
            current_heading = stripped[4:].strip()
            current_lines = []
            continue
        if current_heading:
            current_lines.append(line)
    flush()
    return items


def render_pending_item(item: PendingFrontstageItem) -> list[str]:
    """Render a single pending-frontstage item back to markdown lines."""
    lines = [
        f"### {item.item_id}",
        f"id: {item.item_id}",
        f"type: {item.item_type}",
        f"related_task: {item.related_task}",
        f"summary: {item.summary}",
        f"planner_recommendation: {item.planner_recommendation}",
        f"koder_default_action: {item.koder_default_action}",
        f"user_input_needed: {'true' if item.user_input_needed else 'false'}",
        f"blocking: {'true' if item.blocking else 'false'}",
        "options:",
    ]
    for option in item.options:
        lines.append(f"  - {option}")
    lines.extend(
        [
            f"resolved: {'true' if item.resolved else 'false'}",
            f"resolved_by: {item.resolved_by}",
            f"resolved_at: {item.resolved_at}",
            f"resolution: {item.resolution}",
            "",
        ]
    )
    return lines


def write_pending_frontstage(path: Path, items: list[PendingFrontstageItem]) -> None:
    """Write a full PENDING_FRONTSTAGE.md from a list of items."""
    pending = [item for item in items if item.section != "archived" and not item.resolved]
    archived = [item for item in items if item.section == "archived" or item.resolved]
    lines = [
        "# PENDING_FRONTSTAGE",
        "",
        "## \u5b57\u6bb5\u5b9a\u4e49",
        "",
        "- `id`: \u552f\u4e00\u4e8b\u9879 id\uff0c\u4f8b\u5982 `PF-001`",
        "- `type`: `decision | clarification`",
        "- `related_task`: \u5173\u8054\u4efb\u52a1 id",
        "- `summary`: \u4e00\u53e5\u8bdd\u4e2d\u6587\u6458\u8981",
        "- `planner_recommendation`: planner \u5efa\u8bae\u65b9\u6848",
        "- `koder_default_action`: koder \u4e0d\u4e0a\u6d6e\u7528\u6237\u65f6\u7684\u9ed8\u8ba4\u52a8\u4f5c",
        "- `user_input_needed`: `true | false`",
        "- `blocking`: `true | false`",
        "- `options`: \u53ef\u9009\u9879\u5217\u8868",
        "- `resolved`: `true | false`",
        "- `resolved_by`: `koder | user`",
        "- `resolved_at`: ISO timestamp",
        "- `resolution`: \u6700\u7ec8\u51b3\u5b9a\u6216\u8865\u5145\u8bf4\u660e",
        "",
        "## \u5f85\u5904\u7406\u4e8b\u9879",
        "",
    ]
    if pending:
        for item in pending:
            lines.extend(render_pending_item(item))
    lines.extend(
        [
            "## \u5df2\u5f52\u6863",
            "",
        ]
    )
    if archived:
        for item in archived:
            lines.extend(render_pending_item(item))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# Serialization helpers
# ---------------------------------------------------------------------------

def serialize_adapter_result(result: AdapterResult) -> dict[str, Any]:
    """Convert an ``AdapterResult`` to a plain dict."""
    return {
        "command": result.command,
        "returncode": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }


__all__ = [
    "load_toml_like",
    "parse_brief",
    "parse_pending_frontstage",
    "parse_pending_item",
    "render_pending_item",
    "serialize_adapter_result",
    "write_pending_frontstage",
]
