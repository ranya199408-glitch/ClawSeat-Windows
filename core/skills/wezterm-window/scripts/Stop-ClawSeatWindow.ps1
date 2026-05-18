#Requires -Version 5.1
<#
.SYNOPSIS
    Stop a ClawSeat WezTerm window.

.DESCRIPTION
    Kills a WezTerm process for a specific ClawSeat agent seat.

.PARAMETER Project
    The project name.

.PARAMETER Seat
    The seat name.

.PARAMETER PID
    Direct process ID (alternative to Project/Seat lookup).

.PARAMETER ClawSeatRoot
    Path to ClawSeat installation.

.EXAMPLE
    Stop-ClawSeatWindow -Project "demo" -Seat "builder-1"

.EXAMPLE
    Stop-ClawSeatWindow -PID 12345
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory, ParameterSetName = "BySeat")]
    [string]$Project,

    [Parameter(Mandatory, ParameterSetName = "BySeat")]
    [string]$Seat,

    [Parameter(Mandatory, ParameterSetName = "ByPID")]
    [int]$ProcessId = 0,

    [string]$ClawSeatRoot = $env:CLAWSEAT_ROOT
)

$ErrorActionPreference = "Stop"

# Resolve ProcessId if not provided directly
$targetPid = $ProcessId
if (-not $targetPid -and $Project -and $Seat) {
    $scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
    $getWindowScript = Join-Path $scriptDir "Get-ClawSeatWindow.ps1"

    $window = & $getWindowScript -Project $Project -Seat $Seat -ClawSeatRoot $ClawSeatRoot | Select-Object -First 1

    if (-not $window) {
        Write-Warning "Window not found for $Project-$Seat"
        return
    }

    $targetPid = $window.PID
    Write-Verbose "Resolved PID: $targetPid for $Project-$Seat"
}

# Kill the process
$proc = Get-Process -Id $targetPid -ErrorAction SilentlyContinue
if (-not $proc) {
    Write-Warning "Process $targetPid not found"
    return
}

Write-Verbose "Killing process $targetPid ($($proc.ProcessName))"
Stop-Process -Id $targetPid -Force

Write-Verbose "Process $targetPid killed successfully"
