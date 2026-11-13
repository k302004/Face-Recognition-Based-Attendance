# Raspberry Pi hardware setup

## Hardware

- Raspberry Pi 4 or 5 with Raspberry Pi OS 64-bit
- Raspberry Pi Camera Module or USB webcam
- Reliable 5V power supply
- Optional SIM7600 4G USB modem and active SIM for direct SMS
- Windows computer and Raspberry Pi on the same private LAN

## 1. Configure the Windows server

1. Copy `device_config.example.php` to `device_config.php` beside `api.php`.
2. Replace the example token with a long random value.
3. Start the app with `Start Attendance.vbs`.
4. Run `ipconfig` on Windows and note its IPv4 address.
5. Replace `192.168.1.25` in `config.json` with that address.
6. Allow inbound TCP port `8080` in Windows Firewall for the private network.
7. From the Pi, verify `http://WINDOWS_IP:8080/index.html` opens.

Do not expose port 8080 to the public internet. Use a VPN or HTTPS reverse proxy if the devices are not on the same trusted LAN.

## 2. Install the Pi client

Copy this `raspberry_pi` folder to the Pi, then run:

```bash
cd raspberry_pi
chmod +x setup.sh
./setup.sh
nano config.json
```

On Windows, run `ipconfig` and copy the IPv4 address from the active Wi-Fi or Ethernet adapter. On the Pi, set `api_url` to that address, for example `http://192.168.1.25:8080/api.php?action=device-attendance`; do not use the literal text `windows_ip`. Set `device_token` to exactly match the `token` returned by `device_config.php` on Windows. Keep `sms_enabled` false until attendance recording works.
The setup also installs the `attendance-client` service. After adding face images, start it with `sudo systemctl start attendance-client`. It will start automatically after future reboots and power outages.

## 3. Enroll faces

Create one clear, front-facing image for each student. The filename must be the exact student ID:

```text
known_faces/2026-001.jpg
known_faces/2026-002.jpg
```

The student must already exist in the dashboard with the same ID. Each image must contain exactly one face.

## 4. Test attendance

Run:

```bash
.venv/bin/python attendance_client.py
```

The client first prints `Attendance API connection authenticated`. If it cannot connect, verify the Windows IP and port; if it reports an invalid token, copy the token from `device_config.php` exactly into `config.json`. Look for `Recorded ...` in the terminal, then refresh the dashboard Attendance view. Press `q` to stop the camera client.
For normal unattended operation, use `sudo systemctl start attendance-client` instead of running the Python command manually. Check it with `sudo systemctl status attendance-client` and view errors with `journalctl -u attendance-client -f`.

## 5. Enable SIM7600 SMS

Connect the modem by USB, insert a SIM, and find its serial device with `ls /dev/ttyUSB*`. Set `sms_enabled` and `sms_port` in `config.json`. The client sends to the `parent_phone` stored for the recognized student. The modem requires its own stable power supply; do not power it from a GPIO pin.

The client sends SMS to the `parent_phone` returned by the protected API for the recognized student.

## Website attendance confirmations on the I2C LCD

For the Windows camera + serial SMS bridge setup, the Pi runs `sms_sender.py`.
After a new attendance record is saved, the website forwards the student's name
and `time_in` or `time_out` action through `scripts/send_to_pi.py` to this listener.
The 16x2 LCD flashes `IN: Recorded` or `OUT: Recorded`, scrolls long names, and
returns to `Attendance Ready`. Repeated scans that are already recorded do not
trigger another confirmation. The LCD confirmation is independent of SMS success.

Copy **both** updated files, `sms_sender.py` and `attendance_lcd.py`, into the
existing project `raspberry_pi` folder on the Pi. Preserve your existing
`config.json`, device token, and modem settings. With I2C enabled, add these
settings to that config if needed (the defaults are shown):

```json
"lcd_enabled": true,
"lcd_address": "0x27",
"lcd_i2c_bus": 1,
"lcd_hold_seconds": 2
```

Use your LCD backpack's actual I2C address if it differs from `0x27`.
From that folder, install the display dependencies and test without sending SMS:

```bash
.venv/bin/python -m pip install RPLCD smbus2
.venv/bin/python sms_sender.py --test-lcd time_in --name "Test Student"
.venv/bin/python sms_sender.py --test-lcd time_out --name "Test Student"
```

Stop the previous serial listener before running the updated one:

```bash
.venv/bin/python sms_sender.py --port /dev/ttyAMA1 --baud 115200
```

Keep the serial port previously used by your working PC-to-Pi connection if it
differs from `/dev/ttyAMA1`. Only one process should control the LCD and this serial
port; do not run `attendance_client.py` alongside this listener on the same LCD.
On Windows, restart the SMS bridge with **Stop Attendance.vbs**, then
**Start All.vbs**. A newly recorded Time In or Time Out should then show on the LCD.
The Windows launcher does not start programs on the Pi.
