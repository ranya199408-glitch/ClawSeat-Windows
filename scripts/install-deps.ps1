#Requires -Version 5.1
<#
.SYNOPSIS
    Install ClawSeat dependencies on Windows

.DESCRIPTION
    Downloads and installs Git, WezTerm, and Python for ClawSeat Windows port.
    No package manager (winget/choco) required.
#>

[CmdletBinding()]
param(
    [switch]$SkipGit,
    [switch]$SkipWezTerm,
    [switch]$SkipPython,
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..") | Select-Object -ExpandProperty Path
$InstallDir = Join-Path $RepoRoot ".deps"
$TempDir = "$env:TEMP\clawseat-deps"

function Write-Info { param([string]$Message) Write-Host "==> $Message" -ForegroundColor Cyan }
function Write-Success { param([string]$Message) Write-Host "  [OK] $Message" -ForegroundColor Green }
function Write-Warn { param([string]$Message) Write-Host "  [WARN] $Message" -ForegroundColor Yellow }
function Write-Error { param([string]$Message) Write-Host "  [ERR] $Message" -ForegroundColor Red }

function Test-Command {
    param([string]$Command)
    $null -ne (Get-Command $Command -ErrorAction SilentlyContinue)
}

function Install-Git {
    if (Test-Command "git") {
        Write-Success "Git already installed"
        return
    }

    Write-Info "Downloading Git for Windows..."
    $gitUrl = "https://github.com/git-for-windows/git/releases/download/v2.49.0.windows.1/Git-2.49.0-64-bit.exe"
    $gitInstaller = "$TempDir\git-installer.exe"

    if ($DryRun) {
        Write-Host "  [dry-run] Would download Git from $gitUrl"
        return
    }

    if (-not (Test-Path $TempDir)) {
        New-Item -ItemType Directory -Path $TempDir -Force | Out-Null
    }

    Invoke-WebRequest -Uri $gitUrl -OutFile $gitInstaller -UseBasicParsing
    Write-Success "Git installer downloaded"

    Write-Info "Installing Git..."
    $gitInstallDir = "$InstallDir\Git"
    Start-Process -FilePath $gitInstaller -ArgumentList "/VERYSILENT", "/NORESTART", "/NOCANCEL", "/SP-", "/CLOSEAPPLICATIONS", "/RESTARTAPPLICATIONS", "/DIR=`"$gitInstallDir`"" -Wait
    Write-Success "Git installed to $gitInstallDir"

    # Add to PATH for current session
    $env:PATH = "$gitInstallDir\cmd;$env:PATH"
    # Add to system PATH
    # PATH updated for current session only (sandbox environment)

    Remove-Item $gitInstaller -ErrorAction SilentlyContinue
}

function Install-WezTerm {
    if (Test-Command "wezterm") {
        Write-Success "WezTerm already installed"
        return
    }

    Write-Info "Downloading WezTerm..."
    $weztermUrl = "https://github.com/wez/wezterm/releases/download/20240203-110809-5046fc22/WezTerm-windows-20240203-110809-5046fc22.zip"
    $weztermZip = "$TempDir\wezterm.zip"

    if ($DryRun) {
        Write-Host "  [dry-run] Would download WezTerm from $weztermUrl"
        return
    }

    if (-not (Test-Path $TempDir)) {
        New-Item -ItemType Directory -Path $TempDir -Force | Out-Null
    }

    Invoke-WebRequest -Uri $weztermUrl -OutFile $weztermZip -UseBasicParsing
    Write-Success "WezTerm archive downloaded"

    Write-Info "Extracting WezTerm..."
    $weztermDir = "$InstallDir\WezTerm"
    if (Test-Path $weztermDir) {
        Remove-Item $weztermDir -Recurse -Force
    }
    Expand-Archive -Path $weztermZip -DestinationPath $weztermDir -Force
    Write-Success "WezTerm extracted to $weztermDir"

    # Add to PATH for current session
    $env:PATH = "$weztermDir;$env:PATH"
    # Add to system PATH
    # PATH updated for current session only (sandbox environment)

    Remove-Item $weztermZip -ErrorAction SilentlyContinue
}

function Install-Python {
    if (Test-Command "python") {
        $pyVersion = (python --version 2>&1).ToString()
        if ($pyVersion -match "Python (\d+)\.(\d+)") {
            $major = [int]$matches[1]
            $minor = [int]$matches[2]
            if ($major -eq 3 -and $minor -ge 11) {
                Write-Success "Python $major.$minor already installed"
                return
            }
        }
    }

    Write-Info "Downloading Python 3.12..."
    $pythonUrl = "https://www.python.org/ftp/python/3.12.9/python-3.12.9-amd64.exe"
    $pythonInstaller = "$TempDir\python-installer.exe"

    if ($DryRun) {
        Write-Host "  [dry-run] Would download Python from $pythonUrl"
        return
    }

    if (-not (Test-Path $TempDir)) {
        New-Item -ItemType Directory -Path $TempDir -Force | Out-Null
    }

    Invoke-WebRequest -Uri $pythonUrl -OutFile $pythonInstaller -UseBasicParsing
    Write-Success "Python installer downloaded"

    Write-Info "Installing Python..."
    $pythonInstallDir = "$InstallDir\Python312"
    Start-Process -FilePath $pythonInstaller -ArgumentList "/quiet", "InstallAllUsers=0", "PrependPath=1", "TargetDir=`"$pythonInstallDir`"" -Wait
    Write-Success "Python installed to $pythonInstallDir"

    # Add to PATH for current session
    $env:PATH = "$pythonInstallDir;$pythonInstallDir\Scripts;$env:PATH"

    Remove-Item $pythonInstaller -ErrorAction SilentlyContinue
}

# ============================================================================
# Main
# ============================================================================
Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "       ClawSeat Dependency Installer for Windows" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

if (-not (Test-Path $InstallDir)) {
    New-Item -ItemType Directory -Path $InstallDir -Force | Out-Null
}

if (-not $SkipGit) { Install-Git }
if (-not $SkipWezTerm) { Install-WezTerm }
if (-not $SkipPython) { Install-Python }

Write-Host ""
Write-Host "============================================================" -ForegroundColor Green
Write-Host "              Dependency Install Complete!" -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Green
Write-Host ""
Write-Host "Please restart your terminal for PATH changes to take effect." -ForegroundColor Yellow
Write-Host ""
Write-Host "Next step: Run the ClawSeat installer:" -ForegroundColor Cyan
Write-Host "  .\scripts\install-windows.ps1 -Project myapp" -ForegroundColor White
Write-Host ""
