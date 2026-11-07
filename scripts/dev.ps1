# Start the STARK AI API and dashboard together on Windows (what `make dev` does on macOS / Linux).
# Ports come from .env: STARK_WEB_PORT (dashboard, default 3000) and STARK_PORT (API, default 8000).
# Press Ctrl+C to stop both.  Run:  powershell -ExecutionPolicy Bypass -File scripts\dev.ps1
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$EnvFile = Join-Path $Root ".env"
$VenvPy = Join-Path $Root "services\api\.venv\Scripts\python.exe"

if (-not (Test-Path $EnvFile)) { Write-Host "No .env yet: run scripts\setup.ps1 first."; exit 1 }
if (-not (Test-Path $VenvPy)) { Write-Host "API not installed yet: run scripts\setup.ps1 first."; exit 1 }
if (-not (Test-Path (Join-Path $Root "apps\web\node_modules"))) { Write-Host "Dashboard not installed yet: run scripts\setup.ps1 first."; exit 1 }

# Read one KEY=value from .env without executing it
function Get-EnvValue([string]$Key) {
    $line = Get-Content $EnvFile | Where-Object { $_ -match "^$Key=" } | Select-Object -Last 1
    if ($line) { return ($line -replace "^$Key=", "").Trim().Trim('"').Trim("'") }
    return ""
}
$WebPort = if ($env:STARK_WEB_PORT) { $env:STARK_WEB_PORT } else { Get-EnvValue "STARK_WEB_PORT" }
$ApiPort = if ($env:STARK_PORT) { $env:STARK_PORT } else { Get-EnvValue "STARK_PORT" }
if (-not $WebPort) { $WebPort = "3000" }
if (-not $ApiPort) { $ApiPort = "8000" }
if (($WebPort -notmatch '^\d+$') -or ($ApiPort -notmatch '^\d+$')) { Write-Host "STARK_WEB_PORT and STARK_PORT must be numbers"; exit 1 }

foreach ($port in @($WebPort, $ApiPort)) {
    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $client.Connect("127.0.0.1", [int]$port)
        Write-Host "Port $port is already in use by another program. Set STARK_WEB_PORT / STARK_PORT in .env to free ports."
        exit 1
    } catch { } finally { $client.Dispose() }
}

$env:STARK_PORT = $ApiPort
$env:STARK_WEB_ORIGIN = "http://localhost:$WebPort"  # the API only accepts the dashboard on this port
$env:NEXT_PUBLIC_STARK_API_URL = "http://127.0.0.1:$ApiPort"

$api = Start-Process -FilePath $VenvPy -ArgumentList "-m", "stark.main" -WorkingDirectory (Join-Path $Root "services\api") -NoNewWindow -PassThru
$npx = (Get-Command npx.cmd -ErrorAction SilentlyContinue).Source
if (-not $npx) { $npx = (Get-Command npx).Source }
$web = Start-Process -FilePath $npx -ArgumentList "next", "dev", "-H", "127.0.0.1", "-p", $WebPort -WorkingDirectory (Join-Path $Root "apps\web") -NoNewWindow -PassThru

try {
    $ready = $false
    for ($i = 0; $i -lt 40; $i++) {  # wait until the API answers, so a startup error is visible right away
        try { Invoke-WebRequest -UseBasicParsing -TimeoutSec 2 "http://127.0.0.1:$ApiPort/api/health" | Out-Null; $ready = $true; break } catch { Start-Sleep -Milliseconds 500 }
    }
    if ($ready) { Write-Host "STARK AI ready: open http://localhost:$WebPort  (API http://127.0.0.1:$ApiPort)" }
    else { Write-Host "The API did not start on port $ApiPort. See the error above." }
    if ($env:STARK_DEV_EXIT_WHEN_READY -eq "1") { exit ([int](-not $ready)) }  # used by CI
    Wait-Process -Id $api.Id, $web.Id
} finally {
    foreach ($p in @($api, $web)) {
        # a child that is already exiting makes taskkill print an error; stopping is best effort, never a failure
        if ($p -and -not $p.HasExited) {
            $ErrorActionPreference = "Continue"
            try { & taskkill /PID $p.Id /T /F 2>&1 | Out-Null } catch { }
        }
    }
}
