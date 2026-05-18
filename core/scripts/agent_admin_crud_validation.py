from __future__ import annotations

import sys
from typing import Any

from agent_admin_crud_base import CrudHooks


class ValidationCrud:
    def __init__(self, hooks: CrudHooks) -> None:
        self.hooks = hooks

    def project_bind(self, args: Any) -> int:
        from project_binding import (
            ProjectBindingError,
            bind_project,
            fetch_chat_metadata,
            load_binding,
        )

        try:
            existing = load_binding(args.project)
            group_name, group_external = fetch_chat_metadata(args.feishu_group)
            legacy_account = getattr(args, "feishu_bot_account", None)
            sender_app_id = getattr(args, "feishu_sender_app_id", "") or ""
            sender_mode = getattr(args, "feishu_sender_mode", "auto") or "auto"
            koder_agent = getattr(args, "openclaw_koder_agent", "") or ""
            if legacy_account is not None:
                route_label = "feishu_sender_app_id" if str(legacy_account).startswith("cli_") else "openclaw_koder_agent"
                print(
                    "warning: --feishu-bot-account is deprecated; "
                    f"routing to {route_label}",
                    file=sys.stderr,
                )
                if str(legacy_account).startswith("cli_") and not sender_app_id:
                    sender_app_id = str(legacy_account)
                elif not koder_agent:
                    koder_agent = str(legacy_account)
            path = bind_project(
                project=args.project,
                feishu_group_id=args.feishu_group,
                feishu_group_name=group_name,
                feishu_external=group_external,
                feishu_sender_app_id=sender_app_id,
                feishu_sender_mode=sender_mode,
                openclaw_koder_agent=koder_agent,
                feishu_bot_account="" if legacy_account is None else str(legacy_account),
                tools_isolation="" if existing is None else existing.tools_isolation,
                gemini_account_email="" if existing is None else existing.gemini_account_email,
                codex_account_email="" if existing is None else existing.codex_account_email,
                require_mention=bool(args.require_mention),
                bound_by=args.bound_by,
            )
        except ProjectBindingError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2

        action = "updated" if existing is not None else "created"
        previous = (
            f" (was {existing.feishu_group_id})"
            if existing is not None and existing.feishu_group_id != args.feishu_group
            else ""
        )
        print(
            f"project bind {action}: {args.project} -> {args.feishu_group}"
            f"{previous} [{path}]"
        )
        return 0

    def project_binding_show(self, args: Any) -> int:
        from project_binding import (
            ProjectBindingError,
            binding_path,
            load_binding,
        )

        path = binding_path(args.project)
        try:
            binding = load_binding(args.project)
        except ProjectBindingError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        if binding is None:
            print(f"no binding for project={args.project!r} (expected {path})")
            return 1
        print(f"path: {path}")
        print(binding.as_toml().rstrip())
        return 0

    def project_binding_list(self, args: Any) -> int:
        from project_binding import list_bindings

        bindings = list_bindings()
        if not bindings:
            print("no project bindings found under ~/.agents/tasks/")
            return 0
        width = max(len(b.project) for b in bindings)
        for binding in bindings:
            print(
                f"{binding.project:<{width}}  {binding.feishu_group_id}  "
                f"sender_app_id={binding.feishu_sender_app_id or '-'}  "
                f"sender_mode={binding.feishu_sender_mode}  "
                f"koder_agent={binding.openclaw_koder_agent or '-'}  "
                f"tools_isolation={binding.tools_isolation}  "
                f"gemini_account_email={binding.gemini_account_email or '-'}  "
                f"codex_account_email={binding.codex_account_email or '-'}  "
                f"require_mention={'true' if binding.require_mention else 'false'}"
            )
        return 0

    def project_unbind(self, args: Any) -> int:
        from project_binding import binding_path

        path = binding_path(args.project)
        if not path.exists():
            print(f"no binding to remove for project={args.project!r} (expected {path})")
            return 1
        path.unlink()
        print(f"project unbind: removed {path}")
        return 0

    def project_koder_bind(self, args: Any) -> int:
        from agent_admin_layered import cmd_project_koder_bind

        return cmd_project_koder_bind(args)

    def project_validate(self, args: Any) -> int:
        from agent_admin_layered import cmd_project_validate

        return cmd_project_validate(args)
