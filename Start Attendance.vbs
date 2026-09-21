' Start Attendance.vbs
Option Explicit

Dim shell, fileSystem, appDir, phpExe, command, http, serverReady, wmi, startup, processId, result
Set shell = CreateObject("WScript.Shell")
Set fileSystem = CreateObject("Scripting.FileSystemObject")
appDir = fileSystem.GetParentFolderName(WScript.ScriptFullName)
phpExe = appDir & "\php\php.exe"

If Not fileSystem.FileExists(phpExe) Then
    phpExe = FindPhpOnPath(fileSystem, shell)
End If

If phpExe = "" Then
    MsgBox "PHP runtime was not found. Please ensure the php folder is beside this launcher.", 16, "Attendance System"
    WScript.Quit 1
End If

serverReady = False
On Error Resume Next
Set http = CreateObject("WinHttp.WinHttpRequest.5.1")
http.SetTimeouts 300, 300, 300, 300
http.Open "GET", "http://127.0.0.1:8080/index.html", False
http.Send
serverReady = (Err.Number = 0 And http.Status = 200)
Err.Clear
If serverReady Then
    http.Open "GET", "http://127.0.0.1:8080/api.php?action=device-attendance", False
    http.Send
    serverReady = (Err.Number = 0 And http.Status <> 404)
End If
Err.Clear
On Error GoTo 0

If Not serverReady Then
    command = """" & phpExe & """ -S 0.0.0.0:8080 -t """ & appDir & """"
    Set wmi = GetObject("winmgmts:\\.\root\cimv2")
    Set startup = wmi.Get("Win32_ProcessStartup").SpawnInstance_
    startup.ShowWindow = 0
    result = wmi.Get("Win32_Process").Create(command, appDir, startup, processId)
    If result <> 0 Then WScript.Quit 1
    fileSystem.CreateTextFile(appDir & "\.attendance-server.pid", True).WriteLine processId
    WScript.Sleep 1500
End If

shell.Run "http://127.0.0.1:8080/index.html?v=" & Replace(CStr(Timer), ".", ""), 1, False
Set http = Nothing
Set startup = Nothing
Set wmi = Nothing
Set fileSystem = Nothing
Set shell = Nothing

Function FindPhpOnPath(fileSystem, shell)
    Dim pathValue, folder, candidate
    pathValue = shell.Environment("Process")("PATH")
    For Each folder In Split(pathValue, ";")
        folder = Trim(folder)
        If folder <> "" Then
            candidate = folder & "\php.exe"
            If fileSystem.FileExists(candidate) Then
                FindPhpOnPath = candidate
                Exit Function
            End If
        End If
    Next
    FindPhpOnPath = ""
End Function
