#Requires -Version 5.1
<#
.SYNOPSIS
    Test
#>

[CmdletBinding()]
param(
    [string]$Project = "install",
    [switch]$DetectOnly
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

Write-Host "OK"
if ($DetectOnly) {
    Write-Host "Detect mode"
    exit 0
}
