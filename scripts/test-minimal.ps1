param(
    [string]$Project = "install",
    [switch]$DetectOnly
)

if ($DetectOnly) {
    Write-Host "Detect mode activated"
    exit 0
}

Write-Host "Project: $Project"
