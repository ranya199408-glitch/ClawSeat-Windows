#!/usr/bin/env python3
"""
init_koder.py — Initialize an OpenClaw agent workspace as ClawSeat koder.

Writes the four-file koder workspace contract plus skill symlinks into the
agent's existing workspace directory. Does NOT create the workspace itself —
that's OpenClaw's job.

Usage:
    python3 init_koder.py --workspace <agent_workspace_path> \
        --project <project_name> --profile <profile.toml>
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core._bootstrap import CLAWSEAT_ROOT
from core.resolve import dynamic_profile_path

_harness_scripts = str(CLAWSEAT_ROOT / "core" / "skills" / "gstack-harness" / "scripts")
if _harness_scripts not in sys.path:
    sys.path.insert(0, _harness_scripts)

# Canonical real-HOME resolver — used for default memory root under the
# operator's real home, not the harness sandbox HOME.
_core_lib = str(CLAWSEAT_ROOT / "core" / "lib")
if _core_lib not in sys.path:
    sys.path.insert(0, _core_lib)
from real_home import real_user_home  # noqa: E402

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib  # type: ignore


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Initialize OpenClaw agent workspace as koder.")
    p.add_argument("--workspace", required=True, help="Path to the OpenClaw agent workspace directory.")
    p.add_argument(
        "--project",
        required=True,
        help=(
            "ClawSeat project name (required; no default). "
            "Each koder workspace must be tied to exactly one project — defaulting "
            "to 'install' would silently bind unrelated workspaces to that project."
        ),
    )
    p.add_argument("--profile", help="Path to the dynamic profile TOML. Auto-resolved if omitted.")
    p.add_argument("--feishu-group-id", default="", help="Feishu group ID for this project (oc_xxx). Leave empty to configure later.")
    p.add_argument("--dry-run", action="store_true", help="Print what would be written without changing files.")
    p.add_argument(
        "--on-conflict",
        choices=("ask", "overwrite", "backup", "abort"),
        default="backup",
        help="When the workspace already has managed files (IDENTITY/MEMORY/USER/"
             "WORKSPACE_CONTRACT): back them up to .backup-<timestamp>/ first "
             "(default), overwrite them in place, ask the user interactively, or abort.",
    )
    p.add_argument(
        "--memory-workspace",
        default="",
        help=(
            "When provided, deploy inject_memory.sh from the memory-oracle template "
            "into <memory-workspace>/.claude/hooks/inject_memory.sh (SPEC §5.1 item 12)."
        ),
    )
    p.add_argument(
        "--memory-root",
        default="",
        help=(
            "Absolute path to the memory root (default: ~/.agents/memory). "
            "Used when deploying the inject_memory.sh hook via --memory-workspace."
        ),
    )
    return p.parse_args()


# Files init_koder writes into the workspace. Only these plus obsolete v1 files
# are backed up when --on-conflict=backup is chosen — everything else (skills/,
# repos/, working products like pptx/png etc.) stays in place.
MANAGED_FILES = (
    "IDENTITY.md",
    "MEMORY.md",
    "USER.md",
    "WORKSPACE_CONTRACT.toml",
)

OBSOLETE_FILES = (
    "SOUL.md",
    "TOOLS.md",
    "TOOLS/dispatch.md",
    "TOOLS/project.md",
    "TOOLS/seat.md",
    "TOOLS/memory.md",
    "TOOLS/install.md",
    "TOOLS/koder-hygiene.md",
    "AGENTS.md",
)

KODER_TOOL_TEMPLATE_DIR = CLAWSEAT_ROOT / "core" / "templates" / "koder-workspace-tools"
_TOOL_TEMPLATE_PLACEHOLDER_RE = re.compile(r"{{[A-Za-z0-9_]+}}")


def load_tool_template(name: str) -> str:
    return (KODER_TOOL_TEMPLATE_DIR / name).read_text(encoding="utf-8")


def _render_tool_template(name: str, values: dict[str, object]) -> str:
    rendered = load_tool_template(name)
    for key, value in values.items():
        rendered = rendered.replace(f"{{{{{key}}}}}", str(value))
    leftovers = sorted(set(_TOOL_TEMPLATE_PLACEHOLDER_RE.findall(rendered)))
    if leftovers:
        raise RuntimeError(f"unresolved koder workspace template placeholders in {name}: {leftovers}")
    return rendered


# Conflict-handling plumbing lives in _seat_bootstrap.py.
from _seat_bootstrap import (  # noqa: E402
    backup_managed_files,
    resolve_conflict_policy,
)
from _seat_bootstrap import detect_managed_conflicts as _detect_managed_conflicts_generic  # noqa: E402


def detect_managed_conflicts(workspace: Path) -> list[str]:
    return _detect_managed_conflicts_generic(workspace, (*MANAGED_FILES, *OBSOLETE_FILES))


def load_template() -> dict:
    path = CLAWSEAT_ROOT / "core" / "templates" / "gstack-harness" / "template.toml"
    return tomllib.loads(path.read_text(encoding="utf-8"))


def _find_template_engineer(template: dict, seat_id: str) -> dict:
    for eng in template.get("engineers", []):
        if eng.get("id") == seat_id:
            return dict(eng)
    raise RuntimeError(f"{seat_id} seat not found in gstack-harness template")


def resolve_profile(project: str, explicit: str | None) -> Path:
    if explicit:
        p = Path(explicit).expanduser()
        if p.exists():
            return p
    return dynamic_profile_path(project)


def load_profile_context(project: str, explicit: str | None) -> tuple[Path, Any]:
    from _common import load_profile

    profile_path = resolve_profile(project, explicit)
    return profile_path, load_profile(profile_path)


def koder_spec(template: dict, profile: Any) -> dict:
    seat_id = str(profile.heartbeat_owner).strip() or "koder"
    spec = _find_template_engineer(template, seat_id)
    override = profile.seat_overrides.get(seat_id, {})
    if override:
        spec.update(override)
        spec["id"] = seat_id
    role = str(profile.seat_roles.get(seat_id, spec.get("role", "frontstage-supervisor"))).strip()
    if role:
        spec["role"] = role
    return spec


def roster_seats(profile: Any) -> list[str]:
    return [str(seat) for seat in profile.seats if str(seat).strip()]


def runtime_seats(profile: Any) -> list[str]:
    values = getattr(profile, "runtime_seats", None) or getattr(profile, "materialized_seats", None) or profile.seats
    return [str(seat) for seat in values if str(seat).strip()]


def backend_seats(profile: Any) -> list[str]:
    heartbeat_owner = str(profile.heartbeat_owner).strip()
    return [seat for seat in runtime_seats(profile) if seat != heartbeat_owner]


def default_backend_start_seats(profile: Any) -> list[str]:
    heartbeat_owner = str(profile.heartbeat_owner).strip()
    return [
        str(seat)
        for seat in (profile.default_start_seats or [])
        if str(seat).strip() and str(seat).strip() != heartbeat_owner
    ]


def build_workspace_files(
    *,
    project: str,
    profile_path: Path,
    profile: Any,
    feishu_group_id: str,
    workspace_path: Path | None = None,
) -> dict[str, str]:
    template = load_template()
    spec = koder_spec(template, profile)
    seats = roster_seats(profile)
    runtime = runtime_seats(profile)
    backend = backend_seats(profile)
    default_backend = default_backend_start_seats(profile)
    heartbeat_owner = str(profile.heartbeat_owner).strip() or "koder"
    heartbeat_transport = str(getattr(profile, "heartbeat_transport", "openclaw")).strip() or "openclaw"
    active_loop_owner = str(profile.active_loop_owner).strip() or "planner"
    default_notify_target = str(profile.default_notify_target).strip() or active_loop_owner
    return {
        "IDENTITY.md": render_identity(
            project,
            profile_path,
            spec=spec,
            heartbeat_owner=heartbeat_owner,
            notify_target=default_notify_target,
            backend_seats=backend,
        ),
        "MEMORY.md": render_memory(
            project,
            profile_path,
            heartbeat_owner=heartbeat_owner,
            backend_seats=backend,
            default_backend_start_seats=default_backend,
            workspace_path=workspace_path,
        ),
        "USER.md": render_user_profile(),
        "WORKSPACE_CONTRACT.toml": render_contract(
            project,
            profile_path,
            seats,
            runtime_seats=runtime,
            heartbeat_owner=heartbeat_owner,
            heartbeat_transport=heartbeat_transport,
            active_loop_owner=active_loop_owner,
            default_notify_target=default_notify_target,
            backend_seats=backend,
            default_backend_start_seats=default_backend,
            feishu_group_id=feishu_group_id,
        ),
    }


# ---------------------------------------------------------------------------
# Renderers
# ---------------------------------------------------------------------------

def render_identity(
    project: str,
    profile_path: Path,
    *,
    spec: dict,
    heartbeat_owner: str,
    notify_target: str,
    backend_seats: list[str],
) -> str:
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    skills = []
    for skill_path in spec.get("skills", []):
        expanded = skill_path.replace("{CLAWSEAT_ROOT}", str(REPO_ROOT))
        expanded = os.path.expanduser(expanded)
        skills.append(f"- `{Path(expanded).parent.name}`: `{expanded}`")
    backend_list = ", ".join(f"`{seat}`" for seat in backend_seats) if backend_seats else "(none)"
    return f"""# IDENTITY.md — ClawSeat koder

- **Name:** Koder
- **Role:** frontstage-supervisor
- **Seat ID:** {heartbeat_owner}
- **Project:** {project}
- **Profile:** {profile_path}
- **Initialized:** {now}
- **Language:** Chinese
- **Style:** concise, reliable, low-noise

## Core Responsibilities

1. OUTBOUND: translate Memory `decision_payload` JSON into readable Feishu cards.
2. INBOUND: translate button clicks or free text into structured messages for `<project>-memory`.
3. Research: run bounded read-only local KB research when users ask why, compare, or explain.
4. Timeout: apply `default_if_timeout` when a decision expires.
5. Privacy: read `~/.agents/memory/machine/privacy.md` before every broadcast and hard-fail on matches.
6. Routing: resolve Feishu group messages to projects using prefix, recent context, bound projects, default project, then clarification card.

## Boundaries

- Do not make business decisions; Memory owns recommendations.
- Do not dispatch specialists or mutate ClawSeat seats; route work through `{notify_target}`.
- Do not persist private state beyond OpenClaw/plugin-managed runtime state.
- Do not expose file paths, URLs, hashes, command blocks, or internal RFCs in user-facing cards.

## Skills

{chr(10).join(skills)}

## Backend Seats

Only backend seats may be started from this workspace: {backend_list}.
"""


def render_soul(notify_target: str = "planner") -> str:
    return f"""# SOUL.md — koder operating principles

## 核心原则

1. **先问后做** — 在读代码或提方案之前，先通过 clawseat-intake 或 office-hours 澄清需求
2. **用户管是什么，koder 管怎么路由** — 用户定义目标，koder 判断走创作还是工程路径
3. **不越权** — 不做 worker seat 的活，不做 planner 的执行规划
4. **{notify_target} 是唯一的下一跳** — 永远不直接 dispatch 给 specialist seat
5. **代用户激活 gstack skill** — 用户口语化描述需求时（"做个审查"、"推上去"、"想大一点"等），**你负责**翻译成合适的 gstack skill 激活方式。用户不用记 trigger 词，你要记。见 `TOOLS/dispatch.md` 的 intent 映射表。

## 反谄媚规则

- 不说"好的收到""不错的想法" — 对每个回答给判断
- 发现矛盾必须指出
- 含糊词（"优化""改进""更好"）必须追问到具体指标
- 不说"There are many ways" — 选一个推荐并解释为什么

## intake 路由

- 创作类请求（视频/图片/音频/文案/设计）→ clawseat-intake catalog 流程
- 工程/产品类请求（功能/架构/想法/brainstorm）→ 工程诊断流程或 gstack-office-hours
- 判断不了 → 问一个问题让用户选

## 需求澄清 → gstack skill 激活（硬责任）

用户常用口语化语言表达需求，**你不能直接把用户原话当 dispatch objective 照抄**。必须：

1. **先识别 intent**（见 `TOOLS/dispatch.md` 的 intent → skill 映射表）：
   - "做个工程审查" / "架构对吗" → `eng-review`
   - "做大一点" / "格局" → `ceo-review`
   - "设计/UX 评估" → `design-review`
   - "API/DX 审查" → `devex-review`
   - "推上去" / "ship" / "创 PR" → `ship`
   - "合并部署" / "上生产" → `land`
   - "排查 bug" / "为什么挂了" → `investigate`
2. **确认 intent**：用一句话跟用户对齐——`"我理解你想做 [工程审查]，计划让 planner 跑 gstack-plan-eng-review 打磨执行计划。对吗？"`
3. **用 `--intent` 跑 dispatch_task**——让 trigger 词 + skill-refs 自动注入，不靠用户记，也不靠你临场抄 trigger 词

如果用户的原话太模糊 intent 选不出，**不要猜**——用 clawseat-intake 澄清一轮再决定。

## 安全边界

- 不修改 OpenClaw 源码
- 不在 koder 层存储 secrets — 交给 seat 级别的 .env 文件
- 每次 dispatch 都必须有可追溯的 handoff receipt
"""


def render_tools_index(clawseat_root: Path, *, heartbeat_owner: str, notify_target: str = "planner") -> str:
    """TOOLS.md — the index file. Tells koder WHICH sub-file to read for each task."""
    scripts = clawseat_root / "core" / "skills" / "gstack-harness" / "scripts"
    memory_scripts = clawseat_root / "core" / "skills" / "memory-oracle" / "scripts"
    return _render_tool_template(
        "index.md.tmpl",
        {
            "heartbeat_owner": heartbeat_owner,
            "notify_target": notify_target,
            "scripts": scripts,
            "memory_scripts": memory_scripts,
            "clawseat_root": clawseat_root,
        },
    )


def render_tools_dispatch(clawseat_root: Path) -> str:
    scripts = clawseat_root / "core" / "skills" / "gstack-harness" / "scripts"
    shell = clawseat_root / "core" / "shell-scripts"
    return _render_tool_template(
        "dispatch.md.tmpl",
        {
            "scripts": scripts,
            "shell": shell,
        },
    )


def render_tools_project(clawseat_root: Path, *, heartbeat_owner: str, workspace_path: Path | None = None) -> str:
    scripts = clawseat_root / "core" / "skills" / "gstack-harness" / "scripts"
    # workspace_path is the actual workspace this koder is being initialized into
    # (for example, an OpenClaw workspace-<tenant> directory).
    # Embed the resolved path so the snippet reads THIS workspace's contract,
    # not a hardcoded `workspace-koder` that would mis-route for other projects.
    if workspace_path is not None:
        contract_snippet = (
            f"python3 -c \"import pathlib,tomllib; print(tomllib.loads(pathlib.Path("
            f"'{workspace_path}/WORKSPACE_CONTRACT.toml').read_text())['project'])\""
        )
    else:
        # Fallback when workspace_path is not provided: use the script's own location.
        contract_snippet = (
            "python3 -c \"import pathlib,tomllib,sys; "
            "print(tomllib.loads((pathlib.Path(__file__).resolve().parent / 'WORKSPACE_CONTRACT.toml')"
            ".read_text())['project'])\""
        )
    return _render_tool_template(
        "project.md.tmpl",
        {
            "contract_snippet": contract_snippet,
            "clawseat_root": clawseat_root,
            "scripts": scripts,
            "heartbeat_owner": heartbeat_owner,
        },
    )


def render_tools_seat(clawseat_root: Path, *, heartbeat_owner: str, backend_seats: list[str]) -> str:
    scripts = clawseat_root / "core" / "skills" / "gstack-harness" / "scripts"
    admin = clawseat_root / "core" / "scripts" / "agent_admin.py"
    memory_scripts = clawseat_root / "core" / "skills" / "memory-oracle" / "scripts"
    backend_choices = "|".join(backend_seats) if backend_seats else "seat-id"
    backend_list = ", ".join(f"`{seat}`" for seat in backend_seats) if backend_seats else "(none)"
    return _render_tool_template(
        "seat.md.tmpl",
        {
            "backend_list": backend_list,
            "heartbeat_owner": heartbeat_owner,
            "memory_scripts": memory_scripts,
            "scripts": scripts,
            "backend_choices": backend_choices,
            "admin": admin,
        },
    )


def render_tools_memory(clawseat_root: Path, *, heartbeat_owner: str) -> str:
    scripts = clawseat_root / "core" / "skills" / "gstack-harness" / "scripts"
    memory_scripts = clawseat_root / "core" / "skills" / "memory-oracle" / "scripts"
    return _render_tool_template(
        "memory.md.tmpl",
        {
            "memory_scripts": memory_scripts,
            "scripts": scripts,
            "heartbeat_owner": heartbeat_owner,
        },
    )


def render_tools_install(clawseat_root: Path) -> str:
    shell = clawseat_root / "core" / "shell-scripts"
    return _render_tool_template(
        "install.md.tmpl",
        {
            "clawseat_root": clawseat_root,
            "shell": shell,
        },
    )


def render_memory(
    project: str,
    profile_path: Path,
    *,
    heartbeat_owner: str,
    backend_seats: list[str],
    default_backend_start_seats: list[str],
    workspace_path: Path | None,
) -> str:
    """MEMORY.md — render-time snapshot + pointers to SSOT.

    The authoritative seat roster / backend list lives in WORKSPACE_CONTRACT.toml.
    Live status (which tmux session is up, who has been dispatched) must be
    queried at read time; we intentionally do not hardcode it here.
    """
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    default_backend_list = "\n".join(f"- `{s}`" for s in default_backend_start_seats) or "- (none)"
    scripts_dir = "core/skills/gstack-harness/scripts"
    contract_path = (
        workspace_path / "WORKSPACE_CONTRACT.toml"
        if workspace_path is not None
        else Path("<this-workspace>") / "WORKSPACE_CONTRACT.toml"
    )
    return f"""# MEMORY.md — koder project snapshot

## 项目绑定 (render-time snapshot)

- **project:** {project}
- **profile:** {profile_path}
- **initialized:** {now}

Seat roster and backend list are authoritative in `WORKSPACE_CONTRACT.toml`.
Read them there, not here:

```bash
python3 -c "import pathlib,tomllib; d=tomllib.loads(pathlib.Path('{contract_path}').read_text()); print('seats:', d.get('seats'))"
```

## Recommended startup order (render-time suggestion)

{default_backend_list}

## Status

This file is a **render-time snapshot**, not a live state tracker.
For live state, run:

- `python3 <CLAWSEAT_ROOT>/{scripts_dir}/tui_ctl.py --profile <profile> status` — which seats are VISIBLE
- `tmux ls | grep {project}-` — which tmux sessions exist
- `ls ~/.agents/tasks/{project}/patrol/handoffs/` — recent dispatch activity
"""


def render_user_profile() -> str:
    return """# USER.md — operator language profile

detail_level = "intermediate"  # beginner | intermediate | advanced
language = "zh-CN"

## Rendering Guidance

- beginner: add analogies, avoid jargon, explain one tradeoff at a time.
- intermediate: concise Chinese with explicit risks and next action.
- advanced: direct summary, numbers and deltas first, no teaching tone.
"""


def render_agents(
    spec: dict,
    clawseat_root: Path,
    *,
    heartbeat_owner: str,
    backend_seats: list[str],
) -> str:
    skills_section = []
    for skill_path in spec.get("skills", []):
        expanded = skill_path.replace("{CLAWSEAT_ROOT}", str(clawseat_root))
        expanded = os.path.expanduser(expanded)
        name = Path(expanded).parent.name
        skills_section.append(f"- `{name}`: `{expanded}`")

    # B1: drop role_details entries that are pure behavior rules (they live in SOUL.md).
    # Keep operational/contextual items only.
    _BEHAVIOR_KEYWORDS = (
        "never dispatch directly",
        "planner is always the next hop",
        "do not absorb",
        "creative requests",
        "engineering/product requests",
        "clawseat-intake",
        "gstack-office-hours",
        "first classify intent",
    )
    operational_details = []
    for detail in spec.get("role_details", []):
        if any(kw in detail for kw in _BEHAVIOR_KEYWORDS):
            continue
        operational_details.append(f"- {detail}")
    backend_list = ", ".join(f"`{seat}`" for seat in backend_seats) if backend_seats else "(none)"

    return f"""# AGENTS.md — ClawSeat koder workspace

## Role

- **seat_id:** koder
- **role:** frontstage-supervisor
- **tool:** {spec.get('tool', 'claude')}
- **model:** {spec.get('model', 'opus')} (ClawSeat template default — OpenClaw may override at runtime)

## Skills

{chr(10).join(skills_section)}

> Additional OpenClaw-native skills may be symlinked by OpenClaw itself
> (e.g. `acpx-guide`, `capability-evolver`, `openclaw-governance-audit`,
> `skill-vetter`). For the live set run `ls ~/.openclaw/workspace-{heartbeat_owner}/skills/`.

## Operational details

> See SOUL.md for behavior principles (intake routing, anti-sycophancy,
> dispatch-to-planner-only, specialist-work isolation). This section
> covers operational context only.

{chr(10).join(operational_details) if operational_details else '- (no extra operational details)'}

## Authority

- patrol: ✅
- unblock: ✅
- escalation: ✅
- remind active loop owner: ✅
- dispatch: ❌ (planner only — see SOUL.md)
- review: ❌
- verification: ❌
- design: ❌

## Dispatch protocol

- Use `dispatch_task.py` for formal task dispatch (see `TOOLS/dispatch.md` for the command shape)
- Use `notify_seat.py` for ad hoc messages
- Use `send-and-verify.sh` for tmux transport (fallback only)
- Every dispatch must produce a handoff receipt under `~/.agents/tasks/<project>/patrol/handoffs/`
- Only backend seats may be started from this workspace: {backend_list}
  (Starting a seat is setup/provisioning — see `TOOLS/seat.md`. It does not violate the
  "don't absorb specialist work" rule, which applies to dispatched work-items.)
- In OpenClaw mode, the current agent already is `{heartbeat_owner}` — see TOOLS.md 强制规则.
"""


def render_contract(
    project: str,
    profile_path: Path,
    seats: list[str],
    *,
    runtime_seats: list[str],
    heartbeat_owner: str,
    heartbeat_transport: str,
    active_loop_owner: str,
    default_notify_target: str,
    backend_seats: list[str],
    default_backend_start_seats: list[str],
    feishu_group_id: str = "",
) -> str:
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    seat_toml = ", ".join(f'"{s}"' for s in seats)
    runtime_toml = ", ".join(f'"{s}"' for s in runtime_seats)
    backend_toml = ", ".join(f'"{s}"' for s in backend_seats)
    default_backend_toml = ", ".join(f'"{s}"' for s in default_backend_start_seats)
    # D1: contract fingerprint — a 16-char SHA256 hex of the critical fields,
    # so ack_contract and downstream consumers can detect drift without diff'ing.
    fingerprint_source = (
        f"{project}|{profile_path}|{'/'.join(seats)}|{'/'.join(runtime_seats)}|"
        f"{heartbeat_transport}|{feishu_group_id}"
    )
    contract_fingerprint = hashlib.sha256(fingerprint_source.encode("utf-8")).hexdigest()[:16]
    return f"""version = 1
seat_id = "{heartbeat_owner}"
role = "frontstage-supervisor"
transport = "openclaw"
project = "{project}"
profile = "{profile_path}"
initialized_at = "{now}"
contract_fingerprint = "{contract_fingerprint}"
seats = [{seat_toml}]
runtime_seats = [{runtime_toml}]
backend_seats = [{backend_toml}]
default_backend_start_seats = [{default_backend_toml}]
heartbeat_owner = "{heartbeat_owner}"
heartbeat_transport = "{heartbeat_transport}"
active_loop_owner = "{active_loop_owner}"
default_notify_target = "{default_notify_target}"
feishu_group_id = "{feishu_group_id}"
"""


# ---------------------------------------------------------------------------
# Memory seat inject hook deployment (SPEC §5.1 item 12 — B variant)
# ---------------------------------------------------------------------------


_INJECT_TEMPLATE_PATH = (
    CLAWSEAT_ROOT / "core" / "skills" / "memory-oracle" / "inject_memory.sh.template"
)
_INJECT_HOOK_RELATIVE = Path(".claude") / "hooks" / "inject_memory.sh"


def deploy_memory_inject_hook(
    memory_workspace: Path,
    memory_root: Path,
    *,
    dry_run: bool,
) -> Path:
    """Deploy inject_memory.sh into the memory seat workspace.

    Reads inject_memory.sh.template, substitutes __MEMORY_ROOT__ with the
    real absolute path, and writes the result to
    <memory_workspace>/.claude/hooks/inject_memory.sh with mode 755.

    This function is idempotent — safe to call on re-init.

    Args:
        memory_workspace: Path to the memory seat's workspace directory.
        memory_root: Absolute path to ~/.agents/memory (or override).
        dry_run: Print the intended action without writing to disk.

    Returns:
        The target path (even in dry-run mode).
    """
    if not _INJECT_TEMPLATE_PATH.exists():
        raise FileNotFoundError(
            f"inject_memory.sh.template not found: {_INJECT_TEMPLATE_PATH}"
        )

    template = _INJECT_TEMPLATE_PATH.read_text(encoding="utf-8")
    rendered = template.replace("__MEMORY_ROOT__", str(memory_root))

    target = memory_workspace / _INJECT_HOOK_RELATIVE

    if dry_run:
        print(f"would_write: {target} ({len(rendered)} bytes, mode 755)")
        return target

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(rendered, encoding="utf-8")
    try:
        os.chmod(target, 0o755)
    except OSError:
        pass
    print(f"wrote: {target} (mode 755)")
    return target


# ---------------------------------------------------------------------------
# Symlink helpers
# ---------------------------------------------------------------------------

def ensure_skill_symlink(skills_dir: Path, name: str, source: Path, *, dry_run: bool) -> None:
    dest = skills_dir / name
    if dest.is_symlink():
        if dest.resolve() == source.resolve():
            return  # already correct
        if not dry_run:
            dest.unlink()
    elif dest.exists():
        print(f"  skip: {dest} exists as non-symlink", file=sys.stderr)
        return
    if dry_run:
        print(f"  would_link: {dest} -> {source}")
        return
    dest.symlink_to(source)


def install_koder_skills(
    skills_dir: Path,
    clawseat_root: Path,
    *,
    spec: dict | None = None,
    dry_run: bool,
) -> None:
    """Symlink koder's ClawSeat skills into the workspace skills/ dir.

    Skill list is sourced from the gstack-harness template's ``engineers[id=koder].skills``
    field — the SAME source AGENTS.md renders from — so the rendered manifest
    and the on-disk symlinks can never drift. ``spec`` is the koder engineer
    dict produced by ``koder_spec()``; when called standalone we re-load the
    template to fetch it.
    """
    skills_dir.mkdir(parents=True, exist_ok=True)

    if spec is None:
        spec = _find_template_engineer(load_template(), "koder")

    # Each skill entry is a raw path string that may contain {CLAWSEAT_ROOT}
    # or ~ and resolves to a .../SKILL.md; the symlink's source is the skill
    # directory (parent of SKILL.md).
    for raw_skill in spec.get("skills", []):
        expanded = raw_skill.replace("{CLAWSEAT_ROOT}", str(clawseat_root))
        expanded = os.path.expanduser(expanded)
        skill_dir = Path(expanded).parent
        name = skill_dir.name
        if not skill_dir.exists():
            # External skills (gstack, agent skills) may not be installed yet.
            # Skip with a note so the caller can see what's missing.
            print(f"  skip: {name} (source not found: {skill_dir})", file=sys.stderr)
            continue
        ensure_skill_symlink(skills_dir, name, skill_dir, dry_run=dry_run)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    args = parse_args()
    workspace = Path(args.workspace).expanduser().resolve()

    if not workspace.exists():
        print(f"error: workspace does not exist: {workspace}", file=sys.stderr)
        return 1

    # Conflict handling: check for the 6 files init_koder will overwrite.
    conflicts = detect_managed_conflicts(workspace)
    if conflicts and not args.dry_run:
        policy = resolve_conflict_policy(args.on_conflict, conflicts, workspace)
        if policy == "abort":
            print("aborted: workspace untouched.", file=sys.stderr)
            return 2
        if policy == "backup":
            backup_dir = backup_managed_files(workspace, conflicts)
            print(f"backed up {len(conflicts)} file(s) to {backup_dir}")
        elif policy == "overwrite":
            print(f"overwriting {len(conflicts)} file(s) in place")
            for rel in OBSOLETE_FILES:
                target = workspace / rel
                if target.exists() or target.is_symlink():
                    if target.is_dir():
                        continue
                    target.unlink()
            tools_dir = workspace / "TOOLS"
            try:
                tools_dir.rmdir()
            except OSError:
                pass

    profile_path, profile = load_profile_context(args.project, args.profile)
    files = build_workspace_files(
        project=args.project,
        profile_path=profile_path,
        profile=profile,
        feishu_group_id=args.feishu_group_id,
        workspace_path=workspace,
    )

    for filename, content in files.items():
        target = workspace / filename
        if args.dry_run:
            print(f"would_write: {target} ({len(content)} bytes)")
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        print(f"wrote: {target}")

    # Install skill symlinks
    if not args.dry_run:
        print("installing koder skills...")
    install_koder_skills(workspace / "skills", REPO_ROOT, dry_run=args.dry_run)

    # Deploy memory inject hook if --memory-workspace is given (SPEC §5.1 item 12)
    if args.memory_workspace:
        mem_ws = Path(args.memory_workspace).expanduser().resolve()
        mem_root = (
            Path(args.memory_root).expanduser().resolve()
            if args.memory_root
            else real_user_home() / ".agents" / "memory"
        )
        if not args.dry_run:
            print(f"\ndeploying memory inject hook to {mem_ws}...")
        deploy_memory_inject_hook(mem_ws, mem_root, dry_run=args.dry_run)

    if not args.dry_run:
        print(f"\nkoder initialized for project '{args.project}' at {workspace}")
        print("next: run bootstrap, then start planner")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
