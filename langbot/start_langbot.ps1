# SPDX-License-Identifier: MIT
$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path $PSScriptRoot -Parent
$LangBotExe = Join-Path $ProjectRoot 'langbot-venv\Scripts\langbot.exe'
$PidFile = Join-Path $PSScriptRoot 'langbot.pid'
if (-not (Test-Path -LiteralPath $LangBotExe)) { throw 'Run langbot/setup_langbot.bat first.' }
$MutexSuffix = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($ProjectRoot)).Replace('/','_').Replace('+','-')
$Mutex = New-Object System.Threading.Mutex($false, ('Local\QQBotPublic_' + $MutexSuffix))
$Locked = $false
try {
    try { $Locked = $Mutex.WaitOne(10000) } catch [System.Threading.AbandonedMutexException] { $Locked = $true }
    if (-not $Locked) { throw 'Another launcher is running.' }
    if (Test-Path -LiteralPath $PidFile) {
        $SavedPid = [int](Get-Content -LiteralPath $PidFile -Raw)
        $Existing = Get-CimInstance Win32_Process -Filter ('ProcessId = {0}' -f $SavedPid) -ErrorAction SilentlyContinue
        if ($Existing -and $Existing.ExecutablePath -ieq $LangBotExe) { Write-Output 'Already running.'; return }
    }
    if (Get-NetTCPConnection -LocalPort 5300 -State Listen -ErrorAction SilentlyContinue) { throw 'Port 5300 is occupied; no process was stopped.' }
    $env:PYTHONUTF8 = '1'
    $env:PYTHONIOENCODING = 'utf-8'
    $Started = Start-Process -FilePath $LangBotExe -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $PSScriptRoot 'langbot.out.log') -RedirectStandardError (Join-Path $PSScriptRoot 'langbot.err.log') -PassThru
    Set-Content -LiteralPath $PidFile -Value $Started.Id
    Write-Output 'LangBot started. Configure your own connection in its local panel.'
} finally {
    if ($Locked) { $Mutex.ReleaseMutex() }
    $Mutex.Dispose()
}
