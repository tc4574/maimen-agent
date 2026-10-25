param([switch]$Live, [switch]$Offline, [int]$Port = 8000)
$ErrorActionPreference = 'Stop'
Set-Location (Join-Path $PSScriptRoot '..')
$env:MAIMEN_ENABLE_LIVE_RECOMMENDATIONS = if ($Offline) { '0' } else { '1' }
& ./.venv/Scripts/python.exe -m uvicorn maimen.api:app --host 127.0.0.1 --port $Port
