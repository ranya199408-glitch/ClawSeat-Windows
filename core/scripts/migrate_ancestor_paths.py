#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import platform
import re
import shutil
import subprocess
from datetime import datetime
from pathlib import Path


SEAT_ROLE_MIGRATIONS: list[dict[str, str]] = []

# Ref doc moves keep old core/references/* symlinks for the same 6-month
# compatibility window. Install-time project migrations can consult this table
# when rewriting durable task receipts, local notes, or generated docs.
REF_DOC_PATH_MIGRATIONS = [
    {
        "old": "core/references/communication-protocol.md",
        "new": "core/skills/gstack-harness/references/communication-protocol.md",
        "alias_until": "2026-10-28",
        "type": "ref_doc_path",
    },
    {
        "old": "core/references/collaboration-rules.md",
        "new": "core/skills/planner/references/collaboration-rules.md",
        "alias_until": "2026-10-28",
        "type": "ref_doc_path",
    },
    {
        "old": "core/references/memory-operations-policy.md",
        "new": "core/skills/memory-oracle/references/memory-operations-policy.md",
        "alias_until": "2026-10-28",
        "type": "ref_doc_path",
    },
    {
        "old": "core/references/workflow-doc-schema.md",
        "new": "core/skills/planner/references/workflow-doc-schema.md",
        "alias_until": "2026-10-28",
        "type": "ref_doc_path",
    },
    {
        "old": "core/references/workflow-collaboration-template.md",
        "new": "core/skills/planner/references/workflow-collaboration-template.md",
        "alias_until": "2026-10-28",
        "type": "ref_doc_path",
    },
    {
        "old": "core/references/max-iterations-policy.md",
        "new": "core/skills/planner/references/max-iterations-policy.md",
        "alias_until": "2026-10-28",
        "type": "ref_doc_path",
    },
    {
        "old": "core/references/context-management-template.md",
        "new": "core/skills/clawseat-memory/references/context-management-template.md",
        "alias_until": "2026-10-28",
        "type": "ref_doc_path",
    },
    {
        "old": "core/references/planner-context-policy.md",
        "new": "core/skills/planner/references/planner-context-policy.md",
        "alias_until": "2026-10-28",
        "type": "ref_doc_path",
    },
]


def real_home() -> Path:
    override = os.environ.get("CLAWSEAT_REAL_HOME", "").strip()
    if override:
        return Path(override).expanduser()
    return Path.home()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Migrate v1/v2 ancestor path names to memory/QA path names."
    )
    parser.add_argument("--project", action="append", help="Project name to migrate. May be repeated.")
    parser.add_argument("--all", action="store_true", help="Migrate every project under ~/.agents/tasks.")
    return parser.parse_args()


def project_names(home: Path, args: argparse.Namespace) -> list[str]:
    names = [name for value in (args.project or []) for name in value.split(",") if name.strip()]
    if names:
        return sorted(dict.fromkeys(names))
    tasks_root = home / ".agents" / "tasks"
    if args.all and tasks_root.is_dir():
        return sorted(path.name for path in tasks_root.iterdir() if path.is_dir())
    return []


def symlink_alias(alias: Path, target: Path, changed: list[str]) -> None:
    if alias.is_symlink():
        return
    if alias.exists():
        backup = alias.with_name(alias.name + ".deprecated")
        suffix = 1
        while backup.exists():
            backup = alias.with_name(f"{alias.name}.deprecated.{suffix}")
            suffix += 1
        alias.rename(backup)
        changed.append(f"backup {alias} -> {backup}")
    try:
        alias.symlink_to(target.name)
        changed.append(f"symlink {alias} -> {target.name}")
    except OSError as exc:
        changed.append(f"warn symlink failed {alias}: {exc}")


def rename_with_alias(old: Path, new: Path, changed: list[str]) -> None:
    if old.is_symlink():
        return
    if old.exists() and not new.exists():
        new.parent.mkdir(parents=True, exist_ok=True)
        old.rename(new)
        changed.append(f"rename {old} -> {new}")
    if new.exists() and not old.exists():
        symlink_alias(old, new, changed)
    elif new.exists() and old.exists() and not old.is_symlink():
        symlink_alias(old, new, changed)


def run_launchctl(args: list[str], changed: list[str]) -> None:
    if platform.system() != "Darwin":
        return
    try:
        subprocess.run(["launchctl", *args], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError as exc:
        changed.append(f"warn launchctl {' '.join(args)} failed: {exc}")


def migrate_launch_agent(home: Path, project: str, changed: list[str]) -> None:
    launch_agents = home / "Library" / "LaunchAgents"
    old_label = f"com.clawseat.{project}.ancestor-patrol"
    new_label = f"com.clawseat.{project}.patrol"
    old_path = launch_agents / f"{old_label}.plist"
    new_path = launch_agents / f"{new_label}.plist"

    if old_path.exists() and not old_path.is_symlink():
        run_launchctl(["bootout", f"gui/{os.getuid()}/{old_label}"], changed)
        if not new_path.exists():
            old_path.rename(new_path)
            changed.append(f"rename {old_path} -> {new_path}")
        else:
            symlink_alias(old_path, new_path, changed)
    if new_path.exists():
        text = new_path.read_text(encoding="utf-8")
        updated = text.replace(old_label, new_label).replace(
            "session-name ancestor --project", "session-name memory --project"
        ).replace(
            "--project '{PROJECT}' ancestor", "--project '{PROJECT}' memory"
        )
        if updated != text:
            new_path.write_text(updated, encoding="utf-8")
            changed.append(f"patch {new_path}")
        symlink_alias(old_path, new_path, changed)
        run_launchctl(["bootstrap", f"gui/{os.getuid()}", str(new_path)], changed)


def patch_profile(path: Path, changed: list[str]) -> None:
    if not path.exists():
        return
    if migrate_install_profile_seats(path):
        changed.append(f"patch install profile seats {path}")
    original = path.read_text(encoding="utf-8")
    updated = original.replace('active_loop_owner = "planner"', 'active_loop_owner = "memory"')
    updated = updated.replace('default_notify_target = "planner"', 'default_notify_target = "memory"')
    if updated != original:
        path.write_text(updated, encoding="utf-8")
        changed.append(f"patch {path}")


_PROFILE_LIST_KEYS = frozenset({
    "seats",
    "materialized_seats",
    "bootstrap_seats",
    "heartbeat_seats",
})
_PROFILE_LIST_RE = re.compile(r"^(?P<prefix>\s*(?P<key>[A-Za-z_]+)\s*=\s*)\[(?P<body>[^\]]*)\](?P<suffix>\s*(?:#.*)?)$")
_PROFILE_STRING_RE = re.compile(r'"([^"]*)"')


def _backup_profile(path: Path) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = path.with_name(f"{path.name}.bak.{stamp}")
    suffix = 1
    while backup.exists():
        backup = path.with_name(f"{path.name}.bak.{stamp}.{suffix}")
        suffix += 1
    shutil.copy2(path, backup)
    return backup


def _normalize_install_profile_seats(values: list[str]) -> list[str]:
    renamed = {"builder-1": "builder", "reviewer-1": "reviewer"}
    out: list[str] = []
    for value in values:
        if value == "koder":
            continue
        normalized = renamed.get(value, value)
        if normalized not in out:
            out.append(normalized)
    return out


def _render_toml_list(values: list[str]) -> str:
    return "[" + ", ".join(f'"{value}"' for value in values) + "]"


def migrate_install_profile_seats(profile_path: Path) -> bool:
    """Update install-profile-dynamic.toml seat lists from v0.7 to v2.

    This is intentionally text-preserving: it only rewrites direct assignment
    lines for known seat-list keys and heartbeat_owner. TOML tables such as
    [seat_overrides.<seat>] are left byte-for-byte intact.
    """
    if not profile_path.exists():
        return False

    original = profile_path.read_text(encoding="utf-8")
    changed = False
    output: list[str] = []

    for line in original.splitlines(keepends=True):
        newline = ""
        body = line
        if body.endswith("\n"):
            newline = "\n"
            body = body[:-1]

        stripped = body.strip()
        if stripped.startswith("heartbeat_owner"):
            updated = re.sub(r'^(?P<prefix>\s*heartbeat_owner\s*=\s*)".*?"', r'\g<prefix>""', body)
            if updated != body:
                changed = True
            output.append(updated + newline)
            continue

        match = _PROFILE_LIST_RE.match(body)
        if match and match.group("key") in _PROFILE_LIST_KEYS:
            values = _PROFILE_STRING_RE.findall(match.group("body"))
            normalized = _normalize_install_profile_seats(values)
            rendered = f"{match.group('prefix')}{_render_toml_list(normalized)}{match.group('suffix')}"
            if rendered != body:
                changed = True
            output.append(rendered + newline)
            continue

        output.append(line)

    if not changed:
        return False

    _backup_profile(profile_path)
    profile_path.write_text("".join(output), encoding="utf-8")
    return True


def migrate_toml_seat_roles(path: Path) -> bool:
    if not path.exists():
        return False
    original = path.read_text(encoding="utf-8")
    changed = False
    output: list[str] = []

    for line in original.splitlines(keepends=True):
        newline = ""
        body = line
        if body.endswith("\n"):
            newline = "\n"
            body = body[:-1]

        table_updated = body
        if table_updated != body:
            changed = True
            output.append(table_updated + newline)
            continue

        match = _PROFILE_LIST_RE.match(body)
        if match and match.group("key") in {"engineers", "monitor_engineers", "seat_order"}:
            values = _PROFILE_STRING_RE.findall(match.group("body"))
            normalized = _normalize_install_profile_seats(values)
            rendered = f"{match.group('prefix')}{_render_toml_list(normalized)}{match.group('suffix')}"
            if rendered != body:
                changed = True
            output.append(rendered + newline)
            continue

        output.append(line)

    if not changed:
        return False
    _backup_profile(path)
    path.write_text("".join(output), encoding="utf-8")
    return True


def migrate_project(home: Path, project: str) -> list[str]:
    changed: list[str] = []
    tasks_root = home / ".agents" / "tasks" / project
    handoffs = tasks_root / "patrol" / "handoffs"

    rename_with_alias(handoffs / "ancestor-bootstrap.md", handoffs / "memory-bootstrap.md", changed)
    rename_with_alias(handoffs / "ancestor-kickoff.txt", handoffs / "memory-kickoff.txt", changed)
    rename_with_alias(tasks_root / "ancestor-provider.env", tasks_root / "memory-provider.env", changed)
    rename_with_alias(
        tasks_root / "ancestor-provider-decision.md",
        tasks_root / "memory-provider-decision.md",
        changed,
    )
    migrate_launch_agent(home, project, changed)

    profiles = home / ".agents" / "profiles"
    patch_profile(profiles / f"{project}-profile-dynamic.toml", changed)
    project_toml = home / ".agents" / "projects" / project / "project.toml"
    if migrate_toml_seat_roles(project_toml):
        changed.append(f"patch seat role aliases {project_toml}")
    return changed


def main() -> int:
    home = real_home()
    args = parse_args()
    names = project_names(home, args)
    if not names:
        print("migrate_ancestor_paths: no projects selected")
        return 0
    for project in names:
        changed = migrate_project(home, project)
        if changed:
            print(f"migrate_ancestor_paths: {project}")
            for item in changed:
                print(f"  {item}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
