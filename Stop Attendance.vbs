' Stop Attendance.vbs
Option Explicit

Dim shell, fileSystem, appDir, pidFile, pid, file
Set shell = CreateObject("WScript.Shell")
Set fileSystem = CreateObject("Scripting.FileSystemObject")
appDir = fileSystem.GetParentFolderName(WScript.ScriptFullName)
pidFile = appDir & "\.attendance-server.pid"

If fileSystem.FileExists(pidFile) Then
	Set file = fileSystem.OpenTextFile(pidFile, 1)
	pid = Trim(file.ReadLine)
	file.Close
	If IsNumeric(pid) Then shell.Run "taskkill /PID " & CLng(pid) & " /T /F", 0, True
	fileSystem.DeleteFile pidFile, True
End If

Set file = Nothing
Set fileSystem = Nothing
Set shell = Nothing
