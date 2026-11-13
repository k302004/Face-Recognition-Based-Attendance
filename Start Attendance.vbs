' Start Attendance.vbs
Option Explicit

Dim shell, fileSystem, appDir, phpExe, command, http, serverReady, wmi, startup, processId, result
Set shell = CreateObject("WScript.Shell")
Set fileSystem = CreateObject("Scripting.FileSystemObject")
appDir = fileSystem.GetParentFolderName(WScript.ScriptFullName)
phpExe = shell.ExpandEnvironmentStrings("%USERPROFILE%") & "\.config\herd-lite\bin\php.exe"

If Not fileSystem.FileExists(phpExe) Then
    phpExe = shell.ExpandEnvironmentStrings("%LOCALAPPDATA%") & "\Microsoft\WinGet\Packages\PHP.PHP.8.4_Microsoft.Winget.Source_8wekyb3d8bbwe\php.exe"
End If

If Not fileSystem.FileExists(phpExe) Then
    MsgBox "PHP 8.4 or newer was not found. Install PHP 8.4+ or Herd Lite, then run this launcher again.", 16, "Attendance System"
    WScript.Quit 1
End If

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
    If result <> 0 Then WScript.Quit 1
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
    command = "python scripts\camera_stream.py"
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

' Start SMS gateway (send_to_pi.py) if not running
Dim smsReady
smsReady = False
On Error Resume Next
Set http = CreateObject("WinHttp.WinHttpRequest.5.1")
http.SetTimeouts 300, 300, 300, 300
http.Open "GET", "http://127.0.0.1:8092/health", False
http.Send
smsReady = (Err.Number = 0 And http.Status = 200)
Err.Clear
On Error GoTo 0

If Not smsReady Then
    command = "python scripts\send_to_pi.py --serve --http-port 8092 --serial-port COM3 --baud 115200"
    Set wmi = GetObject("winmgmts:\\.\root\cimv2")
    Set startup = wmi.Get("Win32_ProcessStartup").SpawnInstance_
    startup.ShowWindow = 0
    result = wmi.Get("Win32_Process").Create(command, appDir, startup, processId)
    If result <> 0 Then
        MsgBox "Failed to start SMS gateway. Make sure Python and dependencies are installed.", 16, "Attendance System"
    Else
        fileSystem.CreateTextFile(appDir & "\.sms-gateway.pid", True).WriteLine processId
    End If
    WScript.Sleep 2000
End If

shell.Run "http://127.0.0.1:8000/?v=" & Replace(CStr(Timer), ".", ""), 1, False
Set http = Nothing
Set startup = Nothing
Set wmi = Nothing
Set fileSystem = Nothing
Set shell = Nothing

