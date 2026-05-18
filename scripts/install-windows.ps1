#Requires -Version 5.1
<#
.SYNOPSIS
    ClawSeat Windows Installer - WSL-first WezTerm Edition

.DESCRIPTION
    Installs ClawSeat Windows configuration while keeping the runtime inside WSL Ubuntu.
    PowerShell is the Windows entrypoint, WezTerm is display-only, and tmux inside WSL
    remains the seat interaction and task transport layer.

.PARAMETER Project
    Project name for the installation.

.PARAMETER Template
    Template to use: clawseat-engineering, clawseat-creative, clawseat-solo.

.PARAMETER RepoRoot
    Root directory of the target project repository.

.PARAMETER ForceRepoRoot
    Force the ClawSeat repository root path.

.PARAMETER WslDistro
    Optional WSL distribution name. Defaults to the user's default WSL distro.

.PARAMETER Provider
    AI provider for memory seat: anthropic-console, minimax, deepseek, ark, xcode-best.

.PARAMETER AllApiProvider
    Provider for planner, builder, reviewer, and patrol API-authenticated seats.

.PARAMETER MemoryTool
    Tool for memory seat: claude, codex, gemini.

.PARAMETER MemoryModel
    Model for memory seat.

.PARAMETER EnableAutoPatrol
    Enable automatic patrol cron jobs through Windows Task Scheduler.

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
    Dependencies: WezTerm on Windows; WSL Ubuntu with bash, git, python3, tmux, and AI CLIs.
    Version: 0.2.1-windows
#>

[CmdletBinding()]
param(
    [string]$Project = "install",
    [ValidateSet("clawseat-engineering", "clawseat-creative", "clawseat-solo")]
    [string]$Template = "clawseat-engineering",
    [string]$RepoRoot = "",
    [string]$ForceRepoRoot = "",
    [string]$WslDistro = "",
    [ValidateSet("anthropic-console", "minimax", "deepseek", "ark", "xcode-best")]
    [string]$Provider = "minimax",
    [ValidateSet("anthropic-console", "minimax", "deepseek", "ark", "xcode-best")]
    [string]$AllApiProvider = "minimax",
    [ValidateSet("claude", "codex", "gemini")]
    [string]$MemoryTool = "claude",
    [ValidatePattern('^[A-Za-z0-9][A-Za-z0-9._:/\[\]-]*$')]
    [string]$MemoryModel = "MiniMax-M2.7-highspeed",
    [switch]$EnableAutoPatrol,
    [switch]$DryRun,
    [switch]$DetectOnly,
    [switch]$Reinstall,
    [switch]$ShowHelp
)

$Script:Version = "0.2.1-windows"
$Script:ErrorActionPreference = "Stop"
$Script:ProgressPreference = "SilentlyContinue"
$SupportScript = Join-Path $PSScriptRoot "windows-support.ps1"
. $SupportScript

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$RepoRootResolved = if ($ForceRepoRoot) {
    Resolve-Path $ForceRepoRoot | Select-Object -ExpandProperty Path
} else {
    Resolve-Path (Join-Path $ScriptDir "..") | Select-Object -ExpandProperty Path
}

$ClawSeatRoot = $RepoRootResolved
$CoreDir = Join-Path $ClawSeatRoot "core"
$ScriptsDir = Join-Path $ClawSeatRoot "scripts"
$TemplatesDir = Join-Path $ClawSeatRoot "templates"
$UserProfile = $env:USERPROFILE
$WindowsAgentsRoot = Join-Path $UserProfile ".agents"
$ClawSeatConfigDir = Join-Path $UserProfile ".clawseat"
$WezTermConfigDir = Join-Path (Join-Path $UserProfile ".config") "wezterm"

function Write-Info { param([string]$Message) Write-Host "==> $Message" -ForegroundColor Cyan }
function Write-Success { param([string]$Message) Write-Host "  [OK] $Message" -ForegroundColor Green }
function Write-Warn { param([string]$Message) Write-Host "  [WARN] $Message" -ForegroundColor Yellow }
function Write-Error { param([string]$Message) Write-Host "  [ERR] $Message" -ForegroundColor Red }
function Write-DryRun { param([string]$Message) Write-Host "  [dry-run] $Message" -ForegroundColor Magenta }

function Quote-ClawSeatBash {
    param([Parameter(Mandatory=$true)][string]$Value)
    $escaped = $Value -replace "'", "'\''"
    return "'" + $escaped + "'"
}

function Invoke-ClawSeatInstallWsl {
    param([Parameter(Mandatory=$true)][string]$Command)

    if ($DryRun) {
        Write-DryRun "Would run WSL bash: $Command"
        return
    }
    Invoke-ClawSeatWslBash -Distro $WslDistro -Command $Command
}

function Format-ClawSeatTomlString {
    param([AllowEmptyString()][string]$Value)

    return '"' + ($Value -replace '\\', '\\' -replace '"', '\"' -replace "`r", '\r' -replace "`n", '\n' -replace "`t", '\t') + '"'
}

function Write-ClawSeatUtf8NoBom {
    param(
        [Parameter(Mandatory=$true)][string]$Path,
        [Parameter(Mandatory=$true)][string]$Content
    )

    $encoding = New-Object System.Text.UTF8Encoding $false
    [System.IO.File]::WriteAllText($Path, $Content, $encoding)
}

function Get-ClawSeatTemplateSeatIds {
    param([Parameter(Mandatory=$true)][string]$TemplatePath)

    $ids = @()
    foreach ($line in Get-Content -LiteralPath $TemplatePath) {
        if ($line -match '^\s*id\s*=\s*"([^"]+)"\s*$') {
            $ids += $matches[1]
        }
    }
    return $ids
}

function Add-ClawSeatOverride {
    param(
        [System.Collections.Generic.List[string]]$Lines,
        [Parameter(Mandatory=$true)][string[]]$SeatIds,
        [Parameter(Mandatory=$true)][string]$SeatId,
        [Parameter(Mandatory=$true)][string]$Tool,
        [Parameter(Mandatory=$true)][string]$AuthMode,
        [Parameter(Mandatory=$true)][string]$SeatProvider,
        [Parameter(Mandatory=$true)][string]$Model
    )

    if ($SeatIds -notcontains $SeatId) {
        return
    }

    $Lines.Add("")
    $Lines.Add("[[overrides]]")
    $Lines.Add("id = $(Format-ClawSeatTomlString $SeatId)")
    $Lines.Add("tool = $(Format-ClawSeatTomlString $Tool)")
    $Lines.Add("auth_mode = $(Format-ClawSeatTomlString $AuthMode)")
    $Lines.Add("provider = $(Format-ClawSeatTomlString $SeatProvider)")
    $Lines.Add("model = $(Format-ClawSeatTomlString $Model)")
}

function Test-Dependencies {
    Write-Info "Checking Windows and WSL dependencies..."
    Assert-ClawSeatWindowsReady -Distro $WslDistro
    Write-Success "Windows dependencies found"
    Write-Success "WSL Ubuntu runtime dependencies found"
}

function Get-EnvironmentSummary {
    $repoWslPath = ""
    try {
        $repoWslPath = ConvertTo-ClawSeatWslPath -WindowsPath $ClawSeatRoot -Distro $WslDistro
    } catch {
        $repoWslPath = ""
    }

    return [ordered]@{
        platform = "windows"
        architecture = "wsl-first"
        windows = Get-ClawSeatWindowsDependencySummary -Distro $WslDistro
        wsl = Get-ClawSeatWslDependencySummary -Distro $WslDistro
        paths = [ordered]@{
            clawseat_root_windows = $ClawSeatRoot
            clawseat_root_wsl = $repoWslPath
        }
        templates = @("clawseat-solo", "clawseat-engineering", "clawseat-creative")
        transport = "tmux/send-and-verify inside WSL"
        display = "WezTerm attach only"
        timestamp = (Get-Date -Format "yyyy-MM-ddTHH:mm:ssZ")
    } | ConvertTo-Json -Depth 8
}

function Install-WezTermConfig {
    Write-Info "Installing WezTerm configuration..."

    $templatePath = Join-Path $ScriptsDir "wezterm_config_template.lua"
    $weztermLua = Get-Content $templatePath -Raw

    if (-not (Test-Path $WezTermConfigDir)) {
        New-Item -ItemType Directory -Path $WezTermConfigDir -Force | Out-Null
    }

    $configPath = Join-Path $WezTermConfigDir "wezterm.lua"
    if ($DryRun) {
        Write-DryRun "Would write WezTerm config to $configPath"
    } else {
        if (Test-Path $configPath) {
            $timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
            $backupPath = "$configPath.$timestamp.bak"
            Copy-Item -LiteralPath $configPath -Destination $backupPath -Force
            Write-Warn "Existing WezTerm config backed up: $backupPath"
        }
        $weztermLua | Out-File -FilePath $configPath -Encoding UTF8
        Write-Success "WezTerm config installed: $configPath"
    }
}

function Initialize-DirectoryStructure {
    Write-Info "Initializing Windows-side directory structure..."

    $dirs = @(
        (Join-Path $WindowsAgentsRoot "tasks"),
        (Join-Path $ClawSeatConfigDir "skills"),
        (Join-Path $ClawSeatConfigDir "workspaces")
    )

    foreach ($dir in $dirs) {
        if ($DryRun) {
            Write-DryRun "Would create directory: $dir"
        } else {
            if (-not (Test-Path $dir)) {
                New-Item -ItemType Directory -Path $dir -Force | Out-Null
                Write-Success "Created: $dir"
            }
        }
    }
}

function Initialize-ProjectInWsl {
    param([string]$ProjectName, [string]$TemplateName)

    Write-Info "Bootstrapping project '$ProjectName' inside WSL..."

    $templatePath = Join-Path $TemplatesDir "$TemplateName.toml"
    if (-not (Test-Path $templatePath)) {
        Write-Error "Template not found: $templatePath"
        exit 1
    }

    $repoRootForConfig = if ($RepoRoot) { $RepoRoot } else { $ClawSeatRoot }
    $repoRootWsl = ConvertTo-ClawSeatWslPath -WindowsPath $repoRootForConfig -Distro $WslDistro
    $clawSeatRootWsl = ConvertTo-ClawSeatWslPath -WindowsPath $ClawSeatRoot -Distro $WslDistro
    $localDir = Join-Path (Join-Path $WindowsAgentsRoot "tasks") $ProjectName
    $localToml = Join-Path $localDir "project-local.toml"
    $templateSeatIds = Get-ClawSeatTemplateSeatIds -TemplatePath $templatePath
    $localLines = New-Object 'System.Collections.Generic.List[string]'
    $localLines.Add("project_name = $(Format-ClawSeatTomlString $ProjectName)")
    $localLines.Add("repo_root = $(Format-ClawSeatTomlString $repoRootWsl)")
    Add-ClawSeatOverride -Lines $localLines -SeatIds $templateSeatIds -SeatId "memory" -Tool $MemoryTool -AuthMode "api" -SeatProvider $Provider -Model $MemoryModel
    Add-ClawSeatOverride -Lines $localLines -SeatIds $templateSeatIds -SeatId "planner" -Tool "claude" -AuthMode "api" -SeatProvider $AllApiProvider -Model $MemoryModel
    Add-ClawSeatOverride -Lines $localLines -SeatIds $templateSeatIds -SeatId "builder" -Tool "claude" -AuthMode "api" -SeatProvider $AllApiProvider -Model $MemoryModel
    Add-ClawSeatOverride -Lines $localLines -SeatIds $templateSeatIds -SeatId "reviewer" -Tool "claude" -AuthMode "api" -SeatProvider $AllApiProvider -Model $MemoryModel
    Add-ClawSeatOverride -Lines $localLines -SeatIds $templateSeatIds -SeatId "patrol" -Tool "claude" -AuthMode "api" -SeatProvider $AllApiProvider -Model $MemoryModel
    $localLines.Add("")
    $localLines.Add("[windows]")
    $localLines.Add("platform = $(Format-ClawSeatTomlString 'windows-wsl')")
    $localLines.Add("runtime = $(Format-ClawSeatTomlString 'wsl')")
    $localLines.Add("wsl_distro = $(Format-ClawSeatTomlString $WslDistro)")
    $localLines.Add("window_driver = $(Format-ClawSeatTomlString 'wezterm-attach')")
    $localLines.Add("clawseat_root = $(Format-ClawSeatTomlString $clawSeatRootWsl)")
    $localContent = $localLines -join "`r`n"

    if ($DryRun) {
        Write-DryRun "Would write bootstrap local TOML to $localToml"
    } else {
        if (-not (Test-Path $localDir)) {
            New-Item -ItemType Directory -Path $localDir -Force | Out-Null
        }
        Write-ClawSeatUtf8NoBom -Path $localToml -Content $localContent
        Write-Success "Bootstrap local config: $localToml"
    }

    $localTomlWsl = ConvertTo-ClawSeatWslPath -WindowsPath $localToml -Distro $WslDistro
    $quotedRepo = Quote-ClawSeatBash $clawSeatRootWsl
    $quotedTemplate = Quote-ClawSeatBash $TemplateName
    $quotedLocal = Quote-ClawSeatBash $localTomlWsl
    Invoke-ClawSeatInstallWsl "cd $quotedRepo && python3 core/scripts/agent_admin.py project bootstrap --template $quotedTemplate --local $quotedLocal"
    Write-Success "WSL project bootstrap requested for: $ProjectName"
}

function Install-PatrolTask {
    param([string]$ProjectName)

    if (-not $EnableAutoPatrol) {
        Write-Warn "Auto-patrol not enabled. Use -EnableAutoPatrol to set up scheduled patrols."
        return
    }

    Write-Warn "Auto-patrol scheduling is not implemented for WSL-first Windows yet. Start patrol seats through launch-windows.ps1."
}

function Write-OperatorGuide {
    param([string]$ProjectName)

    Write-Info "Writing operator guide..."

    $guidePath = Join-Path (Join-Path (Join-Path $WindowsAgentsRoot "tasks") $ProjectName) "OPERATOR-START-HERE.md"
    $guideDir = Split-Path -Parent $guidePath
    if (-not (Test-Path $guideDir)) {
        New-Item -ItemType Directory -Path $guideDir -Force | Out-Null
    }

    $guide = (
        "# ClawSeat Windows - Operator Guide",
        "",
        "## Project: $ProjectName",
        "",
        "### Quick Start",
        "",
        "1. Launch seats: ``.\scripts\launch-windows.ps1 -Project $ProjectName``",
        "2. Run smoke test: ``.\scripts\smoke-windows-tmux.ps1 -Project $ProjectName``",
        "3. Watch WezTerm display windows attach to WSL tmux sessions.",
        "",
        "### Essential Commands",
        "",
        '```powershell',
        ".\scripts\launch-windows.ps1 -Project $ProjectName",
        ".\scripts\smoke-windows-tmux.ps1 -Project $ProjectName",
        '```',
        "",
        "### Windows-Specific Notes",
        "",
        "- **WSL Ubuntu** is the runtime for bash, Python, tmux, git, and AI CLI processes",
        "- **tmux** is the only seat interaction and task transport layer",
        "- **WezTerm** only displays WSL tmux sessions, like iTerm on macOS",
        "- **PowerShell** only detects dependencies and launches WSL/WezTerm wrappers",
        "",
        "### Documentation",
        "",
        "- [Windows Port Notes](docs/WINDOWS.md)",
        "- [Architecture](docs/ARCHITECTURE.md)",
        "- [Install Guide](docs/INSTALL.md)"
    ) -join "`r`n"

    if ($DryRun) {
        Write-DryRun "Would write operator guide to $guidePath"
    } else {
        $guide | Out-File -FilePath $guidePath -Encoding UTF8
        Write-Success "Operator guide: $guidePath"
    }
}

function Install-ClawSeat {
    Write-Host ""
    Write-Host "==============================================================" -ForegroundColor Cyan
    Write-Host "          ClawSeat Windows Installer v$Version" -ForegroundColor Cyan
    Write-Host "             WSL-first WezTerm Edition" -ForegroundColor Cyan
    Write-Host "==============================================================" -ForegroundColor Cyan
    Write-Host ""

    if ($DetectOnly) {
        Write-Info "Running environment detection..."
        $summary = Get-EnvironmentSummary
        Write-Host $summary
        exit 0
    }

    Test-Dependencies

    if ($Project -notmatch '^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$') {
        Write-Error "Project name must match ^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$"
        exit 1
    }

    Initialize-DirectoryStructure
    Install-WezTermConfig
    Initialize-ProjectInWsl -ProjectName $Project -TemplateName $Template
    Install-PatrolTask -ProjectName $Project
    Write-OperatorGuide -ProjectName $Project

    Write-Host ""
    Write-Host "==============================================================" -ForegroundColor Green
    Write-Host "              ClawSeat Install Complete!" -ForegroundColor Green
    Write-Host "==============================================================" -ForegroundColor Green
    Write-Host ""
    Write-Info "Project: $Project"
    Write-Info "Template: $Template"
    Write-Info "Platform: Windows + WSL Ubuntu + WezTerm display"
    Write-Host ""
    Write-Host "Next steps:" -ForegroundColor Yellow
    Write-Host "  1. Launch seats: .\scripts\launch-windows.ps1 -Project $Project"
    Write-Host "  2. Run smoke test: .\scripts\smoke-windows-tmux.ps1 -Project $Project"
    Write-Host "  3. Read operator guide: $WindowsAgentsRoot\tasks\$Project\OPERATOR-START-HERE.md"
    Write-Host ""
}

if ($ShowHelp) {
    Get-Help $MyInvocation.MyCommand.Definition -Full
    exit 0
}

Install-ClawSeat
