# STARK AI setup for Windows (PowerShell 5.1 or 7). Does what `make setup` does on macOS / Linux:
# creates the API's Python environment, installs the dashboard, and creates .env with a random API token.
# Run from the repository folder:  powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Api = Join-Path $Root "services\api"
$Web = Join-Path $Root "apps\web"
$VenvPy = Join-Path $Api ".venv\Scripts\python.exe"

function Test-Python311([string[]]$Cmd) {
    try {
        $exe = $Cmd[0]
        $rest = @($Cmd | Select-Object -Skip 1)
        & $exe @rest -c "import sys; sys.exit(sys.version_info < (3, 11))" 2>$null
        return ($LASTEXITCODE -eq 0)
    } catch { return $false }
}

# 1. Find Python 3.11+ (the py launcher first, then python on PATH)
$Python = $null
foreach ($candidate in @(@("py", "-3.13"), @("py", "-3.12"), @("py", "-3.11"), @("python"))) {
    if (Test-Python311 $candidate) { $Python = $candidate; break }
}
if (-not $Python) {
    Write-Host "Python 3.11 or newer was not found. Install Python 3.12 from https://www.python.org/downloads/windows/"
    Write-Host "(tick 'Add python.exe to PATH'), then run this script again."
    exit 1
}
if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
    Write-Host "Node.js 20 or newer was not found. Install the LTS version from https://nodejs.org, then run this script again."
    exit 1
}

# 2. API environment (a broken or too-old .venv is rebuilt)
if ((Test-Path $VenvPy) -and -not (Test-Python311 @($VenvPy))) { Remove-Item -Recurse -Force (Join-Path $Api ".venv") }
if (-not (Test-Path $VenvPy)) {
    Write-Host "Creating the Python environment in services\api\.venv ..."
    $exe = $Python[0]
    $rest = @($Python | Select-Object -Skip 1)
    & $exe @rest -m venv (Join-Path $Api ".venv")
    if ($LASTEXITCODE -ne 0) { throw "Could not create the Python environment." }
}
Push-Location $Api
try {
    & $VenvPy -m pip install --disable-pip-version-check -q --require-hashes -r requirements.lock
    if ($LASTEXITCODE -ne 0) { throw "Installing the API dependencies failed." }
    & $VenvPy -m pip install --disable-pip-version-check -q --no-deps -e .
    if ($LASTEXITCODE -ne 0) { throw "Installing the API failed." }
    & $VenvPy -m pip install --disable-pip-version-check -q "pytest>=8" "pytest-asyncio>=0.23" "playwright>=1.45"
    if ($LASTEXITCODE -ne 0) { throw "Installing the test tools failed." }
} finally { Pop-Location }

# 3. Dashboard
Push-Location $Web
try {
    npm ci --no-audit --no-fund
    if ($LASTEXITCODE -ne 0) { throw "Installing the dashboard failed." }
} finally { Pop-Location }

# 4. .env with a random STARK_API_TOKEN and the demo sandbox (never overwrites an existing .env)
& $VenvPy (Join-Path $Root "scripts\setup.py")
if ($LASTEXITCODE -ne 0) { throw "Creating .env failed." }

Write-Host ""
Write-Host "Setup complete. Start STARK AI with:  powershell -ExecutionPolicy Bypass -File scripts\dev.ps1"
Write-Host "Optional for browser.render:  services\api\.venv\Scripts\python.exe -m playwright install chromium"
