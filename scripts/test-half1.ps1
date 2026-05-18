#Requires -Version 5.1
<#
.SYNOPSIS
    ClawSeat Windows Installer - WezTerm Edition
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

$Script:Version = "0.2.1-windows"
$Script:ErrorActionPreference = "Stop"
$Script:ProgressPreference = "SilentlyContinue"

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
$AgentsRoot = Join-Path $UserProfile ".agents"
$ClawSeatConfigDir = Join-Path $UserProfile ".clawseat"
$WezTermConfigDir = Join-Path $UserProfile ".config" "wezterm"

function Write-Info { param([string]$Message) Write-Host "==> $Message" -ForegroundColor Cyan }
function Write-Success { param([string]$Message) Write-Host "  [OK] $Message" -ForegroundColor Green }
function Write-Warn { param([string]$Message) Write-Host "  [WARN] $Message" -ForegroundColor Yellow }
function Write-Error { param([string]$Message) Write-Host "  [ERR] $Message" -ForegroundColor Red }
function Write-DryRun { param([string]$Message) Write-Host "  [dry-run] $Message" -ForegroundColor Magenta }

function Test-Command {
    param([string]$Command)
    $null -ne (Get-Command $Command -ErrorAction SilentlyContinue)
}

function Invoke-DryRunAware {
    param(
        [scriptblock]$Action,
        [string]$Description
    )
    if ($DryRun) {
        Write-DryRun $Description
        return $null
    }
    Write-Info $Description
    return & $Action
}

function Test-Dependencies {
    Write-Info "Checking dependencies..."
    $deps = @{
        "wezterm" = "WezTerm terminal emulator"
        "git" = "Git version control"
        "python" = "Python 3.11+"
    }

    $missing = @()
    foreach ($cmd in $deps.Keys) {
        if (Test-Command $cmd) {
            Write-Success "$($deps[$cmd]) found"
        } else {
            Write-Error "$($deps[$cmd]) not found"
            $missing += $cmd
        }
    }

    if (Test-Command "python") {
        $pyVersion = (python --version 2>&1).ToString()
        if ($pyVersion -match "Python (\d+)\.(\d+)") {
            $major = [int]$matches[1]
            $minor = [int]$matches[2]
            if ($major -lt 3 -or ($major -eq 3 -and $minor -lt 11)) {
                Write-Error "Python $major.$minor found, but 3.11+ required"
                $missing += "python-version"
            } else {
                Write-Success "Python $major.$minor meets requirement"
            }
        }
    }

    if (Test-Command "tmux") {
        Write-Success "tmux found"
    } else {
        Write-Warn "tmux not found. Install via Git Bash or WSL for best experience"
    }

    if ($missing.Count -gt 0) {
        Write-Error "Missing required dependencies: $($missing -join ', ')"
        Write-Host ""
        Write-Host "Install instructions:" -ForegroundColor Yellow
        Write-Host "  WezTerm:  winget install wez.wezterm"
        Write-Host "  Git:      winget install git.git"
        Write-Host "  Python:   winget install python.python.3.11"
        Write-Host "  tmux:     Install Git Bash, then: pacman -S tmux"
        exit 1
    }
}

function Get-EnvironmentSummary {
    $oauth = @{}
    $tools = @("claude", "codex", "gemini")
    foreach ($tool in $tools) {
        $configDir = Join-Path $UserProfile ".$tool"
        if (Test-Path $configDir) {
            $oauth[$tool] = "oauth"
        } else {
            $oauth[$tool] = "missing"
        }
    }

    $envKeys = Get-ChildItem env: | Where-Object {
        $_.Name -match "ANTHROPIC|OPENAI|GEMINI|MINIMAX|DEEPSEEK"
    }

    $existingProjects = @()
    $projectsDir = Join-Path $AgentsRoot "projects"
    if (Test-Path $projectsDir) {
        $existingProjects = Get-ChildItem $projectsDir -Directory | Select-Object -ExpandProperty Name
    }

    return @{
        oauth = $oauth
        pty = @{ used = 0; total = 256; warn = $false }
        branch = @{ branch = "main"; warn = $false }
        existing_projects = $existingProjects
        api_keys_found = ($envKeys | Measure-Object).Count
        platform = "windows"
        timestamp = (Get-Date -Format "yyyy-MM-ddTHH:mm:ssZ")
    } | ConvertTo-Json -Depth 4
}

Write-Host "HALF 1 LOADED OK"
if ($DetectOnly) {
    Write-Host $env:COMPUTERNAME
    exit 0
}
