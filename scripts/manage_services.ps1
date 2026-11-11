# SPDX-License-Identifier: MIT
param(
    [ValidateSet('Start','Stop')][string]$Action = 'Start',
    [switch]$IncludePersonaSync
)
$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path $PSScriptRoot -Parent
$RunDir = Join-Path $ProjectRoot 'run'
$Modules = @(
    @{ Name='radar'; Script='radar.py'; Config='radar.json' },
    @{ Name='stargaze'; Script='stargaze.py'; Config='stargaze.json' },
    @{ Name='scheduler'; Script='scheduler.py'; Config='schedule.json' },
    @{ Name='wordlib'; Script='wordlib.py'; Config='wordlib.json' }
)
if ($IncludePersonaSync) { $Modules += @{ Name='personasync'; Script='persona-sync.py'; Config='persona-sync.json' } }
function Get-OwnedProcess($Record) {
    $Found = Get-CimInstance Win32_Process -Filter ('ProcessId = {0}' -f [int]$Record.pid) -ErrorAction SilentlyContinue
    if ($Found -and $Found.ExecutablePath -ieq $Record.executable -and $Found.CommandLine -and $Found.CommandLine.Contains('"' + $Record.script + '"')) { return $Found }
    return $null
}
if ($Action -eq 'Start') { New-Item -ItemType Directory -Path $RunDir -Force | Out-Null }
foreach ($Module in $Modules) {
    $ModuleDir = Join-Path $ProjectRoot $Module.Name
    $ScriptPath = Join-Path $ModuleDir $Module.Script
    $PythonPath = Join-Path $ModuleDir '.venv\Scripts\pythonw.exe'
    $RecordPath = Join-Path $RunDir ($Module.Name + '.json')
    $Owned = $null
    if (Test-Path -LiteralPath $RecordPath) {
        $Record = Get-Content -LiteralPath $RecordPath -Raw | ConvertFrom-Json
        if ($Record.script -ieq $ScriptPath -and $Record.executable -ieq $PythonPath) { $Owned = Get-OwnedProcess $Record }
    }
    if ($Action -eq 'Stop') {
        if ($Owned) { Stop-Process -Id $Owned.ProcessId; Write-Output ('Stopped: ' + $Module.Name) }
        else { Write-Output ('No verified managed process: ' + $Module.Name) }
        if (Test-Path -LiteralPath $RecordPath) { Remove-Item -LiteralPath $RecordPath }
        continue
    }
    if ($Owned) { Write-Output ('Already running: ' + $Module.Name); continue }
    if (-not (Test-Path -LiteralPath $PythonPath) -or -not (Test-Path -LiteralPath (Join-Path $ModuleDir $Module.Config))) {
        Write-Output ('Skipped (run module setup and configure first): ' + $Module.Name); continue
    }
    $Started = Start-Process -FilePath $PythonPath -ArgumentList ('"' + $ScriptPath + '"') -WorkingDirectory $ModuleDir -WindowStyle Hidden -PassThru
    @{ pid=$Started.Id; executable=$PythonPath; script=$ScriptPath } | ConvertTo-Json | Set-Content -LiteralPath $RecordPath -Encoding UTF8
    Write-Output ('Started: ' + $Module.Name)
}
