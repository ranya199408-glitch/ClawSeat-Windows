#Requires -Version 5.1
[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [ValidatePattern('^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$')]
    [string]$Project,

    [Parameter(Mandatory)]
    [ValidatePattern('^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$')]
    [string]$Seat,

    [Parameter(Mandatory)]
    [string]$Command,

    [string]$ClawSeatRoot = $env:CLAWSEAT_ROOT,
    [string]$WslDistro = "",
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"

if (-not $ClawSeatRoot) {
    $scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
    $ClawSeatRoot = Resolve-Path (Join-Path (Join-Path (Join-Path (Join-Path $scriptDir "..") "..") "..") "..") | Select-Object -ExpandProperty Path
}

$supportScript = Join-Path (Join-Path $ClawSeatRoot "scripts") "windows-support.ps1"
. $supportScript

function Quote-ClawSeatBash {
    param([Parameter(Mandatory=$true)][string]$Value)
    $escaped = $Value -replace "'", "'\''"
    return "'" + $escaped + "'"
}

$repoWslPath = ConvertTo-ClawSeatWslPath -WindowsPath $ClawSeatRoot -Distro $WslDistro
$quotedRepo = Quote-ClawSeatBash $repoWslPath
$quotedProject = Quote-ClawSeatBash $Project
$quotedSeat = Quote-ClawSeatBash $Seat
$quotedCommand = Quote-ClawSeatBash $Command
$wslCommand = "cd $quotedRepo && core/shell-scripts/send-and-verify.sh --project $quotedProject $quotedSeat $quotedCommand"

if ($DryRun) {
    Write-Host "[dry-run] wsl bash: $wslCommand" -ForegroundColor Magenta
    return
}

Invoke-ClawSeatWslBash -Distro $WslDistro -Command $wslCommand
