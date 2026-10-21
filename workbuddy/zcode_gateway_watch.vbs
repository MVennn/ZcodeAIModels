' Start zcode_gateway_watch.ps1 without a console window.
' Registered in the Startup folder by: powershell -File zcode_gateway_watch.ps1 -Install
Option Explicit

Dim fso, shell, baseDir, scriptPath, command
Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")

baseDir = fso.GetParentFolderName(WScript.ScriptFullName)
scriptPath = fso.BuildPath(baseDir, "zcode_gateway_watch.ps1")

If Not fso.FileExists(scriptPath) Then
    WScript.Quit 1
End If

command = "powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File """ & scriptPath & """"
shell.Run command, 0, False
