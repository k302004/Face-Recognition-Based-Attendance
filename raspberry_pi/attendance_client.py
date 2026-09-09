import json
import time
from datetime import datetime
from pathlib import Path

import cv2
import face_recognition
import requests


ROOT = Path(__file__).resolve().parent


def load_config():
    with (ROOT / "config.json").open(encoding="utf-8") as config_file:
        return json.load(config_file)


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
    checked_in_at = datetime.now().strftime("%I:%M %p").lstrip("0")
    payload = {
        "studentId": student_id,
        "subject": config["subject"],
        "status": "Present",
        "timeIn": checked_in_at,
        "timeOut": "--",
    }
    response = requests.post(
        config["api_url"],
        headers={"X-Device-Token": config["device_token"]},
        json=payload,
        timeout=10,
    )
    if response.status_code == 409:
        print(f"Time out already recorded today: {student_id}")
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


def main():
    config = load_config()
    known_faces_dir = ROOT / config.get("known_faces_dir", "known_faces")
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