#Requires -Version 5.1
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][ValidatePattern('^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$')][string]$Project,
    [string]$WslDistro = "",
    [ValidatePattern('^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$')]
    [string[]]$Seats = @("builder", "reviewer"),
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"
$SupportScript = Join-Path $PSScriptRoot "windows-support.ps1"
. $SupportScript

function Quote-ClawSeatBash {
    param([Parameter(Mandatory=$true)][string]$Value)
    $escaped = $Value -replace "'", "'\''"
    return "'" + $escaped + "'"
}

function Invoke-ClawSeatSmokeWsl {
    param([Parameter(Mandatory=$true)][string]$Command)

    if ($DryRun) {
        Write-Host "[dry-run] wsl bash: $Command" -ForegroundColor Magenta
        return "SENT: dry-run"
    }
    return Invoke-ClawSeatWslBash -Distro $WslDistro -Capture -Command $Command
}

Assert-ClawSeatWindowsReady -Distro $WslDistro
$repoWslPath = ConvertTo-ClawSeatWslPath -WindowsPath $Script:ClawSeatRoot -Distro $WslDistro
$quotedRepo = Quote-ClawSeatBash $repoWslPath
$quotedProject = Quote-ClawSeatBash $Project

foreach ($seat in $Seats) {
    $message = "Windows smoke probe for $Project/$seat"
    $quotedSeat = Quote-ClawSeatBash $seat
    $quotedMessage = Quote-ClawSeatBash $message
    $command = "cd $quotedRepo && core/shell-scripts/send-and-verify.sh --project $quotedProject $quotedSeat $quotedMessage"
    $output = Invoke-ClawSeatSmokeWsl $command
    $text = ($output -join "`n").Trim()

    if (-not $text.StartsWith("SENT:")) {
        throw "Smoke probe for seat '$seat' did not return SENT:. Output: $text"
    }
    Write-Host "Smoke probe delivered to ${seat}: $text" -ForegroundColor Green
}

Write-Host "ClawSeat Windows tmux smoke complete for project '$Project'." -ForegroundColor Green
