Set fso = CreateObject("Scripting.FileSystemObject")
Set ws = CreateObject("WScript.Shell")
scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
ws.Run "powershell.exe -NoProfile -ExecutionPolicy Bypass -File """ & scriptDir & "\start_langbot.ps1""", 0, False
