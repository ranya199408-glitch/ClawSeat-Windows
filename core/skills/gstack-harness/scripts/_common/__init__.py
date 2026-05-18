"""Backward-compatible export surface for legacy gstack harness scripts."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from _utils import (  # noqa: F401
    AGENT_HOME,
    AGENTS_ROOT,
    CONSUMED_RE,
    OPENCLAW_AGENTS_ROOT,
    OPENCLAW_CONFIG_PATH,
    OPENCLAW_FEISHU_SEND_SH,
    OPENCLAW_HOME,
    PLACEHOLDER_RE,
    REPO_ROOT,
    SCRIPTS_ROOT,
    TASK_ROW_RE,
    ensure_dir,
    ensure_parent,
    executable_command,
    load_json,
    load_toml,
    q,
    q_array,
    read_text,
    require_success,
    run_command,
    run_command_with_env,
    sanitize_name,
    summarize_status_lines,
    utc_now_iso,
    write_json,
    write_text,
)
from _feishu import (  # noqa: F401
    DELEGATION_REPORT_HEADER,
    VALID_DELEGATION_DECISION_HINTS,
    VALID_DELEGATION_LANES,
    VALID_DELEGATION_NEXT_ACTIONS,
    VALID_DELEGATION_REPORT_STATUSES,
    VALID_DELEGATION_USER_GATES,
    _classify_send_failure,
    _is_sandbox_home,
    _lark_cli_cwd,
    _lark_cli_env,
    _lark_cli_real_home,
    _real_user_home,
    _resolve_effective_home,
    broadcast_feishu_group_message,
    build_delegation_report_text,
    check_feishu_auth,
    collect_feishu_group_ids_from_config,
    collect_feishu_group_ids_from_sessions,
    collect_feishu_group_keys,
    FeishuGroupResolutionError,
    legacy_feishu_group_broadcast_enabled,
    resolve_feishu_group_strict,
    resolve_primary_feishu_group_id,
    sanitize_human_summary,
    sanitize_report_value,
    send_feishu_user_message,
    stable_dispatch_nonce,
)
from _task_io import (  # noqa: F401
    append_consumed_ack,
    append_status_dispatch_event,
    append_status_dispatch_log,
    append_status_note,
    append_task_to_queue,
    build_completion_message,
    build_notify_message,
    build_notify_payload,
    complete_task_in_queue,
    extract_canonical_verdict,
    extract_prefixed_value,
    file_declares_task,
    find_consumed_ack,
    handoff_assigned,
    upsert_tasks_row,
    write_delivery,
    write_todo,
)
from _heartbeat_helpers import (  # noqa: F401
    heartbeat_manifest_fingerprint,
    heartbeat_receipt_is_verified,
    heartbeat_state,
)

from ._utils import *  # noqa: F401,F403
from .profile import *  # noqa: F401,F403
from .session import *  # noqa: F401,F403
from .notify import *  # noqa: F401,F403
from .heartbeat import *  # noqa: F401,F403
from .notify import notify as notify  # noqa: F401,E402

__all__ = [
    name
    for name in globals()
    if not name.startswith("__") and name not in {"_utils", "profile", "session", "heartbeat"}
]
