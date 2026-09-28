import base64
import hashlib
import json
import queue
import threading
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

import cv2
import face_recognition
import numpy as np  # for caching face encodings as .npy files
import requests
try:
    from RPLCD.i2c import CharLCD
except ImportError:
    CharLCD = None


ROOT = Path(__file__).resolve().parent


def load_config():
    with (ROOT / "config.json").open(encoding="utf-8") as config_file:
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
    """Incrementally sync student face images from API.
    
    Only downloads new/changed images, removes deleted ones,
    and invalidates encoding cache only when image actually changes.
    """
    api_url = config["api_url"].split("?", 1)[0] + "?action=device-faces"
    try:
        response = requests.get(api_url, headers={"X-Device-Token": config["device_token"]}, timeout=15)
        response.raise_for_status()
        faces = response.json().get("faces", [])
    except (requests.RequestException, ValueError) as error:
        raise RuntimeError(f"Could not download student photos from the website: {error}") from error

    directory.mkdir(parents=True, exist_ok=True)
    student_names = {}
    server_ids = set()

    for face in faces:
        image_data = str(face.get("image", ""))
        student_id = face.get("studentId")
        if "," not in image_data or not student_id:
            continue

        server_ids.add(student_id)
        student_names[str(student_id)] = str(face.get("studentName", student_id))

        image_bytes = base64.b64decode(image_data.split(",", 1)[1], validate=True)
        image_hash = hashlib.sha256(image_bytes).hexdigest()

        image_path = directory / f"{student_id}.jpg"
        hash_path = directory / f"{student_id}.hash"

        # Only update if image changed (compare hash)
        if not image_path.exists() or (hash_path.read_text().strip() != image_hash):
            image_path.write_bytes(image_bytes)
            hash_path.write_text(image_hash)
            # Invalidate encoding cache only when image changed
            npy_path = directory / f"{student_id}.npy"
            if npy_path.exists():
                npy_path.unlink()
            print(f"Updated face image for {student_id}")

    # Remove local files for students no longer on server
    for local_file in directory.glob("*.jpg"):
        student_id = local_file.stem
        if student_id not in server_ids:
            local_file.unlink()
            (directory / f"{student_id}.npy").unlink(missing_ok=True)
            (directory / f"{student_id}.hash").unlink(missing_ok=True)
            print(f"Removed deleted student {student_id}")

    print(f"Synced {len(server_ids)} student face photo(s) from the website")
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
    """Load face encodings from cached .npy files, computing and caching if needed."""
    encodings = []
    student_ids = []
    directory = Path(directory)
    for image_path in sorted(directory.glob("*")):
        if image_path.suffix.lower() not in {".jpg", ".jpeg", ".png"}:
            continue
        npy_path = directory / f"{image_path.stem}.npy"
        if npy_path.exists():
            # Load pre-computed encoding from cache (fast)
            encoding = np.load(npy_path)
            encodings.append(encoding)
            student_ids.append(image_path.stem)
        else:
            # Compute encoding from image and cache it (slow, first time only)
            image = face_recognition.load_image_file(image_path)
            face_encodings = face_recognition.face_encodings(image)
            if len(face_encodings) != 1:
                print(f"Skipping {image_path.name}: expected exactly one face")
                continue
            encoding = face_encodings[0]
            np.save(npy_path, encoding)
            encodings.append(encoding)
            student_ids.append(image_path.stem)
    if not encodings:
        raise RuntimeError("No usable face images found in known_faces")
    return encodings, student_ids


def send_sms(config, recipient, name, subject, checked_in_at):
    if not config.get("sms_enabled"):
        return
    import serial

    if not recipient:
        print("SMS skipped: this student has no parent phone number")
        return
    message = config["sms_message"].format(name=name, subject=subject, time=checked_in_at)
    with serial.Serial(config["sms_port"], config.get("sms_baud", 115200), timeout=5) as modem:
        modem.write(b"AT\r")
        time.sleep(1)
        modem.write(b"AT+CMGF=1\r")
        time.sleep(1)
        modem.write((f'AT+CMGS="{recipient}"\r').encode())
        time.sleep(1)
        modem.write(message.encode() + b"\x1a")
        time.sleep(5)


def record_attendance(config, student_id, name):
    """Synchronous attendance recording - kept for compatibility."""
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
        send_sms(config, result.get("parentPhone"), result.get("studentName", name), config["subject"], checked_in_at)
        print(f"Time in recorded for {student_id} ({name}) at {checked_in_at}")
    return True


def _attendance_worker(attendance_queue, config):
    """Background worker to process attendance recordings asynchronously."""
    while True:
        task = attendance_queue.get()
        if task is None:  # Shutdown signal
            break
        student_id, name = task
        try:
            record_attendance(config, student_id, name)
        except Exception as error:
            print(f"Attendance worker error for {student_id}: {error}")
        finally:
            attendance_queue.task_done()


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
    scan_seconds = config.get("scan_seconds", 5)
    process_every_n = config.get("process_every_n_frames", 3)
    frame_counter = 0

    # ============================================================
    # OPTIMIZATION: Async attendance recording via background thread
    # ============================================================
    # WHY: record_attendance() makes an HTTP POST which blocks 50-500ms.
    #      In the main loop this would stall face detection, causing
    #      dropped frames and higher CPU from queue buildup.
    # SOLUTION: Fire-and-forget queue processed by a daemon thread.
    #           Main loop stays responsive; attendance writes happen async.
    # ============================================================
    attendance_queue = queue.Queue()
    worker_thread = threading.Thread(target=_attendance_worker, args=(attendance_queue, config), daemon=True)
    worker_thread.start()

    try:
        while True:
            success, frame = camera.read()
            if not success:
                continue

            frame_counter += 1
            # ============================================================
            # OPTIMIZATION: Frame skipping (process_every_n_frames)
            # ============================================================
            # WHY: face_locations() + face_encodings() = 150-450ms/frame.
            #      Running every frame at 5-10 FPS overheats Pi (esp Pi 3/Zero).
            # SOLUTION: Only run heavy detection every N frames.
            #           Default N=3 reduces CPU ~66% with minimal miss rate
            #           since students pause in front of camera for seconds.
            # ============================================================
            if frame_counter % process_every_n != 0:
                if cv2.waitKey(1) & 0xFF == ord("q"):
                    break
                time.sleep(scan_seconds / 10)
                continue

            now = time.time()
            seen_student_ids = set()
            small_frame = cv2.resize(frame, (0, 0), fx=0.25, fy=0.25)
            rgb_frame = cv2.cvtColor(small_frame, cv2.COLOR_BGR2RGB)
            locations = face_recognition.face_locations(rgb_frame)

            # ============================================================
            # OPTIMIZATION: Early exit guard
            # ============================================================
            # WHY: face_encodings() is the most expensive call (100-300ms).
            #      Most frames have no faces (empty hallway, etc.).
            # SOLUTION: Check face_locations() result first.
            #           If empty, skip encoding entirely and continue loop.
            #           Saves 100-300ms per empty frame.
            # ============================================================
            if not locations:
                if cv2.waitKey(1) & 0xFF == ord("q"):
                    break
                time.sleep(scan_seconds / 10)
                continue

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
                    # Async: queue attendance instead of blocking HTTP call
                    attendance_queue.put((student_id, student_id))
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
        # Graceful shutdown: wait for queue to drain, then stop worker
        attendance_queue.join()
        attendance_queue.put(None)
        worker_thread.join(timeout=5)
        camera.release()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()