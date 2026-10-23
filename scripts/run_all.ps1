# Run all four RecoverPay uAgents in separate PowerShell windows
$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Split-Path -Parent $ScriptDir
Set-Location $RepoRoot

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host "  Starting all four RecoverPay uAgents in separate windows" -ForegroundColor Cyan
Write-Host "  Root: $RepoRoot" -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan

$agents = @(
    @{
        Name = "Orchestrator"
        Module = "agents.orchestrator.agent"
        Port = 8000
        Color = "Green"
    },
    @{
        Name = "Verifier"
        Module = "agents.verifier.agent"
        Port = 8001
        Color = "Yellow"
    },
    @{
        Name = "Fallback"
        Module = "agents.fallback.agent"
        Port = 8002
        Color = "Magenta"
    },
    @{
        Name = "Drafter"
        Module = "agents.drafter.agent"
        Port = 8003
        Color = "Cyan"
    }
)

foreach ($item in $agents) {
    Write-Host "Launching $($item.Name) on port $($item.Port)..." -ForegroundColor $item.Color
    $cmd = "Set-Location '$RepoRoot'; " +
           "if (Test-Path '.venv\Scripts\Activate.ps1') { . .venv\Scripts\Activate.ps1 }; " +
           "`$host.UI.RawUI.WindowTitle = 'RecoverPay $($item.Name) (Port $($item.Port))'; " +
           "python -m $($item.Module)"
    Start-Process powershell.exe -ArgumentList "-NoExit", "-Command", $cmd
}

Write-Host ""
Write-Host "All four agents have been launched in separate windows." -ForegroundColor Green
Write-Host "To talk to Orchestrator, use the Inspector URL printed in its window or connect from ASI:One." -ForegroundColor Gray
Write-Host "To test failure recovery, set `$env:FORCE_FAIL='true' before launching Verifier." -ForegroundColor Gray

