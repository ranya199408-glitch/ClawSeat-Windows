#!/usr/bin/env python3
"""Validate and send Memory decision_payload messages to Koder."""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any


SCHEMA_PATH = Path(__file__).resolve().parents[2] / "schemas" / "decision-payload.schema.json"
_OPTION_ID_RE = re.compile(r"^[A-F]$")
_SEAT_RE = re.compile(r"^([a-z0-9-]+-)?(memory|planner|builder|designer|koder)$")
_ISSUE_RE = re.compile(r"^(#[0-9]+|NEW)$")
_ALLOWED_KEYS = {
    "decision_id",
    "from_seat",
    "to_seat",
    "issue_id",
    "severity",
    "category",
    "context",
    "options",
    "default_if_timeout",
    "timeout_minutes",
    "supporting_docs",
    "created_at",
    "decided_at",
    "decided_by",
    "chosen_option_id",
    "free_text_reply",
}
_REQUIRED_KEYS = {
    "decision_id",
    "from_seat",
    "to_seat",
    "severity",
    "category",
    "context",
    "options",
    "default_if_timeout",
    "timeout_minutes",
    "created_at",
}
_SEVERITIES = {"BLOCKER", "HIGH", "MEDIUM", "LOW"}
_CATEGORIES = {"breaking", "secret", "merge", "skill", "preference", "scope"}


class DecisionPayloadError(ValueError):
    """Raised when a decision_payload violates the schema contract."""


def load_payload(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise DecisionPayloadError("payload must be a JSON object")
    return data


def validate_decision_payload(payload: dict[str, Any]) -> None:
    unknown = sorted(set(payload) - _ALLOWED_KEYS)
    if unknown:
        raise DecisionPayloadError(f"unknown field(s): {', '.join(unknown)}")
    missing = sorted(_REQUIRED_KEYS - set(payload))
    if missing:
        raise DecisionPayloadError(f"missing required field(s): {', '.join(missing)}")
    for key in ("from_seat", "to_seat"):
        value = str(payload.get(key) or "")
        if not _SEAT_RE.match(value):
            raise DecisionPayloadError(f"{key} must be a memory/planner/builder/designer/koder seat")
    if payload["severity"] not in _SEVERITIES:
        raise DecisionPayloadError("severity is invalid")
    if payload["category"] not in _CATEGORIES:
        raise DecisionPayloadError("category is invalid")
    if "issue_id" in payload and not _ISSUE_RE.match(str(payload["issue_id"])):
        raise DecisionPayloadError("issue_id must be #<number> or NEW")
    context = str(payload.get("context") or "")
    if not context or len(context) > 500:
        raise DecisionPayloadError("context must be 1-500 characters")
    options = payload.get("options")
    if not isinstance(options, list) or not (1 <= len(options) <= 6):
        raise DecisionPayloadError("options must contain 1-6 entries")
    option_ids: set[str] = set()
    for idx, option in enumerate(options):
        if not isinstance(option, dict):
            raise DecisionPayloadError(f"options[{idx}] must be an object")
        unknown_option = sorted(set(option) - {"id", "label", "impact"})
        if unknown_option:
            raise DecisionPayloadError(f"options[{idx}] unknown field(s): {', '.join(unknown_option)}")
        for key in ("id", "label", "impact"):
            if key not in option:
                raise DecisionPayloadError(f"options[{idx}] missing {key}")
        option_id = str(option["id"])
        if not _OPTION_ID_RE.match(option_id):
            raise DecisionPayloadError(f"options[{idx}].id must be A-F")
        if option_id in option_ids:
            raise DecisionPayloadError(f"duplicate option id: {option_id}")
        option_ids.add(option_id)
        if not str(option["label"]).strip() or len(str(option["label"])) > 80:
            raise DecisionPayloadError(f"options[{idx}].label must be 1-80 characters")
        if not str(option["impact"]).strip() or len(str(option["impact"])) > 200:
            raise DecisionPayloadError(f"options[{idx}].impact must be 1-200 characters")
    default = str(payload.get("default_if_timeout") or "")
    if default not in option_ids and default not in {"wait", "abort"}:
        raise DecisionPayloadError("default_if_timeout must be an option id, wait, or abort")
    timeout = payload.get("timeout_minutes")
    if not isinstance(timeout, int) or not (1 <= timeout <= 1440):
        raise DecisionPayloadError("timeout_minutes must be an integer from 1 to 1440")
    supporting_docs = payload.get("supporting_docs", [])
    if supporting_docs is not None and (
        not isinstance(supporting_docs, list) or any(not isinstance(item, str) for item in supporting_docs)
    ):
        raise DecisionPayloadError("supporting_docs must be a string array")
    chosen = payload.get("chosen_option_id")
    if chosen is not None and str(chosen) not in option_ids:
        raise DecisionPayloadError("chosen_option_id must match an option id")


def tmux_send_payload(session: str, payload: dict[str, Any], *, runner=subprocess.run) -> subprocess.CompletedProcess[str]:
    validate_decision_payload(payload)
    message = "DECISION_PAYLOAD " + json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return runner(["tmux-send", session, message], capture_output=True, text=True, check=False)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="decision_payload.py")
    sub = parser.add_subparsers(dest="command", required=True)

    validate = sub.add_parser("validate")
    validate.add_argument("--payload-file", required=True)

    send = sub.add_parser("send")
    send.add_argument("--session", required=True)
    send.add_argument("--payload-file", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        payload = load_payload(Path(args.payload_file))
        validate_decision_payload(payload)
        if args.command == "send":
            result = tmux_send_payload(args.session, payload)
            if result.returncode != 0:
                print(result.stderr.strip() or result.stdout.strip(), file=sys.stderr)
                return result.returncode
        print("ok")
        return 0
    except (OSError, json.JSONDecodeError, DecisionPayloadError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
