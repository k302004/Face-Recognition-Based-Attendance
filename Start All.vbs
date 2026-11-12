' Start All.vbs - Starts PHP server + Python camera stream
Option Explicit

Dim shell, fileSystem, appDir, phpExe, pythonExe, command, wmi, startup, processId, result
Set shell = CreateObject("WScript.Shell")
Set fileSystem = CreateObject("Scripting.FileSystemObject")
appDir = fileSystem.GetParentFolderName(WScript.ScriptFullName)

' Find PHP
phpExe = shell.ExpandEnvironmentStrings("%USERPROFILE%") & "\.config\herd-lite\bin\php.exe"
If Not fileSystem.FileExists(phpExe) Then
    phpExe = shell.ExpandEnvironmentStrings("%LOCALAPPDATA%") & "\Microsoft\WinGet\Packages\PHP.PHP.8.4_Microsoft.Winget.Source_8wekyb3d8bbwe\php.exe"
End If

' Find Python
pythonExe = "python"
Dim pythonCheck
On Error Resume Next
pythonCheck = shell.Exec("python --version").StdOut.ReadAll()
On Error GoTo 0
If InStr(pythonCheck, "Python") = 0 Then
    pythonExe = "python3"
End If

' Start PHP server if not running
Dim http, serverReady
serverReady = False
On Error Resume Next
Set http = CreateObject("WinHttp.WinHttpRequest.5.1")
http.SetTimeouts 300, 300, 300, 300
http.Open "GET", "http://127.0.0.1:8000/", False
http.Send
serverReady = (Err.Number = 0 And http.Status = 200)
Err.Clear
On Error GoTo 0

If Not serverReady Then
    command = """" & phpExe & """ artisan serve --host=127.0.0.1 --port=8000"
    Set wmi = GetObject("winmgmts:\\.\root\cimv2")
    Set startup = wmi.Get("Win32_ProcessStartup").SpawnInstance_
    startup.ShowWindow = 0
    result = wmi.Get("Win32_Process").Create(command, appDir, startup, processId)
    If result <> 0 Then
        MsgBox "Failed to start PHP server.", 16, "Attendance System"
        WScript.Quit 1
    End If
    fileSystem.CreateTextFile(appDir & "\.attendance-server.pid", True).WriteLine processId
    WScript.Sleep 1500
End If

' Start camera stream if not running
Dim streamReady
streamReady = False
On Error Resume Next
Set http = CreateObject("WinHttp.WinHttpRequest.5.1")
http.SetTimeouts 300, 300, 300, 300
http.Open "GET", "http://127.0.0.1:8090/face_pose", False
http.Send
streamReady = (Err.Number = 0 And http.Status = 200)
Err.Clear
On Error GoTo 0

If Not streamReady Then
    command = pythonExe & " scripts\camera_stream.py"
    Set wmi = GetObject("winmgmts:\\.\root\cimv2")
    Set startup = wmi.Get("Win32_ProcessStartup").SpawnInstance_
    startup.ShowWindow = 0
    result = wmi.Get("Win32_Process").Create(command, appDir, startup, processId)
    If result <> 0 Then
        MsgBox "Failed to start camera stream. Make sure Python and dependencies are installed.", 16, "Attendance System"
    Else
        fileSystem.CreateTextFile(appDir & "\.camera-stream.pid", True).WriteLine processId
    End If
    WScript.Sleep 3000
End If

shell.Run "http://127.0.0.1:8000/?v=" & Replace(CStr(Timer), ".", ""), 1, False
Set http = Nothing
Set startup = Nothing
Set wmi = Nothing
Set fileSystem = Nothing
Set shell = Nothing