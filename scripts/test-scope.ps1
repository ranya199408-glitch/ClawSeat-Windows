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

Write-Host "OK"
if ($DetectOnly) {
    Write-Host "Detect mode"
    exit 0
}
