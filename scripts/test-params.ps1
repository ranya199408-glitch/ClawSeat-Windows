#Requires -Version 5.1
<#
.SYNOPSIS
    ClawSeat Windows Installer - WezTerm Edition

.DESCRIPTION
    Installs ClawSeat on Windows with WezTerm as the terminal multiplexer.
    Replaces macOS-specific components (iTerm2, tmux, AppleScript, LaunchAgent)
    with Windows-native equivalents.

.PARAMETER Project
    Project name for the installation.

.PARAMETER Template
    Template to use: clawseat-engineering, clawseat-creative, clawseat-solo.

.PARAMETER RepoRoot
    Root directory of the target project repository.

.PARAMETER ForceRepoRoot
    Force the ClawSeat repository root path.

.PARAMETER Provider
    AI provider for memory seat: oauth, anthropic_console, minimax, deepseek, custom_api.

.PARAMETER AllApiProvider
    Provider for all API-authenticated seats.

.PARAMETER MemoryTool
    Tool for memory seat: claude, codex, gemini.

.PARAMETER MemoryModel
    Model for memory seat.

.PARAMETER EnableAutoPatrol
    Enable automatic patrol cron jobs.

.PARAMETER DryRun
    Show what would be done without executing.

.PARAMETER DetectOnly
    Scan environment and print JSON summary, then exit.

.PARAMETER ShowHelp
    Display this help message.

.EXAMPLE
    .\install-windows.ps1 -Project myapp -Template clawseat-engineering

.EXAMPLE
    .\install-windows.ps1 -DetectOnly

.NOTES
    Dependencies: WezTerm, Git, Python 3.11+, tmux (via Git Bash or WSL)
    Author: ClawSeat Windows Port
    Version: 0.2.1-windows
#>

[CmdletBinding()]
param(
    [string]$Project = "install",
    [ValidateSet("clawseat-engineering", "clawseat-creative", "clawseat-solo")]
    [string]$Template = "clawseat-engineering",
    [string]$RepoRoot = "",
    [string]$ForceRepoRoot = "",
    [string]$Provider = "",
    [string]$AllApiProvider = "",
    [ValidateSet("claude", "codex", "gemini")]
    [string]$MemoryTool = "claude",
    [string]$MemoryModel = "gpt-5.4-mini",
    [switch]$EnableAutoPatrol,
    [switch]$DryRun,
    [switch]$DetectOnly,
    [switch]$Reinstall,
    [switch]$ShowHelp
)

Write-Host "OK"
if ($DetectOnly) {
    Write-Host "Detect mode"
    exit 0
}
