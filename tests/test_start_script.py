"""Exercise the startup script's process selection with controlled Windows process data."""
import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PWSH = shutil.which('pwsh')
pytestmark = pytest.mark.skipif(sys.platform != 'win32' or not PWSH, reason='Windows PowerShell startup script')
PYTHON_PATH = str(ROOT / '.venv' / 'Scripts' / 'python.exe')
COMMAND = 'python -m uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8765 --workers 1'


def process(pid, parent, executable, command=COMMAND):
    return {'ProcessId': pid, 'ParentProcessId': parent, 'ExecutablePath': executable,
            'CommandLine': command, 'CreationDate': '2026-10-12T00:00:00'}


def run_restart(tmp_path, processes, listeners, *, reuse=False, sticky=False):
    data = {'processes': processes, 'listeners': listeners, 'reuse': reuse, 'sticky': sticky}
    fixture = tmp_path / 'processes.json'
    fixture.write_text(json.dumps(data), encoding='utf-8')
    harness = tmp_path / 'harness.ps1'
    harness.write_text(r'''
param($StartScript, $Fixture, $PythonPath)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$script:data = Get-Content -LiteralPath $Fixture -Raw | ConvertFrom-Json
$script:stopped = @()
$script:calls = @{}
function Get-NetTCPConnection {
    param($LocalPort, $State, $ErrorAction)
    @($script:data.listeners | Where-Object { $_.LocalPort -eq $LocalPort })
}
function Get-CimInstance {
    param($ClassName, $Filter, $ErrorAction)
    if ($Filter -notmatch 'ProcessId=(\d+)') { throw 'Unexpected process query' }
    $requested = [int]$Matches[1]
    $script:calls[$requested] = 1 + $script:calls[$requested]
    $result = $script:data.processes | Where-Object { $_.ProcessId -eq $requested } | Select-Object -First 1 | Select-Object *
    if ($script:data.reuse -and $requested -eq 101 -and $script:calls[$requested] -ge 2) {
        $result.CreationDate = '2026-10-12T00:01:00'
    }
    $result
}
function Stop-Process {
    param($Id, $ErrorAction)
    $script:stopped += [int]$Id
    if (-not $script:data.sticky) {
        $script:data.listeners = @($script:data.listeners | Where-Object { $_.OwningProcess -ne $Id })
    }
}
$parseErrors = $null
$tokens = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile($StartScript, [ref]$tokens, [ref]$parseErrors)
if ($parseErrors.Count) { throw 'Startup script does not parse' }
$functions = $ast.FindAll({param($node) $node -is [System.Management.Automation.Language.FunctionDefinitionAst]}, $false)
foreach ($item in $functions) { Invoke-Expression $item.Extent.Text }
$failure = ''
try { Stop-ExistingStudio -Port 8765 -PythonPath $PythonPath -TimeoutSeconds 1 }
catch { $failure = $_.Exception.Message }
@{stopped=@($script:stopped);failure=$failure;remaining=@($script:data.listeners)} | ConvertTo-Json -Depth 5 -Compress
''', encoding='utf-8')
    result = subprocess.run([PWSH, '-NoProfile', '-File', str(harness), str(ROOT / 'start.ps1'),
                             str(fixture), PYTHON_PATH], capture_output=True, text=True, encoding='utf-8', timeout=15)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout.strip().splitlines()[-1])


def listener(pid=101, port=8765):
    return {'OwningProcess': pid, 'LocalPort': port}


def test_startup_restarts_current_project_venv_child_once(tmp_path):
    result = run_restart(tmp_path, [process(101, 102, 'C:/Python/python.exe'),
                                  process(102, 999, PYTHON_PATH)], [listener(), listener()])
    assert result['failure'] == ''
    assert result['stopped'] == [101]
    assert result['remaining'] == []


def test_empty_port_does_not_stop_any_process(tmp_path):
    result = run_restart(tmp_path, [], [])
    assert result['stopped'] == [] and result['failure'] == ''


def test_direct_project_interpreter_and_equals_port_are_supported(tmp_path):
    service = process(101, 0, PYTHON_PATH, COMMAND.replace('--port 8765', '--port=8765'))
    result = run_restart(tmp_path, [service], [listener()])
    assert result['stopped'] == [101] and result['failure'] == ''


def test_reused_parent_cannot_prove_project_identity(tmp_path):
    parent = process(102, 0, PYTHON_PATH)
    parent['CreationDate'] = '2026-10-12T00:01:00'
    result = run_restart(tmp_path, [process(101, 102, 'C:/Python/python.exe'), parent], [listener()])
    assert result['stopped'] == [] and result['failure']


@pytest.mark.parametrize('processes', [
    [process(101, 0, 'C:/Python/python.exe', 'python -m http.server 8765')],
    [process(101, 102, 'C:/Python/python.exe'), process(102, 0, 'D:/other/.venv/Scripts/python.exe')],
    [process(101, 0, PYTHON_PATH, COMMAND.replace('--port 8765', '--port 87650'))],
    [process(101, 0, PYTHON_PATH, COMMAND.replace('app.main:create_app', 'other.main:create_app'))],
    [process(101, 0, PYTHON_PATH, COMMAND + ' --app-dir D:/other-project')],
    [process(101, 0, PYTHON_PATH, COMMAND + ' --app-dir="D:/other project"')],
    [process(101, 0, PYTHON_PATH, COMMAND + ' "--app-dir" D:/other-project')],
    [process(101, 0, PYTHON_PATH, COMMAND + f' --app-dir "{ROOT}" "--app-dir" D:/other-project')],
])
def test_unrelated_port_owner_is_not_stopped(tmp_path, processes):
    result = run_restart(tmp_path, processes, [listener()])
    assert result['stopped'] == [] and result['failure']


def test_all_port_owners_are_validated_before_stopping_any(tmp_path):
    result = run_restart(tmp_path, [process(101, 0, PYTHON_PATH),
                                  process(201, 0, 'C:/Other/app.exe', 'unrelated server')],
                         [listener(), listener(201)])
    assert result['stopped'] == [] and result['failure']


def test_explicit_current_project_app_directory_is_supported(tmp_path):
    service = process(101, 0, PYTHON_PATH, COMMAND + f' --app-dir "{ROOT}"')
    result = run_restart(tmp_path, [service], [listener()])
    assert result['stopped'] == [101] and result['failure'] == ''


def test_pid_reuse_does_not_stop_replacement_process(tmp_path):
    result = run_restart(tmp_path, [process(101, 0, PYTHON_PATH)], [listener()], reuse=True)
    assert result['stopped'] == [] and result['failure']


def test_port_release_timeout_aborts_restart(tmp_path):
    result = run_restart(tmp_path, [process(101, 0, PYTHON_PATH)], [listener()], sticky=True)
    assert result['stopped'] == [101] and result['failure']
    assert result['remaining']


def test_real_script_restarts_its_windows_venv_service(tmp_path):
    # Only an isolated ephemeral port/data directory is used, with both paid keys disabled.
    with socket.socket() as reservation:
        reservation.bind(('127.0.0.1', 0))
        port = reservation.getsockname()[1]
    env = {**os.environ, 'VIDEO_DATA_DIR': str(tmp_path / 'data'), 'RUNNINGHUB_API_KEY': '',
           'LLM_API_KEY': '', 'LLM_MODEL': ''}
    starters = []
    logs = []

    def owner():
        result = subprocess.run([PWSH, '-NoProfile', '-Command',
            f'Get-NetTCPConnection -LocalPort {port} -State Listen -ErrorAction SilentlyContinue | '
            'Select-Object -ExpandProperty OwningProcess -Unique'], capture_output=True, text=True,
            encoding='utf-8', timeout=10)
        return result.stdout.strip()

    def wait_ready(previous=''):
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            try:
                with urllib.request.urlopen(f'http://127.0.0.1:{port}/api/creation/config', timeout=1) as response:
                    config = json.load(response)
                current = owner()
                if current and current != previous:
                    assert config['configured'] is False
                    return current
            except (OSError, urllib.error.URLError):
                pass
            time.sleep(0.2)
        pytest.fail('Isolated startup did not become ready: ' + '\n'.join(
            path.read_text(encoding='utf-8', errors='replace') for path in logs))

    def launch():
        path = tmp_path / f'start-{len(starters)}.log'
        logs.append(path)
        with path.open('wb') as output:
            starters.append(subprocess.Popen([PWSH, '-NoProfile', '-File', str(ROOT / 'start.ps1'),
                '-Port', str(port)], cwd=ROOT, env=env, stdout=output, stderr=subprocess.STDOUT))

    try:
        launch()
        previous = wait_ready()
        launch()
        current = wait_ready(previous)
        assert current != previous
        starters[0].wait(timeout=10)
        assert 'restarting' in logs[1].read_text(encoding='utf-8', errors='replace')
        assert starters[1].poll() is None
    finally:
        # Use the same ownership checks to clean up only the service launched by this test.
        cleanup = tmp_path / 'cleanup.ps1'
        cleanup.write_text(r'''
param($StartScript, $Port, $PythonPath)
$ErrorActionPreference = 'Stop'
$tokens = $null; $parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile($StartScript, [ref]$tokens, [ref]$parseErrors)
$functions = $ast.FindAll({param($node) $node -is [System.Management.Automation.Language.FunctionDefinitionAst]}, $false)
foreach ($item in $functions) { Invoke-Expression $item.Extent.Text }
Stop-ExistingStudio -Port $Port -PythonPath $PythonPath
''', encoding='utf-8')
        cleaned = subprocess.run([PWSH, '-NoProfile', '-File', str(cleanup), str(ROOT / 'start.ps1'),
                                  str(port), PYTHON_PATH], capture_output=True, text=True,
                                  encoding='utf-8', timeout=15)
        for starter in starters:
            try:
                starter.wait(timeout=10)
            except subprocess.TimeoutExpired:
                starter.terminate()
                starter.wait(timeout=5)
        assert cleaned.returncode == 0, cleaned.stderr
