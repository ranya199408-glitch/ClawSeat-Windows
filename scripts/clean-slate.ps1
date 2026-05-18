#!/usr/bin/env powershell
#Requires -Version 5.1
<#
.SYNOPSIS
    Clean Slate - Reset ClawSeat Windows installation

.DESCRIPTION
    Removes all ClawSeat state, sessions, and configuration.
    Equivalent to macOS clean-slate.sh but for Windows.

.PARAMETER Project
    Specific project to clean. If not specified, cleans all projects.

.PARAMETER Yes
    Skip confirmation prompt.

.PARAMETER KeepConfig
    Keep WezTerm configuration.
#>

[CmdletBinding()]
param(
    [string]$Project = "",
    [switch]$Yes,
    [switch]$KeepConfig
)

$UserProfile = $env:USERPROFILE
$AgentsRoot = Join-Path $UserProfile ".agents"
$ClawSeatConfigDir = Join-Path $UserProfile ".clawseat"

function Write-Info { param([string]$Message) Write-Host "==> $Message" -ForegroundColor Cyan }
function Write-Success { param([string]$Message) Write-Host "  ✓ $Message" -ForegroundColor Green }
function Write-Warn { param([string]$Message) Write-Host "  ⚠ $Message" -ForegroundColor Yellow }
function Write-Error { param([string]$Message) Write-Host "  ✗ $Message" -ForegroundColor Red }

# Confirmation
if (-not $Yes) {
    Write-Host ""
    Write-Host "WARNING: This will delete all ClawSeat data!" -ForegroundColor Red
    Write-Host ""
    Write-Host "The following will be removed:"
    Write-Host "  - $AgentsRoot"
    if (-not $KeepConfig) {
        Write-Host "  - $ClawSeatConfigDir"
    }
    Write-Host "  - All tmux sessions"
    Write-Host "  - All scheduled tasks"
    Write-Host ""
    $confirm = Read-Host "Type 'yes' to continue"
    if ($confirm -ne "yes") {
        Write-Host "Aborted." -ForegroundColor Yellow
        exit 1
    }
}

# Kill tmux sessions
Write-Info "Killing tmux sessions..."
try {
    $sessions = tmux ls 2>$null
    if ($sessions) {
        tmux kill-server 2>$null
        Write-Success "All tmux sessions killed"
    } else {
        Write-Warn "No tmux sessions found"
    }
} catch {
    Write-Warn "tmux not available or no sessions"
}

# Remove scheduled tasks
Write-Info "Removing scheduled tasks..."
$tasks = schtasks /Query /FO CSV /NH 2>$null | ForEach-Object {
    $parts = $_ -split ','
    if ($parts[0] -match '"ClawSeat') {
        $parts[0] -replace '"', ''
    }
}
foreach ($task in $tasks) {
    if ($task) {
        schtasks /Delete /TN "$task" /F 2>$null | Out-Null
        Write-Success "Removed task: $task"
    }
}

# Remove directories
Write-Info "Removing directories..."

if (Test-Path $AgentsRoot) {
    Remove-Item -Path $AgentsRoot -Recurse -Force
    Write-Success "Removed: $AgentsRoot"
}

if (-not $KeepConfig -and (Test-Path $ClawSeatConfigDir)) {
    Remove-Item -Path $ClawSeatConfigDir -Recurse -Force
    Write-Success "Removed: $ClawSeatConfigDir"
}

# Clean up WezTerm windows
Write-Info "Closing WezTerm windows..."
try {
    $windows = wezterm cli list --format json 2>$null | ConvertFrom-Json
    foreach ($window in $windows) {
        if ($window.title -match "clawseat") {
            wezterm cli kill-window --window-id $window.window_id 2>$null
            Write-Success "Closed window: $($window.title)"
        }
    }
} catch {
    Write-Warn "Could not close WezTerm windows"
}

Write-Host ""
Write-Host "╔══════════════════════════════════════════════════════════════╗" -ForegroundColor Green
Write-Host "║              Clean Slate Complete!                           ║" -ForegroundColor Green
Write-Host "╚══════════════════════════════════════════════════════════════╝" -ForegroundColor Green
Write-Host ""
Write-Host "ClawSeat has been reset. To reinstall, run:"
Write-Host "  .\scripts\install-windows.ps1 -Project <name>" -ForegroundColor Cyan
