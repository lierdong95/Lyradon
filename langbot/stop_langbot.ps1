# SPDX-License-Identifier: MIT
$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path $PSScriptRoot -Parent
$ExpectedExe = Join-Path $ProjectRoot 'langbot-venv\Scripts\langbot.exe'
$PidFile = Join-Path $PSScriptRoot 'langbot.pid'
if (-not (Test-Path -LiteralPath $PidFile)) { Write-Output 'No managed LangBot PID.'; return }
$SavedPid = [int](Get-Content -LiteralPath $PidFile -Raw)
$Existing = Get-CimInstance Win32_Process -Filter ('ProcessId = {0}' -f $SavedPid) -ErrorAction SilentlyContinue
if ($Existing -and $Existing.ExecutablePath -ieq $ExpectedExe) { Stop-Process -Id $SavedPid; Write-Output 'Stopped managed LangBot.' }
elseif ($Existing) { throw 'PID does not belong to this installation; nothing was stopped.' }
Remove-Item -LiteralPath $PidFile
