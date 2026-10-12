param([int]$Port = 8765)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot

if (-not (Test-Path -LiteralPath '.env')) {
    Copy-Item -LiteralPath '.env.example' -Destination '.env'
}
if (-not (Test-Path -LiteralPath '.venv/Scripts/python.exe')) {
    python -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Python venv creation failed. Python 3.11+ is required.' }
}
$studioPython = Join-Path $PSScriptRoot '.venv/Scripts/python.exe'
$studioMarker = Join-Path $PSScriptRoot '.venv/.studio-deps-ready'
if (-not (Test-Path -LiteralPath $studioMarker) -or
    (Get-Item -LiteralPath 'pyproject.toml').LastWriteTime -gt (Get-Item -LiteralPath $studioMarker -ErrorAction SilentlyContinue).LastWriteTime) {
    & $studioPython -m pip install -e .
    if ($LASTEXITCODE -ne 0) {
        Write-Host 'Configured package mirror failed; retrying with the official PyPI index.'
        & $studioPython -m pip install -e . --index-url https://pypi.org/simple
    }
    if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
    New-Item -ItemType File -Path $studioMarker -Force | Out-Null
}
Write-Host "H3 Video Studio: http://127.0.0.1:$Port"
& $studioPython -m uvicorn app.main:create_app --factory --host 127.0.0.1 --port $Port --workers 1
