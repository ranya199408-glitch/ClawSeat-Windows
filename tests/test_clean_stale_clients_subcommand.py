from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from tests.test_agent_admin_session_isolation import _make_session, _make_service

import agent_admin as aa
import agent_admin_commands as aac


def test_tmux_clean_stale_clients_cli_reports_counts_and_reuses_reports(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    session = _make_session(
        tmp_path,
        engineer_id="builder",
        tool="claude",
        auth_mode="oauth",
        provider="anthropic",
        secret_content="ANTHROPIC_AUTH_TOKEN=<ANTHROPIC_AUTH_TOKEN>\n",
    )
    service, hooks = _make_service(tmp_path, session)

    project = SimpleNamespace(name="install", engineers=["builder", "planner"])
    sessions = {
        "builder": SimpleNamespace(session="install-builder-claude", engineer_id="builder"),
        "planner": SimpleNamespace(session="install-planner-claude", engineer_id="planner"),
    }

    hooks.error_cls = RuntimeError
    hooks.load_project_or_current.return_value = project
    hooks.load_project_sessions.return_value = sessions
    hooks.session_service = service

    candidate_calls: list[str] = []
    live_calls: list[str] = []

    candidate_lookup = {
        sessions["builder"].session: [(21, "tmux attach -t install-builder-claude")],
        sessions["planner"].session: [
            (11, "tmux attach -t install-planner-claude"),
            (12, "tmux attach -t install-planner-claude"),
            (13, "tmux attach -t install-planner-claude"),
        ],
    }
    live_lookup = {
        sessions["builder"].session: set(),
        sessions["planner"].session: {11},
    }

    service._tmux_attach_candidate_processes = MagicMock(
        side_effect=lambda session_name: candidate_calls.append(session_name) or candidate_lookup[session_name]
    )
    service._live_tmux_client_pids = MagicMock(
        side_effect=lambda session_name: live_calls.append(session_name) or live_lookup[session_name]
    )

    handlers = aac.CommandHandlers(hooks)
    monkeypatch.setattr(aa, "COMMAND_HANDLERS", handlers)

    with patch.object(service, "clean_stale_attach_clients", wraps=service.clean_stale_attach_clients) as cleanup_mock:
        parser = aa.build_parser()
        args = parser.parse_args(["tmux", "clean-stale-clients", "--project", "install", "--dry-run"])
        rc = args.func(args)

    assert rc == 0
    assert candidate_calls == [sessions["builder"].session, sessions["planner"].session]
    assert live_calls == [sessions["builder"].session, sessions["planner"].session]
    assert [call.args[0] for call in cleanup_mock.call_args_list] == [
        sessions["builder"].session,
        sessions["planner"].session,
    ]
    assert all(call.kwargs["dry_run"] is True for call in cleanup_mock.call_args_list)
    assert cleanup_mock.call_args_list[0].kwargs["report"].candidate_pids == (21,)
    assert cleanup_mock.call_args_list[0].kwargs["report"].stale_pids == (21,)
    assert cleanup_mock.call_args_list[1].kwargs["report"].candidate_pids == (11, 12, 13)
    assert cleanup_mock.call_args_list[1].kwargs["report"].stale_pids == (12, 13)

    captured = capsys.readouterr()
    stdout = captured.out
    stderr = captured.err
    assert "tmux clean-stale-clients: session=install-builder-claude candidates=1" in stdout
    assert "tmux clean-stale-clients: session=install-planner-claude candidates=3" in stdout
    assert "whitelist_hits=1 skip_count=4 dry_run=1" in stdout
    assert "tmux clean-stale-clients: project=install sessions=2 candidates=4 whitelist_hits=1 skip_count=4 dry_run=1" in stdout
    assert "tmux clean-stale-clients: dry-run pid=21 session=install-builder-claude command=tmux attach -t install-builder-claude" in stderr
    assert "tmux clean-stale-clients: dry-run pid=12 session=install-planner-claude command=tmux attach -t install-planner-claude" in stderr
    assert "tmux clean-stale-clients: dry-run pid=13 session=install-planner-claude command=tmux attach -t install-planner-claude" in stderr
