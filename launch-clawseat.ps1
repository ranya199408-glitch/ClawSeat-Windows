#Requires -Version 5.1
[CmdletBinding()]
param(
    [ValidatePattern('^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$')][string]$Project = "demo",
    [string]$WslDistro = "",
    [switch]$Reset,
    [switch]$DryRun
)

$launcher = Join-Path $PSScriptRoot "scripts\launch-windows.ps1"
$launchArgs = @{ Project = $Project }
if ($WslDistro) { $launchArgs.WslDistro = $WslDistro }
if ($DryRun) { $launchArgs.DryRun = $true }

& $launcher @launchArgs
