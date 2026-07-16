[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"

$Project = Split-Path -Parent $PSScriptRoot
$RuntimeRoot = Join-Path $Project ".runtime"
$LogRoot = Join-Path $Project "logs"
$Python = Join-Path $Project ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $Python)) {
    $Python = Join-Path (Split-Path -Parent $Project) "Vibe-Trading\.venv\Scripts\python.exe"
}
$GatewayRoot = "C:\Users\Admin\Documents\Codex\2026-07-13\git-2\CLIProxyAPI"
$GatewayExe = Join-Path $GatewayRoot "bin\cli-proxy-api.exe"
$GatewayConfig = Join-Path $GatewayRoot "config.yaml"
$GatewayPid = Join-Path $GatewayRoot "temp\cli-proxy-api.pid"
$WatchdogPid = Join-Path $RuntimeRoot "watchdog.pid"
$WatchdogLog = Join-Path $LogRoot "watchdog.log"
$WebStdout = Join-Path $LogRoot "server.out.log"
$WebStderr = Join-Path $LogRoot "server.err.log"
$GatewayStdout = Join-Path $LogRoot "gateway.out.log"
$GatewayStderr = Join-Path $LogRoot "gateway.err.log"

New-Item -ItemType Directory -Force -Path $RuntimeRoot, $LogRoot | Out-Null

# Windows PowerShell Start-Process rejects environments containing both Path
# and PATH. Keep one canonical entry before spawning child processes.
$processPath = [Environment]::GetEnvironmentVariable("Path", "Process")
if (-not $processPath) { $processPath = [Environment]::GetEnvironmentVariable("PATH", "Process") }
[Environment]::SetEnvironmentVariable("PATH", $null, "Process")
[Environment]::SetEnvironmentVariable("Path", $processPath, "Process")

function Write-Log([string]$Message) {
    try {
        Add-Content -LiteralPath $WatchdogLog -Encoding UTF8 -Value ("{0} {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $Message)
    } catch { }
}

function Test-Web {
    try {
        $response = Invoke-WebRequest -UseBasicParsing -TimeoutSec 3 -Uri "http://127.0.0.1:8900/health"
        return $response.StatusCode -eq 200
    } catch { return $false }
}

function Test-Port([int]$Port) {
    $match = & "$env:SystemRoot\System32\netstat.exe" -ano -p TCP 2>$null |
        Select-String -Pattern (":{0}\s+.*LISTENING" -f $Port)
    return [bool]$match
}

function Start-Web {
    if (-not (Test-Path -LiteralPath $Python)) {
        Write-Log "Python environment is missing."
        return $null
    }
    try {
        $process = Start-Process -FilePath $Python `
            -ArgumentList @("-m", "cli._legacy", "serve", "--port", "8900", "--host", "127.0.0.1") `
            -WorkingDirectory $Project -WindowStyle Hidden `
            -RedirectStandardOutput $WebStdout -RedirectStandardError $WebStderr -PassThru
        Write-Log "Started analysis service PID=$($process.Id)."
        return $process
    } catch {
        Write-Log "Analysis service start failed: $($_.Exception.Message)"
        return $null
    }
}

function Start-Gateway {
    if (-not (Test-Path -LiteralPath $GatewayExe)) {
        Write-Log "Local GPT gateway executable is missing."
        return $null
    }
    try {
        Remove-Item -LiteralPath $GatewayPid -Force -ErrorAction SilentlyContinue
        $process = Start-Process -FilePath $GatewayExe -ArgumentList @("--config", $GatewayConfig) `
            -WorkingDirectory $GatewayRoot -WindowStyle Hidden `
            -RedirectStandardOutput $GatewayStdout -RedirectStandardError $GatewayStderr -PassThru
        Write-Log "Started local GPT gateway PID=$($process.Id)."
        return $process
    } catch {
        Write-Log "Local GPT gateway start failed: $($_.Exception.Message)"
        return $null
    }
}

$env:HOME = $RuntimeRoot
$env:USERPROFILE = $RuntimeRoot
$env:MPLCONFIGDIR = Join-Path $RuntimeRoot ".matplotlib"
$env:NO_PROXY = "127.0.0.1,localhost"
$env:no_proxy = "127.0.0.1,localhost"
$env:PYTHONPATH = "$(Join-Path $Project 'agent');$($env:PYTHONPATH)"
$env:VIBE_TRADING_ENABLE_BROKERAGE = "false"

$createdNew = $false
$mutex = [Threading.Mutex]::new($true, "Local\VibeAnalysisWatchdog", [ref]$createdNew)
if (-not $createdNew) { $mutex.Dispose(); exit 0 }

Set-Content -LiteralPath $WatchdogPid -Value $PID -Encoding ASCII
Write-Log "Watchdog started PID=$PID."
$web = $null
$gateway = $null

try {
    while ($true) {
        try {
            if (-not (Test-Web)) {
                if ($null -eq $web -or $web.HasExited) { $web = Start-Web }
            }
            if (-not (Test-Port 8317)) {
                if ($null -eq $gateway -or $gateway.HasExited) { $gateway = Start-Gateway }
            }
        } catch { Write-Log "Health iteration failed: $($_.Exception.Message)" }
        Start-Sleep -Seconds 3
    }
} finally {
    Remove-Item -LiteralPath $WatchdogPid -Force -ErrorAction SilentlyContinue
    try { $mutex.ReleaseMutex() } catch { }
    $mutex.Dispose()
}
