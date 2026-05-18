from __future__ import annotations

import os
import subprocess
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
_SUPPORT = _REPO / "scripts" / "windows-support.ps1"
_INSTALL = _REPO / "scripts" / "install-windows.ps1"
_LAUNCH = _REPO / "scripts" / "launch-windows.ps1"
_SMOKE = _REPO / "scripts" / "smoke-windows-tmux.ps1"
_INSTALL_DEPS = _REPO / "scripts" / "install-deps.ps1"
_WEZTERM_TEMPLATE = _REPO / "scripts" / "wezterm_config_template.lua"
_WINDOWS_WINDOW = _REPO / "core" / "scripts" / "agent_admin_window_windows.py"
_WEZTERM_SKILL = _REPO / "core" / "skills" / "wezterm-window" / "SKILL.md"
_CLAUDE_RUNTIME = _REPO / "core" / "launchers" / "runtimes" / "claude.sh"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig")


def test_windows_support_script_defines_wsl_boundary_helpers() -> None:
    text = _read(_SUPPORT)

    for name in (
        "ConvertTo-ClawSeatWslPath",
        "Invoke-ClawSeatWslBash",
        "Get-ClawSeatWindowsDependencySummary",
        "Get-ClawSeatWslDependencySummary",
        "Resolve-ClawSeatWezTerm",
        "Resolve-ClawSeatWezTermCli",
        "Assert-ClawSeatWindowsReady",
    ):
        assert f"function {name}" in text


def test_windows_path_conversion_allows_uncreated_targets_for_dry_run() -> None:
    text = _read(_SUPPORT)

    assert "[System.IO.Path]::GetFullPath($WindowsPath)" in text
    assert "Resolve-Path -LiteralPath $WindowsPath" not in text


def test_wsl_bash_capture_throws_on_nonzero_exit() -> None:
    text = _read(_SUPPORT)

    assert "if ($Capture)" in text
    assert "throw \"WSL command failed with exit ${LASTEXITCODE}: $Command\"" in text
    assert "return $output" in text


def test_windows_scripts_have_powershell_syntax() -> None:
    for script in (_SUPPORT, _INSTALL, _LAUNCH, _SMOKE):
        env = {**os.environ, "CLAWSEAT_SCRIPT_UNDER_TEST": str(script)}
        result = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                "$ErrorActionPreference='Stop'; [scriptblock]::Create((Get-Content -Raw -LiteralPath $env:CLAWSEAT_SCRIPT_UNDER_TEST)) | Out-Null",
            ],
            capture_output=True,
            text=True,
            check=False,
            env=env,
        )
        assert result.returncode == 0, result.stderr or result.stdout


def test_install_and_launch_dot_source_windows_support() -> None:
    assert ". $SupportScript" in _read(_INSTALL)
    assert ". $SupportScript" in _read(_LAUNCH)


def test_launcher_starts_project_in_wsl_and_uses_wezterm_only_for_display() -> None:
    text = _read(_LAUNCH)

    assert "project_file = Path.home() / '.agents' / 'projects' / project / 'project.toml'" in text
    assert "session.get('tool') == 'claude' and session.get('auth_mode') == 'api'" in text
    assert "CLAWSEAT_ENGINEER_ID=memory" in text
    assert r"CLAWSEAT_ENGINEER_PROFILE=\`$HOME/.agents/engineers/memory/engineer.toml" in text
    assert "agent_admin.py session batch-start-engineer $quotedSeatArgs --project $quotedProject --accept-override --no-iterm" in text
    assert "Start-ClawSeatWezTermLayout -Seats $displaySeats" in text
    assert "wsl.exe" in text
    assert "scripts/wait-for-seat.sh" in text
    assert "/tmp/fake-home" not in text
    assert "send-text" not in text


def test_smoke_script_uses_send_and_verify_inside_wsl_without_wezterm() -> None:
    text = _read(_SMOKE)

    assert "core/shell-scripts/send-and-verify.sh" in text
    assert "Invoke-ClawSeatWslBash" in text
    assert "SENT:" in text
    assert "wezterm" not in text.lower()
    assert "send-text" not in text


def test_windows_docs_describe_wsl_first_transport_boundary() -> None:
    text = _read(_REPO / "docs" / "WINDOWS.md")

    assert "WSL Ubuntu" in text
    assert "WezTerm" in text
    assert "display" in text.lower()
    assert "send-and-verify" in text
    assert "Git Bash or WSL" not in text


def test_windows_scripts_reject_option_like_project_names() -> None:
    pattern = "^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$"

    assert pattern in _read(_INSTALL)
    assert pattern in _read(_LAUNCH)
    assert pattern in _read(_SMOKE)


def test_windows_support_prefers_wezterm_gui_executable() -> None:
    text = _read(_SUPPORT)

    assert "function Resolve-ClawSeatWezTermCli" in text
    assert 'Join-Path (Split-Path -Parent $weztermCommand) "wezterm-gui.exe"' in text
    assert "$weztermGuiFromPath" in text
    assert "$candidates = @(\n        @(" in text


def test_launcher_uses_wezterm_gui_for_start_and_cli_for_splits() -> None:
    text = _read(_LAUNCH)

    assert "$wezterm = Resolve-ClawSeatWezTerm" in text
    assert "$weztermCli = Resolve-ClawSeatWezTermCli" in text
    assert "`$weztermCli = $(ConvertTo-ClawSeatPowerShellLiteral $weztermCli)" in text
    assert "`$weztermCli cli --prefer-mux split-pane" in text
    assert "`$wezterm cli --prefer-mux split-pane" not in text


def test_launcher_defaults_to_resetting_stale_windows_sessions() -> None:
    text = _read(_LAUNCH)
    wrapper = _read(_REPO / "launch-clawseat.ps1")

    assert "[switch]$NoReset" in text
    assert '$resetFlag = if ($NoReset) { "" } else { " --reset" }' in text
    assert "[switch]$Reset" not in text
    assert "[switch]$Reset" in wrapper
    assert '$launchArgs = @{ Project = $Project }' in wrapper
    assert 'if ($Reset) { $argsList += "-Reset" }' not in wrapper
    assert "& $launcher @launchArgs" in wrapper


def test_launcher_quotes_wezterm_arguments_before_start_process() -> None:
    text = _read(_LAUNCH)

    assert "function Join-ClawSeatWindowsArguments" in text
    assert '$wezArgs = @("start", "--", "powershell.exe", "-NoExit", "-EncodedCommand", $encodedBootstrap)' in text
    assert "--title" not in text
    assert "Start-Process -FilePath $wezterm -ArgumentList (Join-ClawSeatWindowsArguments $wezArgs)" in text


def test_launcher_uses_one_wezterm_window_with_five_vertical_panes() -> None:
    text = _read(_LAUNCH)

    assert "Start-ClawSeatWezTermLayout" in text
    assert "Start-ClawSeatWezTermSeat" not in text
    assert "ConvertTo-ClawSeatPowerShellLiteral" in text
    assert "-EncodedCommand" in text
    assert "cli --prefer-mux split-pane --right -- powershell.exe" in text
    assert "cli --prefer-mux split-pane --pane-id `$previousPaneId --right -- powershell.exe" in text
    assert "--bottom" not in text
    assert 'Start-Process -FilePath $wezterm -ArgumentList (Join-ClawSeatWindowsArguments $wezArgs)' in text
    assert "foreach ($seat in $displaySeats)" not in text


def test_smoke_script_validates_seats_and_quotes_project() -> None:
    text = _read(_SMOKE)

    assert "[string[]]$Seats" in text
    assert "$quotedProject = Quote-ClawSeatBash $Project" in text
    assert "--project $quotedProject" in text


def test_no_real_anthropic_tokens_in_windows_probe_scripts() -> None:
    for path in _REPO.glob("test_3panes*"):
        text = _read(path)
        assert "MINIMAX_CREDENTIAL_PREFIX" not in text
        assert "ANTHROPIC_CREDENTIAL_PREFIX" not in text


def test_windows_probe_scripts_do_not_bypass_claude_permissions() -> None:
    for path in _REPO.glob("test_3panes*"):
        assert "--dangerously-skip-permissions" not in _read(path)


def test_legacy_windows_launchers_delegate_to_wsl_first_launcher() -> None:
    paths = [
        _REPO / "launch-clawseat.ps1",
        _REPO / "launch-simple.bat",
        _REPO / "launch-clawseat-safe.bat",
        _REPO / "test_3panes_skill.ps1",
        _REPO / "core" / "skills" / "wezterm-window" / "scripts" / "Start-ClaudeAgent.ps1",
        *(_REPO / ".deps").glob("agent-*.ps1"),
        _REPO / ".deps" / "launch-clawseat-agents.ps1",
    ]

    for path in paths:
        text = _read(path)
        assert "scripts\\launch-windows.ps1" in text or "scripts/launch-windows.ps1" in text or "smoke-windows-tmux.ps1" in text
        assert "claude" not in text.lower()
        assert "codex" not in text.lower()
        assert "gemini" not in text.lower()
        assert "send-text" not in text
        assert "ANTHROPIC_AUTH_TOKEN" not in text
        assert "ANTHROPIC_API_KEY" not in text


def test_installer_bootstraps_project_state_inside_wsl() -> None:
    text = _read(_INSTALL)

    assert "agent_admin.py project bootstrap" in text
    assert "ConvertTo-ClawSeatWslPath -WindowsPath $localToml" in text
    assert "Invoke-ClawSeatInstallWsl" in text
    assert "Writing project configuration" not in text


def test_installer_backs_up_existing_wezterm_config_before_overwrite() -> None:
    text = _read(_INSTALL)

    assert "Test-Path $configPath" in text
    assert "$backupPath = \"$configPath.$timestamp.bak\"" in text
    assert "Copy-Item -LiteralPath $configPath -Destination $backupPath -Force" in text
    assert "Write-Warn \"Existing WezTerm config backed up:" in text


def test_windows_installer_defaults_bootstrap_seats_to_minimax() -> None:
    text = _read(_INSTALL)

    assert '[ValidateSet("anthropic-console", "minimax", "deepseek", "ark", "xcode-best")]' in text
    assert '[string]$Provider = "minimax"' in text
    assert '[string]$AllApiProvider = "minimax"' in text
    assert '[string]$MemoryModel = "MiniMax-M2.7-highspeed"' in text
    assert "Format-ClawSeatTomlString" in text
    assert "Write-ClawSeatUtf8NoBom" in text
    assert "Get-ClawSeatTemplateSeatIds" in text
    assert "$templateSeatIds = Get-ClawSeatTemplateSeatIds -TemplatePath $templatePath" in text
    assert '$Lines.Add("[[overrides]]")' in text
    assert 'Add-ClawSeatOverride -Lines $localLines -SeatIds $templateSeatIds -SeatId "memory" -Tool $MemoryTool -AuthMode "api" -SeatProvider $Provider -Model $MemoryModel' in text
    assert 'Add-ClawSeatOverride -Lines $localLines -SeatIds $templateSeatIds -SeatId "planner" -Tool "claude" -AuthMode "api" -SeatProvider $AllApiProvider -Model $MemoryModel' in text
    assert 'Add-ClawSeatOverride -Lines $localLines -SeatIds $templateSeatIds -SeatId "builder" -Tool "claude" -AuthMode "api" -SeatProvider $AllApiProvider -Model $MemoryModel' in text
    assert 'Add-ClawSeatOverride -Lines $localLines -SeatIds $templateSeatIds -SeatId "reviewer" -Tool "claude" -AuthMode "api" -SeatProvider $AllApiProvider -Model $MemoryModel' in text
    assert 'Add-ClawSeatOverride -Lines $localLines -SeatIds $templateSeatIds -SeatId "patrol" -Tool "claude" -AuthMode "api" -SeatProvider $AllApiProvider -Model $MemoryModel' in text
    assert "$localContent | Out-File -FilePath $localToml -Encoding UTF8" not in text


def test_dependency_installer_uses_repo_relative_deps_dir() -> None:
    text = _read(_INSTALL_DEPS)

    assert '$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")' in text
    assert '$InstallDir = Join-Path $RepoRoot ".deps"' in text
    assert "X:\\fake-home\\ClawSeat-Windows\\.deps" not in text


def test_wezterm_template_uses_only_supported_config_fields() -> None:
    text = _read(_WEZTERM_TEMPLATE)

    assert "title_font_size" not in text
    assert "format-window-title" not in text
    assert "pane:get_title" not in text
    assert "clawseat_enabled" not in text
    assert "return config" in text


def test_windows_window_module_uses_shlex_quote() -> None:
    text = _read(_WINDOWS_WINDOW)

    assert "import shlex" in text
    assert "shlex.quote" in text
    assert "shutil.quote" not in text


def test_windows_window_module_quotes_complete_tmux_targets() -> None:
    text = _read(_WINDOWS_WINDOW)

    assert "def _tmux_attach_command" in text
    assert "shlex.quote('=' + target)" in text
    assert '_tmux_attach_command(f"{project.name}-{primary_seat_id}")' in text
    assert "_tmux_attach_command(entry.tmux_name)" in text
    assert "_tmux_attach_command(session)" in text
    assert '"tmux attach -t \'="' not in text


def test_wezterm_skill_documents_display_only_boundary() -> None:
    text = _read(_WEZTERM_SKILL)

    assert "WezTerm only displays WSL tmux sessions" in text
    assert "send-and-verify.sh" in text
    assert "pane text injection" in text
    assert "send-text" not in text
    assert "--dangerously-skip-permissions" not in text


def test_claude_runtime_prefers_wsl_user_local_tools() -> None:
    text = _read(_CLAUDE_RUNTIME)

    assert 'PATH="$REAL_HOME/.local/bin:$REAL_HOME/.local/node/current/bin:$PATH"' in text
    assert "export PATH" in text


def test_launcher_uses_wait_for_seat_for_canonical_session_attach() -> None:
    text = _read(_LAUNCH)

    assert "scripts/wait-for-seat.sh" in text
    assert '"tmux", "attach"' not in text
    assert "Start-ClawSeatWezTermLayout" in text
    assert "Start-ClawSeatWezTermAttach" not in text


def test_root_probe_scripts_do_not_execute_on_import() -> None:
    for path in _REPO.glob("test_3panes*.py"):
        text = _read(path)
        assert "if __name__ == \"__main__\":" in text
        before_guard = text.split("if __name__ == \"__main__\":", 1)[0]
        assert "subprocess.run" not in before_guard


def test_root_probe_scripts_do_not_bypass_wsl_tmux_transport() -> None:
    forbidden = (
        "wezterm_panes_driver.py",
        "send-text",
        "ANTHROPIC_AUTH_TOKEN",
        "ANTHROPIC_API_KEY",
        "command\": \"claude",
        "command\": \"codex",
        "command\": \"gemini",
    )

    for path in _REPO.glob("test_3panes*.py"):
        text = _read(path)
        for value in forbidden:
            assert value not in text, f"{path.name} contains forbidden transport pattern: {value}"
