$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
$backendDir = Join-Path $projectRoot 'backend'
$frontendDir = Join-Path $projectRoot 'frontend'
$pythonPath = Join-Path $backendDir '.venv-mt5/Scripts/python.exe'
$vitePath = Join-Path $frontendDir 'node_modules/vite/bin/vite.js'
$logDir = Join-Path $projectRoot 'logs'
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw 'Create backend/.venv-mt5 and install backend/requirements-mt5.txt first. See MT5_SETUP.md.'
}
if (-not (Test-Path -LiteralPath $vitePath)) {
    throw 'Run npm ci inside frontend first.'
}
if (-not (Get-NetTCPConnection -State Listen -LocalPort 8000 -ErrorAction SilentlyContinue)) {
    $apiProcess = Start-Process -FilePath $pythonPath -ArgumentList 'run_local.py' -WorkingDirectory $backendDir -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $logDir 'backend.out.log') -RedirectStandardError (Join-Path $logDir 'backend.err.log')
    Write-Host "Backend launched (PID $($apiProcess.Id))."
} else { Write-Host 'Port 8000 is already in use; backend launch skipped.' }
if (-not (Get-NetTCPConnection -State Listen -LocalPort 3000 -ErrorAction SilentlyContinue)) {
    $nodePath = (Get-Command node).Source
    $uiProcess = Start-Process -FilePath $nodePath -ArgumentList @("`"$vitePath`"", '--host', '127.0.0.1', '--port', '3000', '--strictPort') -WorkingDirectory $frontendDir -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $logDir 'frontend.out.log') -RedirectStandardError (Join-Path $logDir 'frontend.err.log')
    Write-Host "Dashboard launched (PID $($uiProcess.Id))."
} else { Write-Host 'Port 3000 is already in use; dashboard launch skipped.' }
Write-Host 'Dashboard: http://localhost:3000/backtest'
Write-Host 'API: http://127.0.0.1:8000/docs'
Write-Host 'Log into MT5 demo, connect, save a strategy, then Start demo. Launching does not place orders.'
