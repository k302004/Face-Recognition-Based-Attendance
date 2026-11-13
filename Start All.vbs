' Website listens on 0.0.0.0:8000 for local-network sharing.
' Starts all attendance services without opening terminal windows.
Option Explicit
Dim shell, fs, appDir, helper, command
Set shell = CreateObject("WScript.Shell")
Set fs = CreateObject("Scripting.FileSystemObject")
appDir = fs.GetParentFolderName(WScript.ScriptFullName)
helper = appDir & "\scripts\start_attendance.ps1"
If Not fs.FileExists(helper) Then
    MsgBox "Missing launcher helper: " & helper, 16, "Attendance startup"
    WScript.Quit 1
End If
command = "powershell.exe -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File """ & helper & """"
If WScript.Arguments.Count > 0 Then
    If WScript.Arguments(0) = "--check" Then
        WScript.Echo "Launcher syntax OK"
        WScript.Quit 0
    End If
End If
WScript.Quit shell.Run(command, 0, True)