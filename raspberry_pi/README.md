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

Set `api_url`, `device_token`, and `subject`. Keep `sms_enabled` false until attendance recording works.
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

Look for `Recorded ...` in the terminal, then refresh the dashboard Attendance view. Press `q` to stop the camera client.
For normal unattended operation, use `sudo systemctl start attendance-client` instead of running the Python command manually. Check it with `sudo systemctl status attendance-client` and view errors with `journalctl -u attendance-client -f`.

## 5. Enable SIM7600 SMS

Connect the modem by USB, insert a SIM, and find its serial device with `ls /dev/ttyUSB*`. Set `sms_enabled` and `sms_port` in `config.json`. The client sends to the `parent_phone` stored for the recognized student. The modem requires its own stable power supply; do not power it from a GPIO pin.

The client sends SMS to the `parent_phone` returned by the protected API for the recognized student.