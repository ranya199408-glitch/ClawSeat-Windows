param(
    [string]$Project = "install",
    [switch]$DetectOnly
)

$Script:ErrorActionPreference = "Stop"
$UserProfile = $env:USERPROFILE
$AgentsRoot = Join-Path $UserProfile ".agents"

function Get-EnvironmentSummary {
    $oauth = @{}
    $tools = @("claude", "codex", "gemini")
    foreach ($tool in $tools) {
        $configDir = Join-Path $UserProfile ".$tool"
        if (Test-Path $configDir) {
            $oauth[$tool] = "oauth"
        } else {
            $oauth[$tool] = "missing"
        }
    }

    $envKeys = Get-ChildItem env: | Where-Object {
        $_.Name -match "ANTHROPIC|OPENAI|GEMINI|MINIMAX|DEEPSEEK"
    }

    $existingProjects = @()
    $projectsDir = Join-Path $AgentsRoot "projects"
    if (Test-Path $projectsDir) {
        $existingProjects = Get-ChildItem $projectsDir -Directory | Select-Object -ExpandProperty Name
    }

    return @{
        oauth = $oauth
        pty = @{ used = 0; total = 256; warn = $false }
        branch = @{ branch = "main"; warn = $false }
        existing_projects = $existingProjects
        api_keys_found = ($envKeys | Measure-Object).Count
        platform = "windows"
        timestamp = (Get-Date -Format "yyyy-MM-ddTHH:mm:ssZ")
    } | ConvertTo-Json -Depth 4
}

Write-Host "OK"
if ($DetectOnly) {
    $summary = Get-EnvironmentSummary
    Write-Host $summary
    exit 0
}
