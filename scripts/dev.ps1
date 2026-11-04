$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root '.venv/Scripts/python.exe'
$vite = Join-Path $root 'frontend/node_modules/vite/bin/vite.js'
if (!(Test-Path -LiteralPath $python) -or !(Test-Path -LiteralPath $vite)) {
    throw 'Install backend and frontend dependencies first. See docs/development.md.'
}
$node = (Get-Command node -ErrorAction Stop).Source
foreach ($port in @(8000, 5173)) {
    if (Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue) {
        throw "Port $port is occupied. Stop the existing service before running this script."
    }
}
$logs = Join-Path $root '.work/dev-logs'
New-Item -ItemType Directory -Path $logs -Force | Out-Null
$backend = $null
$frontend = $null
try {
    $backend = Start-Process -FilePath $python -ArgumentList '-m uvicorn app.main:app --host 127.0.0.1 --port 8000' -WorkingDirectory $root -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $logs 'backend.out.log') -RedirectStandardError (Join-Path $logs 'backend.err.log')
    $frontend = Start-Process -FilePath $node -ArgumentList @('"' + $vite + '"', '--host', '127.0.0.1') -WorkingDirectory (Join-Path $root 'frontend') -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $logs 'frontend.out.log') -RedirectStandardError (Join-Path $logs 'frontend.err.log')
    Write-Host 'Frontend: http://127.0.0.1:5173'
    Write-Host 'API docs: http://127.0.0.1:8000/docs'
    Write-Host 'Press Ctrl+C to stop both services. Logs: .work/dev-logs'
    while (!$backend.HasExited -and !$frontend.HasExited) {
        Start-Sleep -Seconds 1
        $backend.Refresh()
        $frontend.Refresh()
    }
    throw 'A development service exited. Inspect .work/dev-logs.'
}
finally {
    foreach ($child in @($backend, $frontend)) {
        if ($null -ne $child -and !$child.HasExited) {
            Stop-Process -Id $child.Id -ErrorAction SilentlyContinue
        }
    }
}
