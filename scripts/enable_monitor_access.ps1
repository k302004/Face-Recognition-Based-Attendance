param([switch]$Quiet)
# Run once as administrator to allow the second laptop on the same network.
$ErrorActionPreference = 'Stop'
try {
    $network = Get-NetIPConfiguration | Where-Object { $_.IPv4DefaultGateway -and $_.IPv4Address } | Select-Object -First 1
    if (-not $network) { throw 'Connect to Wi-Fi or Ethernet first.' }
    foreach ($port in @(8000, 8090)) {
        $name = 'Attendance-Monitor-LocalSubnet-' + $port
        if (Get-NetFirewallRule -Name $name -ErrorAction SilentlyContinue) {
            Set-NetFirewallRule -Name $name -Enabled True -InterfaceAlias $network.InterfaceAlias -RemoteAddress LocalSubnet -Action Allow
        } else {
            New-NetFirewallRule -Name $name -DisplayName "Attendance Monitor - local subnet TCP $port" -Direction Inbound -Action Allow -Protocol TCP -LocalPort $port -RemoteAddress LocalSubnet -Profile Any -InterfaceAlias $network.InterfaceAlias | Out-Null
        }
    }
    if ($Quiet) { exit 0 }
    $popup = New-Object -ComObject WScript.Shell
    $popup.Popup(('Monitor access enabled. Open http://' + $network.IPv4Address[0].IPAddress + ':8000/monitor on the second laptop.'), 0, 'Attendance Monitor', 64) | Out-Null
} catch {
    if ($Quiet) { exit 1 }
    $popup = New-Object -ComObject WScript.Shell
    $popup.Popup($_.Exception.Message, 0, 'Monitor access requires administrator permission', 16) | Out-Null
    exit 1
}
