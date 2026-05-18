from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from agent_admin_crud_base import HOME, CrudHooks, _update_profile_seat, require_caller_authority
from agent_admin_crud_bootstrap import BootstrapCrud
from agent_admin_crud_engineer import EngineerCrud
from agent_admin_crud_project import ProjectCrud
from agent_admin_crud_validation import ValidationCrud


class CrudHandlers:
    def __init__(self, hooks: CrudHooks) -> None:
        self.hooks = hooks
        self.project = ProjectCrud(hooks)
        self.engineer = EngineerCrud(hooks)
        self.bootstrap = BootstrapCrud(hooks)
        self.validation = ValidationCrud(hooks)

    def _require_escalation_authority(self, action: str) -> None:
        require_caller_authority("escalation", action, self.hooks.error_cls)

    def project_open(self, args: Any) -> int:
        return self.project.project_open(args)

    def project_create(self, args: Any) -> int:
        return self.project.project_create(args)

    def project_use(self, args: Any) -> int:
        return self.project.project_use(args)

    def project_current(self, args: Any) -> int:
        return self.project.project_current(args)

    def project_layout_set(self, args: Any) -> int:
        return self.project.project_layout_set(args)

    def project_init_tools(self, args: Any) -> int:
        return self.project.project_init_tools(args)

    def project_switch_identity(self, args: Any) -> int:
        return self.project.project_switch_identity(args)

    def project_delete(self, args: Any) -> int:
        return self.project.project_delete(args)

    def project_bootstrap(self, args: Any) -> int:
        return self.bootstrap.project_bootstrap(args)

    def engineer_create(self, args: Any) -> int:
        self._require_escalation_authority("engineer create")
        return self.engineer.engineer_create(args)

    def engineer_delete(self, args: Any) -> int:
        self._require_escalation_authority("engineer delete")
        return self.engineer.engineer_delete(args)

    def engineer_rename(self, args: Any) -> int:
        self._require_escalation_authority("engineer rename")
        return self.engineer.engineer_rename(args)

    def engineer_rebind(self, args: Any) -> int:
        self._require_escalation_authority("engineer rebind")
        return self.engineer.engineer_rebind(args)

    def engineer_refresh_workspace(self, args: Any) -> int:
        return self.engineer.engineer_refresh_workspace(args)

    def engineer_regenerate_workspace(self, args: Any) -> int:
        self._require_escalation_authority("engineer regenerate-workspace")
        return self.engineer.engineer_regenerate_workspace(args)

    def engineer_secret_set(self, args: Any) -> int:
        self._require_escalation_authority("engineer secret-set")
        return self.engineer.engineer_secret_set(args)

    def project_bind(self, args: Any) -> int:
        return self.validation.project_bind(args)

    def project_binding_show(self, args: Any) -> int:
        return self.validation.project_binding_show(args)

    def project_binding_list(self, args: Any) -> int:
        return self.validation.project_binding_list(args)

    def project_unbind(self, args: Any) -> int:
        return self.validation.project_unbind(args)

    def project_koder_bind(self, args: Any) -> int:
        return self.validation.project_koder_bind(args)

    def project_validate(self, args: Any) -> int:
        return self.validation.project_validate(args)


if __name__ == "__main__":
    import argparse as _ap

    _p = _ap.ArgumentParser(description="Profile-only seat operations (no session bootstrap)")
    _p.add_argument("command", choices=["engineer_create", "engineer_rebind"])
    _p.add_argument("seat_id")
    _p.add_argument("--profile", required=True)
    _p.add_argument("--role")
    _p.add_argument("--tool", default="claude")
    _p.add_argument("--mode", default="oauth")
    _p.add_argument("--provider", default="anthropic")
    _p.add_argument("--model")
    _a = _p.parse_args()
    _profile_path = Path(_a.profile)
    _role = (_a.role or "").strip() or _a.seat_id.split("-")[0]
    _rebind = _a.command == "engineer_rebind"
    try:
        require_caller_authority("escalation", f"profile update ({_a.command})", RuntimeError)
        _update_profile_seat(
            _profile_path,
            _a.seat_id,
            _role,
            _a.tool,
            _a.mode,
            _a.provider,
            _a.model,
            rebind=_rebind,
        )
        print(f"updated profile {_profile_path}: {_a.seat_id} ({_a.command})")
    except Exception as _exc:
        print(f"error: {_exc}", file=sys.stderr)
        sys.exit(1)
