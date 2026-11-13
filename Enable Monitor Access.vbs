Option Explicit
Dim fs, appDir, helper, shellApp
Set fs = CreateObject("Scripting.FileSystemObject")
appDir = fs.GetParentFolderName(WScript.ScriptFullName)
helper = appDir & "\scripts\enable_monitor_access.ps1"
Set shellApp = CreateObject("Shell.Application")
shellApp.ShellExecute "powershell.exe", "-NoLogo -NoProfile -ExecutionPolicy Bypass -File """ & helper & """", appDir, "runas", 0
