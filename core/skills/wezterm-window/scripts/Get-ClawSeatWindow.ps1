#Requires -Version 5.1
<#
.SYNOPSIS
    Get information about running ClawSeat WezTerm windows.

.DESCRIPTION
    Lists all WezTerm processes and filters for ClawSeat agent windows.
    Matches by window title (MainWindowTitle) which is set by the temp script.

.PARAMETER Project
    Filter by project name.

.PARAMETER Seat
    Filter by seat name.

.PARAMETER ClawSeatRoot
    Path to ClawSeat installation.

.EXAMPLE
    Get-ClawSeatWindow

.EXAMPLE
    Get-ClawSeatWindow -Project "demo" -Seat "builder-1"
#>
[CmdletBinding()]
param(
    [string]$Project = "",

    [string]$Seat = "",

    [string]$ClawSeatRoot = $env:CLAWSEAT_ROOT
)

$ErrorActionPreference = "Stop"

# Find all wezterm-gui processes with non-empty titles
$weztermProcs = Get-Process wezterm-gui -ErrorAction SilentlyContinue | Where-Object { $_.MainWindowTitle -and $_.MainWindowTitle -ne '' } | ForEach-Object {
    # Parse project/seat from title (format: project-seat)
    $proj = ""
    $seatName = ""
    $title = $_.MainWindowTitle

    # Match project-seat pattern: project can have hyphens, seat is the last hyphen-separated part
    if ($title -match '^(.+)-([a-zA-Z0-9_-]+)$') {
        $proj = $matches[1]
        $seatName = $matches[2]
    }

    [PSCustomObject]@{
        PID         = $_.Id
        Title       = $title
        Project     = $proj
        Seat        = $seatName
        StartTime   = $_.StartTime
        Process     = $_
    }
}

# Filter for ClawSeat windows (title matches project-seat pattern)
$clawSeatWindows = $weztermProcs | Where-Object { $_.Project -and $_.Seat }

# Apply filters
if ($Project) {
    $clawSeatWindows = $clawSeatWindows | Where-Object { $_.Project -eq $Project }
}

if ($Seat) {
    $clawSeatWindows = $clawSeatWindows | Where-Object { $_.Seat -eq $Seat }
}

$clawSeatWindows
