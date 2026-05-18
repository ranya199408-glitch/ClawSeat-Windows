#Requires -Version 5.1
$Script:ClawSeatSupportDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$Script:ClawSeatRoot = Resolve-Path (Join-Path $Script:ClawSeatSupportDir "..") | Select-Object -ExpandProperty Path

function Test-ClawSeatCommand {
    param([Parameter(Mandatory=$true)][string]$Command)
    return $null -ne (Get-Command $Command -ErrorAction SilentlyContinue)
}

function Resolve-ClawSeatWezTermCli {
    $candidates = @(
        @(
            (Get-Command "wezterm.exe" -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source -ErrorAction SilentlyContinue),
            (Join-Path $Script:ClawSeatRoot ".deps\WezTerm\WezTerm-windows-20240203-110809-5046fc22\wezterm.exe"),
            "C:\Program Files\WezTerm\wezterm.exe"
        ) | Where-Object { $_ -and (Test-Path $_) }
    )

    if ($candidates.Count -gt 0) {
        return $candidates[0]
    }
    return ""
}

function Resolve-ClawSeatWezTerm {
    $weztermCommand = Resolve-ClawSeatWezTermCli
    $weztermGuiFromPath = if ($weztermCommand) { Join-Path (Split-Path -Parent $weztermCommand) "wezterm-gui.exe" } else { "" }
    $candidates = @(
        @(
            $weztermGuiFromPath,
            (Join-Path $Script:ClawSeatRoot ".deps\WezTerm\WezTerm-windows-20240203-110809-5046fc22\wezterm-gui.exe"),
            "C:\Program Files\WezTerm\wezterm-gui.exe",
            $weztermCommand
        ) | Where-Object { $_ -and (Test-Path $_) }
    )

    if ($candidates.Count -gt 0) {
        return $candidates[0]
    }
    return ""
}

function Invoke-ClawSeatWslRaw {
    param(
        [Parameter(Mandatory=$true)][string[]]$Arguments,
        [string]$Distro = ""
    )

    $wslArgs = @()
    if ($Distro) {
        $wslArgs += @("-d", $Distro)
    }
    $wslArgs += $Arguments

    return & wsl.exe @wslArgs
}

function Invoke-ClawSeatWslBash {
    param(
        [Parameter(Mandatory=$true)][string]$Command,
        [string]$Distro = "",
        [switch]$Capture
    )

    $args = @()
    if ($Distro) {
        $args += @("-d", $Distro)
    }
    $args += @("--", "bash", "-lc", $Command)

    if ($Capture) {
        $output = & wsl.exe @args 2>&1
        if ($LASTEXITCODE -ne 0) {
            throw "WSL command failed with exit ${LASTEXITCODE}: $Command"
        }
        return $output
    }
    & wsl.exe @args
    if ($LASTEXITCODE -ne 0) {
        throw "WSL command failed with exit ${LASTEXITCODE}: $Command"
    }
}

function ConvertTo-ClawSeatWslPath {
    param(
        [Parameter(Mandatory=$true)][string]$WindowsPath,
        [string]$Distro = ""
    )

    $fullPath = [System.IO.Path]::GetFullPath($WindowsPath)
    $escaped = $fullPath -replace "'", "'\''"
    $output = Invoke-ClawSeatWslBash -Distro $Distro -Capture -Command "wslpath -a '$escaped'"
    $path = ($output | Select-Object -First 1).ToString().Trim()
    if (-not $path) {
        throw "Failed to convert Windows path to WSL path: $WindowsPath"
    }
    return $path
}

function Get-ClawSeatWindowsDependencySummary {
    param([string]$Distro = "")

    $wezterm = Resolve-ClawSeatWezTerm
    $wslInstalled = Test-ClawSeatCommand "wsl.exe"
    $distroFound = $false
    $distroName = $Distro

    if ($wslInstalled) {
        if ($Distro) {
            & wsl.exe -d $Distro -- true 2>$null
            $distroFound = $LASTEXITCODE -eq 0
        } else {
            $defaultDistro = (& wsl.exe -- bash -lc 'printf "%s" "$WSL_DISTRO_NAME"' 2>$null) -join ""
            $distroName = ($defaultDistro -replace "`0", "").Trim()
            $distroFound = [bool]$distroName
        }
    }

    return [ordered]@{
        platform = "windows"
        powershell = $PSVersionTable.PSVersion.ToString()
        wsl = @{ found = $wslInstalled; distro = $distroName; distro_found = $distroFound }
        wezterm = @{ found = [bool]$wezterm; path = $wezterm }
    }
}

function Get-ClawSeatWslDependencySummary {
    param([string]$Distro = "")

    if (-not (Test-ClawSeatCommand "wsl.exe")) {
        return [ordered]@{ available = $false; reason = "wsl.exe not found" }
    }

    $probe = @'
set +e
printf '{'
printf '"available":true,'
printf '"bash":'; command -v bash >/dev/null 2>&1 && printf 'true' || printf 'false'; printf ','
printf '"python3":'; command -v python3 >/dev/null 2>&1 && printf 'true' || printf 'false'; printf ','
printf '"git":'; command -v git >/dev/null 2>&1 && printf 'true' || printf 'false'; printf ','
printf '"tmux":'; command -v tmux >/dev/null 2>&1 && printf 'true' || printf 'false'; printf ','
printf '"claude":'; command -v claude >/dev/null 2>&1 && printf 'true' || printf 'false'; printf ','
printf '"codex":'; command -v codex >/dev/null 2>&1 && printf 'true' || printf 'false'; printf ','
printf '"gemini":'; command -v gemini >/dev/null 2>&1 && printf 'true' || printf 'false'
printf '}'
'@

    $json = (Invoke-ClawSeatWslBash -Distro $Distro -Capture -Command $probe) -join ""
    try {
        return $json | ConvertFrom-Json
    } catch {
        return [ordered]@{ available = $false; reason = "failed to parse WSL dependency probe"; raw = $json }
    }
}

function Assert-ClawSeatWindowsReady {
    param([string]$Distro = "")

    $windows = Get-ClawSeatWindowsDependencySummary -Distro $Distro
    $wsl = Get-ClawSeatWslDependencySummary -Distro $Distro
    $errors = @()

    if (-not $windows.wsl.found) { $errors += "Install WSL: wsl --install -d Ubuntu" }
    if (-not $windows.wsl.distro_found) { $errors += "Install or select a WSL distro: wsl --install -d Ubuntu" }
    if (-not $windows.wezterm.found) { $errors += "Install WezTerm: winget install wez.wezterm" }
    if (-not $wsl.available) { $errors += "WSL probe failed: $($wsl.reason)" }
    foreach ($name in @("bash", "python3", "git", "tmux")) {
        if ($wsl.available -and -not $wsl.$name) { $errors += "Install $name inside WSL Ubuntu" }
    }

    if ($errors.Count -gt 0) {
        throw ($errors -join "`n")
    }
}
