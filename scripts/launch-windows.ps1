#Requires -Version 5.1
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][ValidatePattern('^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$')][string]$Project,
    [string]$WslDistro = "",
    [switch]$NoReset,
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

function Invoke-ClawSeatLaunchWsl {
    param([Parameter(Mandatory=$true)][string]$Command)

    if ($DryRun) {
        Write-Host "[dry-run] wsl bash: $Command" -ForegroundColor Magenta
        return
    }
    Invoke-ClawSeatWslBash -Distro $WslDistro -Command $Command
}

function Join-ClawSeatWindowsArguments {
    param([Parameter(Mandatory=$true)][string[]]$Arguments)

    $quoted = foreach ($arg in $Arguments) {
        $escaped = $arg -replace '([\\]*)"', '$1$1\"'
        $escaped = $escaped -replace '([\\]+)$', '$1$1'
        if ($escaped -match '[\s"]') {
            "`"$escaped`""
        } else {
            $escaped
        }
    }
    return ($quoted -join " ")
}

function Get-ClawSeatSeatWslArguments {
    param([Parameter(Mandatory=$true)][string]$Seat)

    $seatCommand = "cd $quotedRepo && scripts/wait-for-seat.sh $quotedProject $(Quote-ClawSeatBash $Seat)"
    $wslArgs = @()
    if ($WslDistro) {
        $wslArgs += @("-d", $WslDistro)
    }
    return $wslArgs + @("--", "bash", "-lc", $seatCommand)
}

function ConvertTo-ClawSeatPowerShellLiteral {
    param([AllowEmptyString()][string]$Value)

    return "'" + ($Value -replace "'", "''") + "'"
}

function ConvertTo-ClawSeatEncodedPowerShellCommand {
    param([Parameter(Mandatory=$true)][string]$Command)

    $bytes = [System.Text.Encoding]::Unicode.GetBytes($Command)
    return [Convert]::ToBase64String($bytes)
}

function ConvertTo-ClawSeatInlinePowerShellCommand {
    param([Parameter(Mandatory=$true)][string[]]$Arguments)

    return "& " + (($Arguments | ForEach-Object { ConvertTo-ClawSeatPowerShellLiteral $_ }) -join " ")
}

function Start-ClawSeatWezTermLayout {
    param([Parameter(Mandatory=$true)][string[]]$Seats)

    $wezterm = Resolve-ClawSeatWezTerm
    $weztermCli = Resolve-ClawSeatWezTermCli
    if (-not $wezterm -or -not $weztermCli) {
        throw "WezTerm not found. Install with: winget install wez.wezterm"
    }

    Write-Host "WezTerm display: one window for project '$Project' seats '$($Seats -join ', ')'" -ForegroundColor Cyan

    $firstSeat = $Seats[0]
    $firstArgs = @("wsl.exe") + (Get-ClawSeatSeatWslArguments -Seat $firstSeat)
    $bootstrapLines = New-Object System.Collections.Generic.List[string]
    $bootstrapLines.Add("`$ErrorActionPreference = 'Stop'")
    $bootstrapLines.Add("`$weztermCli = $(ConvertTo-ClawSeatPowerShellLiteral $weztermCli)")
    $bootstrapLines.Add("Start-Sleep -Milliseconds 1200")

    if ($Seats.Count -ge 2) {
        $rightCommand = ConvertTo-ClawSeatInlinePowerShellCommand (@("wsl.exe") + (Get-ClawSeatSeatWslArguments -Seat $Seats[1]))
        $bootstrapLines.Add("`$rightSplitOutput = (& `$weztermCli cli --prefer-mux split-pane --right -- powershell.exe -NoExit -Command $(ConvertTo-ClawSeatPowerShellLiteral $rightCommand) 2>&1)")
        $bootstrapLines.Add("`$previousPaneId = `$rightSplitOutput | Where-Object { `$_.ToString().Trim() -match '^[0-9]+$' } | Select-Object -Last 1")
    }

    for ($index = 2; $index -lt $Seats.Count; $index++) {
        $rightCommand = ConvertTo-ClawSeatInlinePowerShellCommand (@("wsl.exe") + (Get-ClawSeatSeatWslArguments -Seat $Seats[$index]))
        $bootstrapLines.Add("if (-not `$previousPaneId) { throw 'WezTerm split-pane did not return a pane id' }")
        $bootstrapLines.Add("`$rightSplitOutput = (& `$weztermCli cli --prefer-mux split-pane --pane-id `$previousPaneId --right -- powershell.exe -NoExit -Command $(ConvertTo-ClawSeatPowerShellLiteral $rightCommand) 2>&1)")
        $bootstrapLines.Add("`$previousPaneId = `$rightSplitOutput | Where-Object { `$_.ToString().Trim() -match '^[0-9]+$' } | Select-Object -Last 1")
    }

    $bootstrapLines.Add((ConvertTo-ClawSeatInlinePowerShellCommand $firstArgs))
    $bootstrap = $bootstrapLines -join "`n"
    $encodedBootstrap = ConvertTo-ClawSeatEncodedPowerShellCommand $bootstrap
    $wezArgs = @("start", "--", "powershell.exe", "-NoExit", "-EncodedCommand", $encodedBootstrap)

    if ($DryRun) {
        Write-Host "[dry-run] $wezterm start -- powershell.exe -NoExit -EncodedCommand $encodedBootstrap" -ForegroundColor Magenta
        return
    }

    Start-Process -FilePath $wezterm -ArgumentList (Join-ClawSeatWindowsArguments $wezArgs) -WindowStyle Normal
}

Assert-ClawSeatWindowsReady -Distro $WslDistro
$repoWslPath = ConvertTo-ClawSeatWslPath -WindowsPath $Script:ClawSeatRoot -Distro $WslDistro
$quotedRepo = Quote-ClawSeatBash $repoWslPath
$quotedProject = Quote-ClawSeatBash $Project
$resetFlag = if ($NoReset) { "" } else { " --reset" }

$seatListCommand = "cd $quotedRepo && python3 - $quotedProject <<'PY'`nfrom pathlib import Path`nimport sys`nimport tomllib`nproject = sys.argv[1]`nproject_file = Path.home() / '.agents' / 'projects' / project / 'project.toml'`nsessions_root = Path.home() / '.agents' / 'sessions' / project`nwith project_file.open('rb') as fh:`n    data = tomllib.load(fh)`nmonitor_seats = data.get('monitor_engineers') or data.get('engineers') or []`nseats = []`nfor seat in monitor_seats:`n    session_file = sessions_root / str(seat) / 'session.toml'`n    if not session_file.is_file():`n        continue`n    with session_file.open('rb') as fh:`n        session = tomllib.load(fh)`n    if session.get('tool') == 'claude' and session.get('auth_mode') == 'api':`n        seats.append(str(seat))`nprint(' '.join(seats))`nPY"
$seatListOutput = Invoke-ClawSeatWslBash -Distro $WslDistro -Command $seatListCommand -Capture
$displaySeats = @($seatListOutput -split '\s+' | Where-Object { $_ })
if (-not $displaySeats) {
    throw "No Claude API monitor seats found for project '$Project'. Run install-windows.ps1 first."
}
$quotedSeatArgs = ($displaySeats | ForEach-Object { Quote-ClawSeatBash $_ }) -join " "
Invoke-ClawSeatLaunchWsl "cd $quotedRepo && CLAWSEAT_ENGINEER_ID=memory CLAWSEAT_ENGINEER_PROFILE=\`$HOME/.agents/engineers/memory/engineer.toml python3 core/scripts/agent_admin.py session batch-start-engineer $quotedSeatArgs --project $quotedProject --accept-override --no-iterm$resetFlag"

Start-ClawSeatWezTermLayout -Seats $displaySeats

Write-Host "ClawSeat Windows launch complete for project '$Project'." -ForegroundColor Green
Write-Host "Task transport remains inside WSL/tmux via send-and-verify.sh." -ForegroundColor Gray
