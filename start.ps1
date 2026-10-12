param([ValidateRange(1, 65535)][int]$Port = 8765)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot

function Get-StudioListeners {
    param([int]$Port)
    Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
        Select-Object -ExpandProperty OwningProcess -Unique
}

function Test-StudioProcess {
    param($ServiceProcess, [int]$Port, [string]$PythonPath)
    $command = $ServiceProcess.CommandLine
    if (-not $command -or
        $command -notmatch '(?:^|\s)-m\s+uvicorn(?=\s|$)' -or
        $command -notmatch '(?:^|\s)"?app\.main:create_app"?(?=\s|$)' -or
        $command -notmatch "(?:^|\s)--port(?:\s+|=)`"?$Port`"?(?=\s|$)") {
        return $false
    }
    if ($command -match '(?:^|\s)"?--app-dir"?(?:\s|=|$)') {
        $projectRoot = [IO.Path]::GetFullPath((Join-Path ([IO.Path]::GetDirectoryName($PythonPath)) '../..')).TrimEnd('\')
        $appDirectories = [regex]::Matches($command, '(?:^|\s)"?--app-dir"?(?:\s+|=)(?:"([^"]+)"|(\S+))')
        if (-not $appDirectories.Count) { return $false }
        foreach ($match in $appDirectories) {
            $directory = if ($match.Groups[1].Success) { $match.Groups[1].Value } else { $match.Groups[2].Value }
            # A relative directory cannot establish the running process's working directory.
            if ($directory -notmatch '^(?:[A-Za-z]:[\\/]|\\\\)' -or
                [IO.Path]::GetFullPath($directory).TrimEnd('\') -ne $projectRoot) {
                return $false
            }
        }
    }
    # On Windows the venv launcher often owns a child running the base Python.
    $current = $ServiceProcess
    $visited = @{}
    for ($depth = 0; $current -and $depth -lt 8; $depth++) {
        if ($visited.ContainsKey([int]$current.ProcessId)) { break }
        $visited[[int]$current.ProcessId] = $true
        if ($current.ExecutablePath -and
            [IO.Path]::GetFullPath($current.ExecutablePath) -eq [IO.Path]::GetFullPath($PythonPath)) {
            return $true
        }
        if (-not $current.ParentProcessId) { break }
        $parent = Get-CimInstance Win32_Process -Filter "ProcessId=$($current.ParentProcessId)" -ErrorAction Stop
        if (-not $parent -or $parent.CreationDate -gt $current.CreationDate) { break }
        $current = $parent
    }
    return $false
}

function Stop-ExistingStudio {
    param([int]$Port, [string]$PythonPath, [int]$TimeoutSeconds = 10)
    $owners = @(Get-StudioListeners -Port $Port)
    if (-not $owners.Count) { return }
    $services = @()
    foreach ($ownerId in $owners) {
        $service = Get-CimInstance Win32_Process -Filter "ProcessId=$ownerId" -ErrorAction Stop
        if (-not $service -or -not (Test-StudioProcess -ServiceProcess $service -Port $Port -PythonPath $PythonPath)) {
            throw "Port $Port is occupied by another process (PID $ownerId). It will not be stopped."
        }
        $services += $service
    }
    foreach ($service in $services) {
        # Recheck identity immediately before stopping, in case a PID was reused.
        $current = Get-CimInstance Win32_Process -Filter "ProcessId=$($service.ProcessId)" -ErrorAction Stop
        if (-not $current) { continue }
        if ($current.CreationDate -ne $service.CreationDate -or
            -not (Test-StudioProcess -ServiceProcess $current -Port $Port -PythonPath $PythonPath)) {
            throw "Process identity changed for PID $($service.ProcessId); restart aborted."
        }
        Write-Host "H3 Video Studio is already running on port $Port (PID $($service.ProcessId)); restarting."
        Stop-Process -Id $service.ProcessId -ErrorAction Stop
    }
    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    while (@(Get-StudioListeners -Port $Port).Count) {
        if ([DateTime]::UtcNow -ge $deadline) {
            throw "Port $Port was not released within $TimeoutSeconds seconds; restart aborted."
        }
        Start-Sleep -Milliseconds 200
    }
}

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
Stop-ExistingStudio -Port $Port -PythonPath $studioPython
Write-Host "H3 Video Studio: http://127.0.0.1:$Port"
& $studioPython -m uvicorn app.main:create_app --factory --host 127.0.0.1 --port $Port --workers 1
if ($LASTEXITCODE -ne 0) { throw "H3 Video Studio exited with code $LASTEXITCODE." }
