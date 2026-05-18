"""ClawSeat skill registry — load, query, and validate the skill SSOT.

The registry lives in ``core/skill_registry.toml``.  Every skill referenced
by any template or install script must have an entry there.

This module is a pure library — the CLI lives in ``core/scripts/skill_manager.py``.
"""
from __future__ import annotations

import os
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Import canonical real-HOME resolver (SSOT at core/lib/real_home.py). When
# this module is imported from a seat sandbox HOME, os.path.expanduser and
# Path.home() return the sandbox tree — so any "~" in a skill-registry
# path resolves against `<HOME>/.agents/runtime/identities/.../home/`
# instead of the operator's real home, and every gstack-skills lookup
# misses. R1-VERIFY flagged this as BLOCKING because builder-1's R1-HOME
# pass missed this file.
_REAL_HOME_LIB = Path(__file__).resolve().parent / "lib"
if str(_REAL_HOME_LIB) not in sys.path:
    sys.path.insert(0, str(_REAL_HOME_LIB))
from real_home import real_user_home as _real_user_home_ssot  # noqa: E402


def _expand_tilde(value: str) -> str:
    """Expand a leading ~ against the operator's real HOME (pwd-based).

    Mirrors `os.path.expanduser(value)` semantics but uses the SSOT real-HOME
    resolver so results do NOT depend on $HOME (which is the sandbox HOME
    inside seat runtimes).
    """
    if value.startswith("~/") or value == "~":
        return str(_real_user_home_ssot()) + value[1:]
    return value


# ── Path constants ──────────────────────────────────────────────────

REPO_ROOT = Path(
    os.environ.get("CLAWSEAT_ROOT", str(Path(__file__).resolve().parents[1]))
)

DEFAULT_REGISTRY_PATH = REPO_ROOT / "core" / "skill_registry.toml"

# Canonical prefix the registry and templates use for gstack skills. If an
# operator cloned gstack to a non-canonical path, they export
# GSTACK_SKILLS_ROOT and expand_skill_path() below rewrites the prefix.
_CANONICAL_GSTACK_PREFIX = "~/.gstack/repos/gstack/.agents/skills"


def _resolve_gstack_skills_root() -> str | None:
    """Return the operator-provided GSTACK_SKILLS_ROOT override, or None.

    Refuses relative paths — they silently resolve against cwd and produce
    mystery "skill not found" errors at bootstrap / start_seat time. Emits
    a stderr warning and falls back to the canonical default when the env
    var is non-absolute.

    Shared with core/skills/gstack-harness/scripts/dispatch_task.py's
    identical resolver — keep the two in sync if either changes.
    """
    import sys as _sys
    env = os.environ.get("GSTACK_SKILLS_ROOT", "").strip()
    if not env:
        return None
    expanded = Path(env).expanduser()
    if not expanded.is_absolute():
        _sys.stderr.write(
            f"warning: GSTACK_SKILLS_ROOT={env!r} is not absolute; "
            f"ignoring and falling back to ~/.gstack/repos/gstack/.agents/skills.\n"
            f"         Set it to an absolute path like "
            f"{expanded.resolve()} to take effect.\n"
        )
        return None
    return str(expanded)


# Source-specific install hints shown when a skill is missing.
SOURCE_INSTALL_HINTS: dict[str, str] = {
    "bundled": "Ensure the ClawSeat repo is intact: git status / git checkout",
    "gstack": (
        "Install gstack at the canonical path: "
        "git clone --single-branch --depth 1 https://github.com/garrytan/gstack.git "
        "~/.gstack/repos/gstack && cd ~/.gstack/repos/gstack && ./setup\n"
        "    (Or, if gstack is already installed elsewhere, export "
        "GSTACK_SKILLS_ROOT=/absolute/path/to/.agents/skills and re-run.)"
    ),
    "agent": "Install lark-cli skills: see lark-cli skill install docs or copy from a peer machine",
    "openclaw-migrated": "Install migrated OpenClaw skills under ~/.agents/skills or sync them from the operator machine.",
}


# ── Data model ──────────────────────────────────────────────────────

@dataclass(slots=True)
class SkillEntry:
    """One skill in the registry."""

    name: str
    source: str  # "bundled" | "gstack" | "agent"
    path: str  # raw path with {CLAWSEAT_ROOT} / ~ placeholders
    required: bool
    roles: list[str] = field(default_factory=list)
    description: str = ""
    templates: list[str] = field(default_factory=list)  # empty = all templates
    entry_skill: bool = False


@dataclass(slots=True)
class SkillCheckItem:
    """Result of checking a single skill."""

    name: str
    source: str
    expanded_path: str
    exists: bool
    required: bool
    message: str
    fix_hint: str = ""


@dataclass(slots=True)
class SkillCheckResult:
    """Aggregated result of validating the full registry or a subset."""

    items: list[SkillCheckItem]

    @property
    def all_present(self) -> bool:
        return all(item.exists for item in self.items)

    @property
    def required_missing(self) -> list[SkillCheckItem]:
        return [i for i in self.items if not i.exists and i.required]

    @property
    def optional_missing(self) -> list[SkillCheckItem]:
        return [i for i in self.items if not i.exists and not i.required]

    @property
    def present(self) -> list[SkillCheckItem]:
        return [i for i in self.items if i.exists]

    def summary_lines(self) -> list[str]:
        lines: list[str] = []
        for item in self.items:
            if item.exists:
                lines.append(f"  [ok] {item.name}: {item.expanded_path}")
            else:
                tag = "BLOCKED" if item.required else "MISSING"
                lines.append(f"  [{tag}] {item.name}: {item.expanded_path}")
                if item.fix_hint:
                    lines.append(f"    -> {item.fix_hint}")
        req_missing = self.required_missing
        opt_missing = self.optional_missing
        if req_missing:
            lines.insert(0, f"skill_check: BLOCKED ({len(req_missing)} required skill(s) missing)")
        elif opt_missing:
            lines.insert(0, f"skill_check: WARNING ({len(opt_missing)} optional skill(s) missing)")
        else:
            lines.insert(0, f"skill_check: PASS ({len(self.items)} skills verified)")
        return lines


# ── Loaders ─────────────────────────────────────────────────────────

def _parse_entry(raw: dict[str, Any]) -> SkillEntry:
    return SkillEntry(
        name=str(raw.get("name", "")).strip(),
        source=str(raw.get("source", "bundled")).strip(),
        path=str(raw.get("path", "")).strip(),
        required=bool(raw.get("required", False)),
        roles=list(raw.get("roles", [])),
        description=str(raw.get("description", "")).strip(),
        templates=list(raw.get("templates", [])),
        entry_skill=bool(raw.get("entry_skill", False)),
    )


def load_registry(registry_path: Path | None = None) -> list[SkillEntry]:
    """Parse the skill registry TOML and return a list of SkillEntry."""
    path = registry_path or DEFAULT_REGISTRY_PATH
    with open(path, "rb") as f:
        data = tomllib.load(f)
    return [_parse_entry(raw) for raw in data.get("skills", [])]


# ── Path helpers ────────────────────────────────────────────────────

def expand_skill_path(raw: str) -> Path:
    """Expand ``{CLAWSEAT_ROOT}``, ``~``, and optional ``GSTACK_SKILLS_ROOT``.

    If the caller has exported ``GSTACK_SKILLS_ROOT`` (because they cloned
    gstack somewhere other than the canonical ``~/.gstack/repos/gstack``),
    any registry path that begins with the canonical gstack-skills prefix
    is rewritten to the operator-supplied root. This is the single seam
    that makes skill_registry.toml portable without rewriting its 20+
    hardcoded gstack entries.
    """
    expanded = raw.replace("{CLAWSEAT_ROOT}", str(REPO_ROOT))
    gstack_override = _resolve_gstack_skills_root()
    if gstack_override:
        # Match both the literal `~/...` form and an already-expanded home.
        # `_expand_tilde` uses real_user_home() so a sandbox-HOME caller
        # still produces the operator's real canonical prefix for comparison.
        canonical_expanded = _expand_tilde(_CANONICAL_GSTACK_PREFIX)
        if expanded.startswith(_CANONICAL_GSTACK_PREFIX):
            expanded = gstack_override + expanded[len(_CANONICAL_GSTACK_PREFIX):]
        elif expanded.startswith(canonical_expanded):
            expanded = gstack_override + expanded[len(canonical_expanded):]
    # Final expansion: route `~` through real_user_home, not $HOME.
    return Path(_expand_tilde(expanded))


def resolve_skill(entry: SkillEntry) -> tuple[Path, bool]:
    """Return (expanded_path, exists_on_disk)."""
    p = expand_skill_path(entry.path)
    return p, p.exists()


# ── Filters ─────────────────────────────────────────────────────────

def skills_for_source(entries: list[SkillEntry], source: str) -> list[SkillEntry]:
    """Filter entries by source type (bundled / gstack / agent)."""
    return [e for e in entries if e.source == source]


def skills_for_role(entries: list[SkillEntry], role: str) -> list[SkillEntry]:
    """Filter entries by role name."""
    return [e for e in entries if role in e.roles]


def skills_for_template(entries: list[SkillEntry], template_name: str) -> list[SkillEntry]:
    """Filter entries relevant to a template (empty templates list = all templates)."""
    return [e for e in entries if not e.templates or template_name in e.templates]


def external_skills(entries: list[SkillEntry]) -> list[SkillEntry]:
    """Return all non-bundled skills (gstack + agent)."""
    return [e for e in entries if e.source != "bundled"]


# ── Validation ──────────────────────────────────────────────────────

def _check_one(entry: SkillEntry) -> SkillCheckItem:
    expanded, exists = resolve_skill(entry)
    if exists:
        return SkillCheckItem(
            name=entry.name,
            source=entry.source,
            expanded_path=str(expanded),
            exists=True,
            required=entry.required,
            message=f"{entry.name} ({entry.source}): ok",
        )
    return SkillCheckItem(
        name=entry.name,
        source=entry.source,
        expanded_path=str(expanded),
        exists=False,
        required=entry.required,
        message=f"{entry.name} ({entry.source}): not found at {expanded}",
        fix_hint=SOURCE_INSTALL_HINTS.get(entry.source, ""),
    )


def validate_all(
    entries: list[SkillEntry] | None = None,
    *,
    registry_path: Path | None = None,
    role: str | None = None,
    source: str | None = None,
    active_roles: set[str] | None = None,
) -> SkillCheckResult:
    """Validate skill paths.  Returns a SkillCheckResult.

    Accepts optional filters:
    - *role*: check only skills for a specific role
    - *source*: check only skills from a specific source layer
    - *active_roles*: if provided, a skill marked required=true is only treated
      as required when its roles list is empty (universal) OR overlaps active_roles.
      Skills whose roles are non-empty and disjoint from active_roles are downgraded
      to optional — they belong to seat types not present in this profile.
      Pass None (default) to preserve the existing global required=true behaviour.
    """
    if entries is None:
        entries = load_registry(registry_path)
    if role:
        entries = skills_for_role(entries, role)
    if source:
        entries = skills_for_source(entries, source)

    if active_roles is not None:
        # Downgrade required skills whose roles don't intersect active_roles.
        # Skills with roles=[] are always applicable (universal).
        adjusted: list[SkillEntry] = []
        for e in entries:
            if e.required and e.roles and not (set(e.roles) & active_roles):
                from dataclasses import replace
                e = replace(e, required=False)
            adjusted.append(e)
        entries = adjusted

    items = [_check_one(e) for e in entries]
    return SkillCheckResult(items=items)


# ── Template diff ───────────────────────────────────────────────────

def diff_template(template_name: str, entries: list[SkillEntry] | None = None) -> dict[str, list[str]]:
    """Compare a template's skill assignments against the registry.

    Returns ``{"unregistered": [...], "uncovered": [...]}``:
    - *unregistered*: skill paths in the template but not in the registry
    - *uncovered*: registry skills for the template's roles that the template doesn't assign
    """
    if entries is None:
        entries = load_registry()

    # Load the template
    tpl_path = REPO_ROOT / "core" / "templates" / template_name / "template.toml"
    if not tpl_path.exists():
        return {"error": [f"template not found: {tpl_path}"]}

    with open(tpl_path, "rb") as f:
        tpl = tomllib.load(f)

    # Collect all skill paths used in the template
    tpl_skill_paths: set[str] = set()
    tpl_roles: set[str] = set()
    for eng in tpl.get("engineers", []):
        role = str(eng.get("role", "")).strip()
        if role:
            tpl_roles.add(role)
        for skill in eng.get("skills", []):
            tpl_skill_paths.add(str(skill).strip())

    # Registry skill paths (expanded for comparison)
    registry_by_path: dict[str, SkillEntry] = {}
    for e in entries:
        registry_by_path[e.path] = e

    # 1. Skills in template but not in registry
    unregistered = [p for p in sorted(tpl_skill_paths) if p not in registry_by_path]

    # 2. Registry skills for these roles that template doesn't use
    relevant = [e for e in entries if any(r in tpl_roles for r in e.roles)]
    uncovered = [e.name for e in relevant if e.path not in tpl_skill_paths and not e.entry_skill]

    return {"unregistered": unregistered, "uncovered": uncovered}
