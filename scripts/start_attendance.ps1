param([switch]$CheckOnly, [switch]$Stop, [switch]$NoBrowser, [switch]$MonitorOnly)
$ErrorActionPreference = 'Stop'
# Default website binding: all interfaces, for local-network sharing.
$projectDir = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectDir
$logDir = Join-Path $projectDir 'storage\logs'
New-Item -ItemType Directory -Path $logDir -Force | Out-Null
$launchMutex = $null
$lockHeld = $false

function Test-Endpoint([string]$Url) {
    try {
        $reply = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 2
        return $reply.StatusCode -eq 200
    } catch { return $false }
}

function Find-Python([string]$Imports) {
    $candidates = @(
        (Join-Path $projectDir '.venv\Scripts\python.exe'),
        (Join-Path $projectDir 'scripts\.venv\Scripts\python.exe')
    )
    foreach ($name in @('python', 'python3')) {
        $found = Get-Command $name -ErrorAction SilentlyContinue
        if ($found) { $candidates += $found.Source }
    }
    foreach ($candidate in ($candidates | Select-Object -Unique)) {
        if (-not (Test-Path -LiteralPath $candidate)) { continue }
        try {
            & $candidate -c $Imports 2>$null
            if ($LASTEXITCODE -eq 0) { return $candidate }
        } catch { }
    }
    throw "No Python installation has the required packages: $Imports. See README.md for installation."
}

function Start-ServiceProcess($Name, $Executable, $Arguments, $Url, $PidName) {
    if (Test-Endpoint $Url) {
        # Adopt the actual listening process so Stop also works after a restart
        # or when an earlier launch's Python wrapper has exited.
        $port = ([uri]$Url).Port
        $listener = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($listener) {
            $owner = Get-CimInstance Win32_Process -Filter "ProcessId=$($listener.OwningProcess)"
            if ($owner -and $owner.CommandLine -like "*$projectDir*" -and $owner.CommandLine -match 'camera_stream\.py|send_to_pi\.py|artisan|resources[/\\]server\.php') {
                Set-Content -LiteralPath (Join-Path $projectDir $PidName) -Value $owner.ProcessId
            }
        }
        Write-Output "$Name already running."
        return
    }
    $outLog = Join-Path $logDir "$Name.out.log"
    $errLog = Join-Path $logDir "$Name.error.log"
    $process = Start-Process -FilePath $Executable -ArgumentList $Arguments -WorkingDirectory $projectDir -WindowStyle Hidden -RedirectStandardOutput $outLog -RedirectStandardError $errLog -PassThru
    Set-Content -LiteralPath (Join-Path $projectDir $PidName) -Value $process.Id
    $deadline = [DateTime]::UtcNow.AddSeconds(30)
    do {
        if (Test-Endpoint $Url) { Write-Output "$Name ready."; return }
        $process.Refresh()
        if ($process.HasExited) { break }
        Start-Sleep -Milliseconds 300
    } while ([DateTime]::UtcNow -lt $deadline)
    throw "$Name did not become ready. Check $errLog and $outLog. For the camera, reconnect the external camera selected in public\camera.config."
}

try {
    if (-not $CheckOnly) {
        # Serialize Start/Stop, including rapid double-clicks on either VBS file.
        $hasher = [System.Security.Cryptography.SHA256]::Create()
        $hash = [BitConverter]::ToString($hasher.ComputeHash([Text.Encoding]::UTF8.GetBytes($projectDir.ToLowerInvariant()))).Replace('-', '')
        $hasher.Dispose()
        $launchMutex = New-Object System.Threading.Mutex($false, ('Local\AttendanceLauncher-' + $hash))
        try { $lockHeld = $launchMutex.WaitOne(0) }
        catch [System.Threading.AbandonedMutexException] { $lockHeld = $true }
        if (-not $lockHeld) { exit 0 }
    }
    if ($Stop) {
        foreach ($pidName in @('.camera-stream.pid', '.sms-gateway.pid', '.attendance-server.pid')) {
            $pidPath = Join-Path $projectDir $pidName
            if (-not (Test-Path -LiteralPath $pidPath)) { continue }
            $servicePid = (Get-Content -LiteralPath $pidPath -Raw).Trim()
            if ($servicePid -match '^\d+$') {
                $processInfo = Get-CimInstance Win32_Process -Filter "ProcessId = $servicePid"
                if ($processInfo -and $processInfo.CommandLine -like "*$projectDir*" -and $processInfo.CommandLine -match 'camera_stream\.py|send_to_pi\.py|artisan|resources[/\\]server\.php') {
                    Start-Process -FilePath 'taskkill.exe' -ArgumentList @('/PID', $servicePid, '/T', '/F') -WindowStyle Hidden -Wait
                }
            }
            Remove-Item -LiteralPath $pidPath
        }
        exit 0
    }
    $network = Get-NetIPConfiguration | Where-Object { $_.IPv4DefaultGateway -and $_.IPv4Address } | Select-Object -First 1
    $monitorHost = if ($network) { [string]$network.IPv4Address[0].IPAddress } else { '127.0.0.1' }
    $monitorUrl = 'http://' + $monitorHost + ':8000/monitor'
    if ($MonitorOnly) { Start-Process $monitorUrl; exit 0 }
    if (-not (Test-Path -LiteralPath (Join-Path $projectDir 'vendor\autoload.php'))) { throw 'PHP dependencies are missing. Run composer install first.' }
    if (-not (Test-Path -LiteralPath (Join-Path $projectDir '.env'))) { throw 'The .env file is missing. Complete the README setup first.' }
    $phpCommand = Get-Command php -ErrorAction SilentlyContinue
    if ($phpCommand) { $phpExe = $phpCommand.Source }
    else {
        $phpExe = Join-Path $env:USERPROFILE '.config\herd-lite\bin\php.exe'
        if (-not (Test-Path -LiteralPath $phpExe)) { throw 'PHP was not found. Install PHP 8.4+ and add it to PATH.' }
    }
    $cameraPython = Find-Python 'import cv2, face_recognition, numpy'
    $smsPython = Find-Python 'import serial'
    if ($CheckOnly) {
        Write-Output "PHP: $phpExe"
        Write-Output "Camera Python: $cameraPython"
        Write-Output "SMS Python: $smsPython"
        Write-Output 'Camera selection: public\camera.config. SMS port: send_to_pi.py default (currently COM4).'
        exit 0
    }
    if (-not $NoBrowser) {
        $needsNetworkSetup = $false
        foreach ($port in @(8000, 8090)) {
            $rule = Get-NetFirewallRule -Name ('Attendance-Monitor-LocalSubnet-' + $port) -ErrorAction SilentlyContinue
            if (-not $rule -or [string]$rule.Enabled -ne 'True') { $needsNetworkSetup = $true }
        }
        if ($needsNetworkSetup) {
            # Windows requires an administrator prompt only for first-time LAN access.
            $setup = Start-Process powershell.exe -ArgumentList ('-NoLogo -NoProfile -ExecutionPolicy Bypass -File "' + (Join-Path $PSScriptRoot 'enable_monitor_access.ps1') + '" -Quiet') -Verb RunAs -WindowStyle Hidden -Wait -PassThru
            if ($setup.ExitCode -ne 0) { throw 'Network setup was not completed. Run Enable Monitor Access.vbs and approve the administrator prompt.' }
        }
    }
    # No camera index override: camera_stream.py reads public/camera.config.
    Start-ServiceProcess 'attendance-web' $phpExe ('"' + (Join-Path $projectDir 'artisan') + '" serve --host=0.0.0.0 --port=8000 --no-reload') 'http://127.0.0.1:8000/api/monitor/active' '.attendance-server.pid'
    Start-ServiceProcess 'attendance-sms' $smsPython ('-u "' + (Join-Path $projectDir 'scripts\send_to_pi.py') + '" --serve --http-port 8092 --serial-port COM4 --baud 115200') 'http://127.0.0.1:8092/health' '.sms-gateway.pid'
    Start-ServiceProcess 'attendance-camera' $cameraPython ('-u "' + (Join-Path $projectDir 'scripts\camera_stream.py') + '"') 'http://127.0.0.1:8090/snapshot' '.camera-stream.pid'
    # A healthy localhost-only server cannot serve the second laptop.
    $listeners = @(Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue)
    if (-not ($listeners | Where-Object { $_.LocalAddress -in @('0.0.0.0', '::') })) {
        throw 'The website is bound to localhost only. Run Stop Attendance.vbs, then Start All.vbs to enable network sharing.'
    }
    Set-Content -LiteralPath (Join-Path $projectDir 'Monitor Link.txt') -Value @(
        'Open this address on the second laptop connected to the same network:', $monitorUrl,
        '', 'On the main PC, click Start Operation Mode to activate the monitor.',
        'Camera: public/camera.config. SMS/LCD bridge: COM4.',
        'The Raspberry Pi must be powered on; its sms_listener.service starts on boot.'
    )
    Write-Output "Ready. Monitor: $monitorUrl"
    if (-not $NoBrowser) { Start-Process 'http://127.0.0.1:8000/' }
} catch {
    $message = $_.Exception.Message
    Add-Content -LiteralPath (Join-Path $logDir 'attendance-launcher.log') -Value ("$(Get-Date -Format o) $message")
    if ($CheckOnly -or $NoBrowser) { Write-Error $message; exit 1 }
    $popup = New-Object -ComObject WScript.Shell
    $popup.Popup($message, 0, 'Attendance startup', 16) | Out-Null
    exit 1
} finally {
    if ($lockHeld) { $launchMutex.ReleaseMutex() }
    if ($null -ne $launchMutex) { $launchMutex.Dispose() }
}
