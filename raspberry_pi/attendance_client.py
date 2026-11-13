import json
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

try:
    import cv2
except ImportError:
    print('OpenCV (cv2) is not installed. Install with: pip install opencv-python', file=sys.stderr)
    raise SystemExit(1)
try:
    import face_recognition
except ImportError:
    print('face_recognition is not installed. Install with: pip install face-recognition', file=sys.stderr)
    raise SystemExit(1)
try:
    import requests
except ImportError:
    print('requests is not installed. Install with: pip install requests', file=sys.stderr)
    raise SystemExit(1)
try:
    from RPLCD.i2c import CharLCD
except ImportError:
    CharLCD = None

try:
    from gsmmodem.pdu import encodeSmsSubmitPdu
except ImportError:
    encodeSmsSubmitPdu = None


ROOT = Path(__file__).resolve().parent


def load_config():
    config_path = ROOT / "config.json"
    if not config_path.is_file():
        print("Missing config.json. Copy config.example.json to config.json and edit it.", file=sys.stderr)
        raise SystemExit(1)
    with config_path.open(encoding="utf-8") as config_file:
        return json.load(config_file)


def check_api_connection(config):
    api_url = str(config.get("api_url", ""))
    host = urlparse(api_url).hostname
    if not host or host.lower() in {
        "windows_ip",
        "windows-ip",
        "your-windows-ip",
        "your_windows_ipv4",
        "your-windows-ipv4",
    }:
        raise RuntimeError(
            "The api_url still contains a placeholder Windows address. "
            "Replace windows_ip with the Windows computer's IPv4 address from ipconfig."
        )
    try:
        response = requests.get(
            api_url.split("?", 1)[0] + "?action=device-health",
            headers={"X-Device-Token": config["device_token"]},
            timeout=10,
        )
    except requests.RequestException as error:
        raise RuntimeError(
            f"Cannot reach attendance API at {api_url}. "
            "Check the Windows IP, port 8080, firewall, and LAN connection."
        ) from error
    if response.status_code == 401:
        raise RuntimeError(
            "Attendance API rejected the device token. Copy the token from "
            "device_config.php into raspberry_pi/config.json."
        )
    if not response.ok:
        raise RuntimeError(f"Attendance API health check failed ({response.status_code}): {response.text}")


def sync_known_faces(config, directory):
    api_url = config["api_url"].split("?", 1)[0] + "?action=device-faces"
    try:
        response = requests.get(api_url, headers={"X-Device-Token": config["device_token"]}, timeout=15)
        response.raise_for_status()
        faces = response.json().get("faces", [])
    except (requests.RequestException, ValueError) as error:
        raise RuntimeError(f"Could not download student photos from the website: {error}") from error
    directory.mkdir(parents=True, exist_ok=True)
    student_names = {}
    for face in faces:
        image_data = str(face.get("image", ""))
        if "," not in image_data or not face.get("studentId"):
            continue
        import base64
        image_bytes = base64.b64decode(image_data.split(",", 1)[1], validate=True)
        (directory / f"{face['studentId']}.jpg").write_bytes(image_bytes)
        student_names[str(face["studentId"])] = str(face.get("studentName", face["studentId"]))
    print(f"Downloaded {len(faces)} student face photo(s) from the website")
    return student_names


def initialize_lcd():
    if CharLCD is None:
        print("[LCD] RPLCD is not installed; continuing without LCD")
        return None
    try:
        lcd = CharLCD("PCF8574", 0x27, cols=16, rows=2)
        lcd.clear()
        lcd.write_string("Attendance Ready")
        lcd.cursor_pos = (1, 0)
        lcd.write_string("Scan your face")
        print("[LCD] Ready")
        return lcd
    except Exception as error:
        print(f"[LCD] Disabled: {error}")
        return None


def show_lcd_student(lcd, name):
    if lcd is None:
        return
    try:
        lcd.clear()
        lcd.write_string("Welcome")
        lcd.cursor_pos = (1, 0)
        lcd.write_string(str(name)[:16])
    except Exception as error:
        print(f"[LCD] Display update failed: {error}")


def load_known_faces(directory):
    encodings = []
    student_ids = []
    for image_path in sorted(Path(directory).glob("*")):
        if image_path.suffix.lower() not in {".jpg", ".jpeg", ".png"}:
            continue
        image = face_recognition.load_image_file(image_path)
        face_encodings = face_recognition.face_encodings(image)
        if len(face_encodings) != 1:
            print(f"Skipping {image_path.name}: expected exactly one face")
            continue
        encodings.append(face_encodings[0])
        student_ids.append(image_path.stem)
    if not encodings:
        raise RuntimeError("No usable face images found in known_faces")
    return encodings, student_ids


def send_sms(config, recipient, name, subject, checked_in_at):
    if not recipient:
        print("SMS skipped: this student has no parent phone number")
        return
    if encodeSmsSubmitPdu is None:
        print("gsmmodem not installed; skipping SMS")
        return
    message = config["sms_message"].format(name=name, subject=subject, time=checked_in_at)
    port = config.get("sms_port", "/dev/ttyAMA0")
    baud = config.get("sms_baud", 115200)
    try:
        import serial
        with serial.Serial(port, baud, timeout=5) as modem:
            modem.reset_input_buffer()
            # Wait for boot
            boot_buf = ""
            deadline = time.time() + 15
            while time.time() < deadline:
                if modem.in_waiting:
                    boot_buf += modem.read(modem.in_waiting).decode("utf-8", errors="ignore")
                    if "SMS DONE" in boot_buf or "PB DONE" in boot_buf or "READY" in boot_buf:
                        break
                time.sleep(0.2)
            # Wait for AT OK
            for _ in range(10):
                modem.reset_input_buffer()
                modem.write(b"AT\r")
                time.sleep(1)
                if "OK" in modem.read(modem.in_waiting or 0).decode("utf-8", errors="ignore"):
                    break
                time.sleep(1)
            # PDU mode
            modem.write(b"AT+CMGF=0\r")
            time.sleep(1)
            modem.read(modem.in_waiting or 0)

            pdus = encodeSmsSubmitPdu(recipient, message)
            for idx, pdu in enumerate(pdus, start=1):
                # gsmmodem returns Pdu objects whose raw octets live in
                # `.data`; older wrappers may expose them differently.
                if hasattr(pdu, "data") and isinstance(getattr(pdu, "data", None), (bytes, bytearray)):
                    pdu_hex = bytes(pdu.data).hex().upper()
                elif hasattr(pdu, "toHex"):
                    res = pdu.toHex()
                    pdu_hex = res.upper() if isinstance(res, str) else res.hex().upper()
                else:
                    pdu_hex = str(pdu).upper()
                tpdu_length = pdu.tpduLength
                for attempt in range(1, 4):
                    modem.reset_input_buffer()
                    modem.write(("AT+CMGS=%d\r" % tpdu_length).encode())
                    deadline = time.time() + 5
                    prompt_buf = ""
                    while time.time() < deadline:
                        if modem.in_waiting:
                            prompt_buf += modem.read(modem.in_waiting).decode("utf-8", errors="ignore")
                            if ">" in prompt_buf:
                                break
                        time.sleep(0.1)
                    if ">" not in prompt_buf:
                        time.sleep(1)
                        continue
                    modem.write((pdu_hex + "\x1a").encode())
                    final_resp = ""
                    deadline = time.time() + 15
                    while time.time() < deadline:
                        if modem.in_waiting:
                            final_resp += modem.read(modem.in_waiting).decode("utf-8", errors="ignore")
                            if "OK" in final_resp or "ERROR" in final_resp or "+CMGS" in final_resp or "+CMS ERROR" in final_resp:
                                break
                        time.sleep(0.5)
                    if "OK" in final_resp or "+CMGS" in final_resp:
                        break
                    time.sleep(2)
                else:
                    print(f"SMS segment {idx} failed")
                    return
            print(f"SMS sent to {recipient}")
    except Exception as error:
        print(f"[SMS] Failed to send: {error}")


def record_attendance(config, student_id, name):
    checked_in_at = datetime.now().strftime("%I:%M %p").lstrip("0")
    payload = {
        "studentId": student_id,
        "subject": config["subject"],
        "status": "Present",
        "timeIn": checked_in_at,
        "timeOut": "--",
    }
    try:
        response = requests.post(
            config["api_url"],
            headers={"X-Device-Token": config["device_token"]},
            json=payload,
            timeout=10,
        )
    except requests.RequestException as error:
        print(f"Attendance API connection error: {error}")
        return False
    if response.status_code == 409:
        message = response.json().get("message", "Attendance already recorded today.")
        print(f"Attendance skipped for {student_id}: {message}")
        return False
    if not response.ok:
        print(f"Attendance API error ({response.status_code}): {response.text}")
        return False
    result = response.json()
    if result.get("action") == "time_out":
        print(f"Time out recorded for {student_id} at {result.get('timeOut')}")
    else:
        provider = str(result.get("smsProvider") or config.get("sms_provider", "raspberry_pi")).lower()
        phone = result.get("parentPhone")
        student_name = result.get("studentName", name)
        message = config.get("sms_message", "{name} checked in.").format(name=student_name, subject=config["subject"], time=checked_in_at)
        if provider == "textbee":
            send_textbee(config, phone, message)
        else:
            # raspberry_pi provider implies SMS is always enabled
            send_sms(config, phone, student_name, config["subject"], checked_in_at)
        print(f"Time in recorded for {student_id} ({name}) at {checked_in_at}")
    return True


def main():
    config = load_config()
    check_api_connection(config)
    print("Attendance API connection authenticated")
    lcd = initialize_lcd()
    known_faces_dir = ROOT / config.get("known_faces_dir", "known_faces")
    student_names = sync_known_faces(config, known_faces_dir)
    known_encodings, student_ids = load_known_faces(known_faces_dir)
    camera = cv2.VideoCapture(config.get("camera_index", 0))
    if not camera.isOpened():
        raise RuntimeError("Could not open the camera")

    active_faces = {}
    absence_seconds = 5
    tolerance = config.get("match_tolerance", 0.48)
    scan_seconds = config.get("scan_seconds", 2)
    try:
        while True:
            success, frame = camera.read()
            if not success:
                continue
            now = time.time()
            seen_student_ids = set()
            small_frame = cv2.resize(frame, (0, 0), fx=0.25, fy=0.25)
            rgb_frame = cv2.cvtColor(small_frame, cv2.COLOR_BGR2RGB)
            locations = face_recognition.face_locations(rgb_frame)
            for encoding in face_recognition.face_encodings(rgb_frame, locations):
                matches = face_recognition.compare_faces(known_encodings, encoding, tolerance=tolerance)
                distances = face_recognition.face_distance(known_encodings, encoding)
                best_match = distances.argmin() if len(distances) else None
                if best_match is None or not matches[best_match]:
                    continue
                student_id = student_ids[best_match]
                seen_student_ids.add(student_id)
                if student_id not in active_faces:
                    show_lcd_student(lcd, student_names.get(student_id, student_id))
                    if record_attendance(config, student_id, student_id):
                        active_faces[student_id] = now
                else:
                    active_faces[student_id] = now
            for student_id, last_seen_at in list(active_faces.items()):
                if student_id not in seen_student_ids and now - last_seen_at >= absence_seconds:
                    del active_faces[student_id]
            if cv2.waitKey(1) & 0xFF == ord("q"):
                break
            time.sleep(scan_seconds / 10)
    finally:
        camera.release()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()