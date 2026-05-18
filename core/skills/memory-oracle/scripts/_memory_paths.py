#!/usr/bin/env python3
"""
_memory_paths.py — directory layout constants and ID generation for memory-oracle.

Layout (target state, SPEC §3):
  ~/.agents/memory/
  ├── machine/                           ← scanner outputs
  │   └── current_context.json           ← current project pointer + last_refresh_ts
  ├── projects/<project-name>/
  │   ├── decisions/<id>.json
  │   ├── deliveries/<id>.json
  │   ├── issues/<id>.json
  │   ├── findings/<id>.json
  │   └── reflections.jsonl
  ├── shared/
  │   ├── library_knowledge/<topic>.json
  │   ├── patterns/<pattern-id>.json
  │   └── examples/<lib>-<pattern>.json
  ├── research/<topic>/
  ├── events.log
  └── responses/<query-id>.json
"""
from __future__ import annotations

import hashlib
import os
import time
from pathlib import Path


def _real_user_home() -> Path:
    import pwd

    try:
        real = Path(pwd.getpwuid(os.getuid()).pw_dir)
        if real.is_dir():
            return real
    except (KeyError, OSError):  # silent-ok: pwd lookup unavailable; fall back to HOME env or Path.home()
        pass
    env_home = os.environ.get("HOME")
    if env_home:
        return Path(env_home)
    return Path.home()


HOME = _real_user_home()
MEMORY_ROOT = HOME / ".agents" / "memory"

MACHINE_DIR = MEMORY_ROOT / "machine"
PROJECTS_DIR = MEMORY_ROOT / "projects"
SHARED_DIR = MEMORY_ROOT / "shared"
RESEARCH_DIR = MEMORY_ROOT / "research"
EVENTS_LOG = MEMORY_ROOT / "events.log"
RESPONSES_DIR = MEMORY_ROOT / "responses"

# Filename for per-project reflection JSONL (SPEC §3)
REFLECTIONS_FILE = "reflections.jsonl"

# Subdirectories under projects/<name>/ for each fact kind
KIND_SUBDIRS: dict[str, str] = {
    "decision": "decisions",
    "delivery": "deliveries",
    "issue": "issues",
    "finding": "findings",
}

# Subdirectories under shared/ for each fact kind
SHARED_KIND_SUBDIRS: dict[str, str] = {
    "library_knowledge": "library_knowledge",
    "pattern": "patterns",
    "example": "examples",
}


def project_dir(project: str) -> Path:
    """Return the directory for a named project."""
    return PROJECTS_DIR / project


def reflections_path(project: str, *, memory_root: Path | None = None) -> Path:
    """Return the reflections JSONL path for a project (SPEC §3).

    Write hooks are M5's responsibility; this constant is registered here so
    M3/M5 can import it without re-deriving the layout.
    """
    root = memory_root if memory_root is not None else MEMORY_ROOT
    return root / "projects" / project / REFLECTIONS_FILE


def events_log_path(*, memory_root: Path | None = None) -> Path:
    """Return the global events.log JSONL path (SPEC §3).

    Write hooks are M5's responsibility; registered here for importability.
    """
    root = memory_root if memory_root is not None else MEMORY_ROOT
    return root / "events.log"


# ── M2 project-scanner path helpers (SPEC §3, D15) ───────────────────────────
# Each helper returns the canonical kind-named file path under projects/<p>/.
# Files are named <kind>.json (one file per kind per project, full-rebuild policy).


def dev_env_path(project: str, *, memory_root: Path | None = None) -> Path:
    """Return projects/<p>/dev_env.json — shallow-depth flat summary."""
    root = memory_root if memory_root is not None else MEMORY_ROOT
    return root / "projects" / project / "dev_env.json"


def runtime_path(project: str, *, memory_root: Path | None = None) -> Path:
    """Return projects/<p>/runtime.json — language/deps detector output."""
    root = memory_root if memory_root is not None else MEMORY_ROOT
    return root / "projects" / project / "runtime.json"


def tests_path(project: str, *, memory_root: Path | None = None) -> Path:
    """Return projects/<p>/tests.json — test-framework detector output."""
    root = memory_root if memory_root is not None else MEMORY_ROOT
    return root / "projects" / project / "tests.json"


def deploy_path(project: str, *, memory_root: Path | None = None) -> Path:
    """Return projects/<p>/deploy.json — deploy-config detector output."""
    root = memory_root if memory_root is not None else MEMORY_ROOT
    return root / "projects" / project / "deploy.json"


def ci_path(project: str, *, memory_root: Path | None = None) -> Path:
    """Return projects/<p>/ci.json — CI/CD detector output."""
    root = memory_root if memory_root is not None else MEMORY_ROOT
    return root / "projects" / project / "ci.json"


def lint_path(project: str, *, memory_root: Path | None = None) -> Path:
    """Return projects/<p>/lint.json — lint/format detector output."""
    root = memory_root if memory_root is not None else MEMORY_ROOT
    return root / "projects" / project / "lint.json"


def structure_path(project: str, *, memory_root: Path | None = None) -> Path:
    """Return projects/<p>/structure.json — repo-structure detector output."""
    root = memory_root if memory_root is not None else MEMORY_ROOT
    return root / "projects" / project / "structure.json"


def env_templates_path(project: str, *, memory_root: Path | None = None) -> Path:
    """Return projects/<p>/env_templates.json — env-template detector output (deep only)."""
    root = memory_root if memory_root is not None else MEMORY_ROOT
    return root / "projects" / project / "env_templates.json"


# Mapping: M2 kind → path helper for use in scan_project.py
M2_KIND_PATH_HELPERS: dict[str, object] = {
    "dev_env": dev_env_path,
    "runtime": runtime_path,
    "tests": tests_path,
    "deploy": deploy_path,
    "ci": ci_path,
    "lint": lint_path,
    "structure": structure_path,
    "env_templates": env_templates_path,
}


def generate_id(kind: str, project: str, content: str) -> str:
    """Generate a stable fact ID: <kind>-<project|shared>-<8-char hash>.

    Includes time.time_ns() so two writes of the same title don't collide.
    """
    ns = "shared" if project == "_shared" else project
    payload = f"{kind}:{ns}:{content}:{time.time_ns()}"
    digest = hashlib.sha256(payload.encode()).hexdigest()[:8]
    return f"{kind}-{ns}-{digest}"


def fact_path(kind: str, project: str, fact_id: str, *, memory_root: Path | None = None) -> Path:
    """Resolve where a fact JSON file should be stored on disk.

    Args:
        kind: Fact kind (decision, delivery, ...).
        project: Project name or '_shared'.
        fact_id: The generated fact ID.
        memory_root: Override for ~/.agents/memory (used in tests).
    """
    root = memory_root if memory_root is not None else MEMORY_ROOT

    if project == "_shared":
        subdir_name = SHARED_KIND_SUBDIRS.get(kind, f"{kind}s")
        return root / "shared" / subdir_name / f"{fact_id}.json"

    # reflection → per-project JSONL (SPEC §3; write appended by M5)
    if kind == "reflection":
        return reflections_path(project, memory_root=memory_root)

    subdir_name = KIND_SUBDIRS.get(kind)
    if subdir_name:
        return root / "projects" / project / subdir_name / f"{fact_id}.json"

    # Other kinds without a dedicated subdir go at project root
    return root / "projects" / project / f"{fact_id}.json"
