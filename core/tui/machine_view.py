"""Machine-layer read-only view — the other half of §9's TUI surface.

Shows what ~/.clawseat/machine.toml declares today:
  - the memory singleton (role / tool / auth / provider / monitor state)
  - every OpenClaw tenant + which project it's currently bound to

Consumes: machine_config.load_machine() (Phase 1 deliverable per §9).
Produces: nothing — read-only. Edits go through dedicated CLI commands
(`agent-admin machine memory edit`, `agent-admin project koder-bind`).

Invocation:

    python3 -m core.tui.machine_view              # live view
    python3 -m core.tui.machine_view --json       # structured output
    python3 -m core.tui.machine_view --sample     # deprecated; real engine only
"""
from __future__ import annotations

import argparse
import json
import sys
import textwrap
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CORE_LIB = str(_REPO_ROOT / "core" / "lib")
if _CORE_LIB not in sys.path:
    sys.path.insert(0, _CORE_LIB)

# ─────────────────────────────────────────────────────────────────────
# Engine adapter.
# ─────────────────────────────────────────────────────────────────────

from machine_config import load_machine, list_openclaw_tenants, validate_tenant  # noqa: E402
from tmux import tmux_session_alive as _tmux_has_session  # noqa: E402

USE_REAL_ENGINE = True


def _read_tenant_binding(tenant: Any) -> str | None:
    """Peek at ~/.openclaw/workspace-<name>/WORKSPACE_CONTRACT.toml to find the
    project this tenant is currently bound to.

    Returns None if binding cannot be determined (workspace absent / no contract).
    This is a READ-ONLY view — never write.
    """
    ws = Path(tenant.workspace).expanduser()
    contract = ws / "WORKSPACE_CONTRACT.toml"
    if not contract.is_file():
        return None
    try:
        try:
            import tomllib
        except ImportError:
            import tomli as tomllib  # type: ignore
        data = tomllib.loads(contract.read_text())
        project = data.get("project") or data.get("bound_project")
        if isinstance(project, str) and project.strip():
            return project.strip()
    except Exception:  # noqa: BLE001 silent-ok: contract read is best-effort; show None on any parse error
        return None
    return None


# ─────────────────────────────────────────────────────────────────────
# Rendering
# ─────────────────────────────────────────────────────────────────────

def _header(title: str) -> str:
    bar = "─" * (len(title) + 4)
    return f"┌{bar}┐\n│  {title}  │\n└{bar}┘"


def _render_memory(machine: Any) -> str:
    mem = machine.memory
    # v1 LEGACY (M4 remove): retired global memory session "machine-memory-claude".
    session_name = "-".join(("machine", "memory", "claude"))
    # Back-compat: v1 used `install-memory-claude`; show whichever is alive.
    alive_session = None
    for candidate in (session_name, "install-memory-claude", "memory-claude"):
        if _tmux_has_session(candidate):
            alive_session = candidate
            break
    status = f"alive ({alive_session})" if alive_session else "not running"

    lines = [
        _header("memory (machine singleton)"),
        f"  role           {mem.role}",
        f"  tool           {mem.tool}",
        f"  auth_mode      {mem.auth_mode}",
        f"  provider       {mem.provider}",
        f"  model          {getattr(mem, 'model', '—')}",
        f"  runtime_dir    {mem.runtime_dir}",
        f"  storage_root   {mem.storage_root}",
        f"  monitor        {'on' if mem.monitor else 'off'}",
        f"  tmux           {status}",
    ]
    return "\n".join(lines)


def _render_tenants(machine: Any) -> str:
    tenants = list_openclaw_tenants(machine)
    if not tenants:
        return _header("OpenClaw tenants") + "\n  (none declared)"
    rows: list[list[str]] = [
        ["name", "workspace", "bound project", "health"]
    ]
    for t in tenants:
        ok, detail = validate_tenant(machine, t.name)
        bound = _read_tenant_binding(t) or "—"
        health = "ok" if ok else f"error: {detail}"
        rows.append([t.name, str(t.workspace), bound, health])
    widths = [max(len(r[i]) for r in rows) for i in range(len(rows[0]))]
    lines = [_header("OpenClaw tenants (koder slots)")]
    for i, row in enumerate(rows):
        line = "  " + "  ".join(c.ljust(widths[j]) for j, c in enumerate(row))
        lines.append(line)
        if i == 0:
            lines.append("  " + "  ".join("-" * w for w in widths))
    return "\n".join(lines)


def _render_machine(machine: Any) -> str:
    out = [
        _render_memory(machine),
        "",
        _render_tenants(machine),
    ]
    return "\n".join(out)


# ─────────────────────────────────────────────────────────────────────
# JSON mode — for scripting / GUI integration
# ─────────────────────────────────────────────────────────────────────

def _to_jsonable(machine: Any) -> dict[str, Any]:
    mem = machine.memory
    tenants_out = []
    for t in list_openclaw_tenants(machine):
        ok, detail = validate_tenant(machine, t.name)
        tenants_out.append({
            "name": t.name,
            "workspace": str(t.workspace),
            "description": getattr(t, "description", ""),
            "bound_project": _read_tenant_binding(t),
            "validation": {"ok": ok, "detail": detail},
        })
    return {
        "version": getattr(machine, "version", 1),
        "memory": {
            "role": mem.role,
            "tool": mem.tool,
            "auth_mode": mem.auth_mode,
            "provider": mem.provider,
            "model": getattr(mem, "model", None),
            "runtime_dir": str(mem.runtime_dir),
            "storage_root": str(mem.storage_root),
            "monitor": mem.monitor,
        },
        "tenants": tenants_out,
        "engine": "real" if USE_REAL_ENGINE else "mock",
    }


# ─────────────────────────────────────────────────────────────────────
# Main flow
# ─────────────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ClawSeat machine-layer view")
    parser.add_argument("--json", action="store_true",
                        help="emit structured JSON instead of the human view")
    parser.add_argument("--sample", action="store_true",
                        help="deprecated compatibility flag; real machine.toml is always shown")
    args = parser.parse_args(argv)

    if args.sample and USE_REAL_ENGINE:
        print("[note] --sample has no effect once Phase 1 is live; showing real machine.toml",
              file=sys.stderr)

    machine = load_machine()

    if args.json:
        print(json.dumps(_to_jsonable(machine), ensure_ascii=False, indent=2))
        return 0

    print(textwrap.dedent(f"""
        ╔════════════════════════════════════════════════════════════════╗
        ║  ClawSeat machine view — ~/.clawseat/machine.toml               ║
        ║  Spec: docs/schemas/v0.4-layered-model.md §3                   ║
        ║  Engine: {'real' if USE_REAL_ENGINE else 'mock (Phase 1 not landed)':<54}║
        ╚════════════════════════════════════════════════════════════════╝
    """).strip())
    print()
    print(_render_machine(machine))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
