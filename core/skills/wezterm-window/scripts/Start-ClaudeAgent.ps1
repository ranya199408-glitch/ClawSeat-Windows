#Requires -Version 5.1
[CmdletBinding()]
param(
    [Parameter(Mandatory, Position = 0)]
    [ValidatePattern('^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$')]
    [string]$Project,

    [Parameter(Mandatory, Position = 1)]
    [ValidatePattern('^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$')]
    [string]$Seat,

    [string]$Role = "ClawSeat Agent",
    [string]$WorkingDir = $PWD,
    [string]$WelcomeColor = "Cyan",
    [hashtable]$ExtraEnv = @{},
    [string]$ClawSeatRoot = $env:CLAWSEAT_ROOT,
    [string]$WslDistro = "",
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"

if (-not $ClawSeatRoot) {
    $scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
    $ClawSeatRoot = Resolve-Path (Join-Path (Join-Path (Join-Path (Join-Path $scriptDir "..") "..") "..") "..") | Select-Object -ExpandProperty Path
}

$launcher = Join-Path $ClawSeatRoot "scripts\launch-windows.ps1"
$argsList = @("-Project", $Project, "-NoReset")
if ($WslDistro) { $argsList += @("-WslDistro", $WslDistro) }
if ($DryRun) { $argsList += "-DryRun" }

& $launcher @argsList
