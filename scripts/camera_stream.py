#!/usr/bin/python3
"""Simple MJPEG camera stream server for the DRLCEFI attendance app.

Run:
    python3 scripts/camera_stream.py [camera_index] [port]

The stream performs face recognition on every frame (when the optional
``face_recognition`` package is available) and overlays the name of the
student currently in front of the camera. The most recently identified
student is also exposed through ``/current_student`` as JSON.

Then open http://127.0.0.1:<port>/video_feed in a browser or point an <img> tag at it.
"""
import json
import os
import sqlite3
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

try:
    import cv2
except ImportError:
    print('OpenCV (cv2) is not installed. Install with: pip install opencv-python', file=sys.stderr)
    raise SystemExit(1)

HOST = "127.0.0.1"
DEFAULT_PORT = 8090
DEFAULT_CAMERA = 0

ROOT = Path(__file__).resolve().parent.parent
FACE_IMAGES_DIR = ROOT / "public" / "face_images"
DB_PATH = ROOT / "public" / "attendance.sqlite"

# Optional face recognition support. The stream still works without it.
try:
    import face_recognition
    import numpy as np

    FACE_RECOGNITION_AVAILABLE = True
except Exception:  # pragma: no cover - depends on environment
    face_recognition = None
    np = None
    FACE_RECOGNITION_AVAILABLE = False

# No fallback: face detection relies on face_recognition only.

# Known-face state (populated by load_known_faces).
KNOWN_ENCODINGS = []
KNOWN_STUDENT_IDS = []
KNOWN_STUDENT_NAMES = {}
FACE_MATCH_TOLERANCE = 0.48
RECOGNITION_INTERVAL_SECONDS = 0.5
ABSENCE_SECONDS = 5.0
POSE_INTERVAL_SECONDS = 0.3


def parse_args():
    camera_index = None
    port = DEFAULT_PORT
    target_width = 720
    target_height = 1280

    if len(sys.argv) > 1:
        try:
            camera_index = int(sys.argv[1])
        except ValueError:
            camera_index = None
    if len(sys.argv) > 2:
        try:
            port = int(sys.argv[2])
        except ValueError:
            pass
    if len(sys.argv) > 3:
        try:
            target_width = int(sys.argv[3])
        except ValueError:
            pass
    if len(sys.argv) > 4:
        try:
            target_height = int(sys.argv[4])
        except ValueError:
            pass

    if camera_index is None:
        camera_index = load_camera_index_from_config()

    return camera_index, port, target_width, target_height


def load_camera_index_from_config():
    config_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "public", "camera.config")
    if os.path.isfile(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as handle:
                config = json.load(handle)
            camera_id = str(config.get("id", "")).strip()
            if camera_id.isdigit():
                return int(camera_id)
        except Exception:
            pass
    return DEFAULT_CAMERA


def load_student_name_map(db_path=None):
    """Map face-image basename -> (student_id, full_name) from the SQLite DB."""
    mapping = {}
    path = Path(db_path) if db_path is not None else DB_PATH
    if not path.is_file():
        return mapping
    try:
        connection = sqlite3.connect(str(path))
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            "SELECT student_id, full_name, face_image_path FROM students "
            "WHERE is_archived = 0 AND face_image_path IS NOT NULL AND face_image_path != ''"
        ).fetchall()
        connection.close()
        for row in rows:
            for image_path in str(row["face_image_path"] or "").split(","):
                image_path = image_path.strip()
                if not image_path:
                    continue
                mapping[os.path.basename(image_path)] = (str(row["student_id"]), str(row["full_name"]))
    except Exception as error:
        print(f"[faces] could not read student database: {error}")
    return mapping


def load_known_faces(directory=None, student_names=None, db_path=None):
    """Load known face encodings from ``directory``.

    Returns ``(encodings, student_ids)`` to stay compatible with the reference
    ``attendance_client.load_known_faces``. Recognised names are stored in the
    module-level ``KNOWN_STUDENT_NAMES`` mapping.
    """
    global KNOWN_ENCODINGS, KNOWN_STUDENT_IDS, KNOWN_STUDENT_NAMES

    if directory is None:
        if FACE_IMAGES_DIR.is_dir():
            directory = FACE_IMAGES_DIR
        else:
            directory = ROOT / "known_faces"
    directory = Path(directory)

    name_map = load_student_name_map(db_path)
    provided_names = student_names or {}

    encodings = []
    student_ids = []
    names = {}

    if not FACE_RECOGNITION_AVAILABLE:
        print("[faces] face_recognition is not installed; streaming without recognition")
        return encodings, student_ids

    if not directory.is_dir():
        print(f"[faces] known faces directory not found: {directory}")
        return encodings, student_ids

    for image_path in sorted(directory.iterdir()):
        if not image_path.is_file():
            continue
        if image_path.suffix.lower() not in {".jpg", ".jpeg", ".png", ".webp"}:
            continue
        try:
            image = face_recognition.load_image_file(str(image_path))
            face_encodings = face_recognition.face_encodings(image)
        except Exception as error:
            print(f"[faces] could not read {image_path.name}: {error}")
            continue
        if len(face_encodings) != 1:
            print(f"[faces] skipping {image_path.name}: expected exactly one face, found {len(face_encodings)}")
            continue

        db_entry = name_map.get(image_path.name)
        if db_entry is not None:
            student_id = db_entry[0]
            student_name = db_entry[1]
        else:
            student_id = image_path.stem
            student_name = provided_names.get(student_id, student_id)

        encodings.append(face_encodings[0])
        student_ids.append(student_id)
        names[student_id] = student_name

    if not encodings:
        print(f"[faces] no usable face images found in {directory}")
    else:
        print(f"[faces] loaded {len(encodings)} known face(s) from {directory}")

    KNOWN_ENCODINGS = encodings
    KNOWN_STUDENT_IDS = student_ids
    KNOWN_STUDENT_NAMES = names
    return encodings, student_ids


def get_student_name(student_id):
    if student_id is None:
        return None
    return KNOWN_STUDENT_NAMES.get(str(student_id), str(student_id))


def recognize_frame(frame, known_encodings=None, student_ids=None, tolerance=None):
    """Return (locations, student_ids, names, confidences) for a BGR frame."""
    if known_encodings is None:
        known_encodings = KNOWN_ENCODINGS
    if student_ids is None:
        student_ids = KNOWN_STUDENT_IDS
    if tolerance is None:
        tolerance = FACE_MATCH_TOLERANCE

    locations = []
    matched_ids = []
    names = []
    confidences = []

    if not FACE_RECOGNITION_AVAILABLE:
        return locations, matched_ids, names, confidences

    small = cv2.resize(frame, (0, 0), fx=0.25, fy=0.25)
    rgb_small = cv2.cvtColor(small, cv2.COLOR_BGR2RGB)
    face_locations_small = face_recognition.face_locations(rgb_small)
    face_encodings = face_recognition.face_encodings(rgb_small, face_locations_small)

    for location, encoding in zip(face_locations_small, face_encodings):
        top, right, bottom, left = location
        scaled_location = (top * 4, right * 4, bottom * 4, left * 4)
        locations.append(scaled_location)

        if not known_encodings:
            matched_ids.append(None)
            names.append("Unknown")
            confidences.append(None)
            continue

        distances = face_recognition.face_distance(known_encodings, encoding)
        best_index = int(np.argmin(distances)) if len(distances) else None
        if best_index is not None and distances[best_index] <= tolerance:
            student_id = student_ids[best_index]
            matched_ids.append(student_id)
            names.append(get_student_name(student_id))
            confidences.append(float(1.0 - distances[best_index]))
        else:
            matched_ids.append(None)
            names.append("Unknown")
            confidences.append(float(distances[best_index]) if best_index is not None else None)

    return locations, matched_ids, names, confidences


def process_frame(frame, known_encodings=None, student_ids=None, tolerance=None):
    """Annotate ``frame`` with recognised faces and return (frame, student).

    ``student`` is the dict returned by :func:`identify_current_student` or
    ``None``. The input frame is copied before drawing.
    """
    if known_encodings is None:
        known_encodings = KNOWN_ENCODINGS
    if student_ids is None:
        student_ids = KNOWN_STUDENT_IDS
    result_frame = frame.copy()
    locations, matched_ids, names, confidences = recognize_frame(
        result_frame, known_encodings=known_encodings, student_ids=student_ids, tolerance=tolerance
    )
    for location, name in zip(locations, names):
        top, right, bottom, left = location
        color = (0, 200, 0) if (name and name != "Unknown") else (0, 0, 200)
        cv2.rectangle(result_frame, (left, top), (right, bottom), color, 2)
        label = name or "Unknown"
        (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 2)
        cv2.rectangle(result_frame, (left, bottom), (left + tw + 8, bottom + th + 10), color, cv2.FILLED)
        cv2.putText(result_frame, label, (left + 4, bottom + th + 4), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)

    student = None
    for sid, name, conf in zip(matched_ids, names, confidences):
        if sid is not None:
            student = {"student_id": sid, "name": name, "confidence": conf}
            break

    overlay = "Current: {} ({})".format(student["name"], student["student_id"]) if student else "No student detected"
    cv2.putText(result_frame, overlay, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 0), 2)
    return result_frame, student


def identify_current_student(frame, known_encodings=None, student_ids=None, tolerance=None):
    """Identify the (first recognised) student present in ``frame``.

    Returns a dict ``{"student_id": ..., "name": ..., "confidence": ...}``
    or ``None`` when no known student is found.
    """
    locations, matched_ids, names, confidences = recognize_frame(
        frame, known_encodings=known_encodings, student_ids=student_ids, tolerance=tolerance
    )
    for student_id, name, confidence in zip(matched_ids, names, confidences):
        if student_id is not None:
            return {
                "student_id": student_id,
                "name": name,
                "confidence": confidence,
            }
    return None


def identify_student(frame, known_encodings=None, student_ids=None, tolerance=None):
    return identify_current_student(frame, known_encodings=known_encodings, student_ids=student_ids, tolerance=tolerance)


def recognize_student(frame, known_encodings=None, student_ids=None, tolerance=None):
    return identify_current_student(frame, known_encodings=known_encodings, student_ids=student_ids, tolerance=tolerance)


def get_current_student():
    """Return the module/global current student if a stream is running."""
    return None


def identify_student_in_image(image_path, known_encodings=None, student_ids=None, tolerance=None):
    """Convenience helper: identify a student from an image file path."""
    image = cv2.imread(str(image_path))
    if image is None:
        return None
    if known_encodings is None:
        load_known_faces()
        known_encodings = KNOWN_ENCODINGS
        student_ids = KNOWN_STUDENT_IDS
    return identify_current_student(image, known_encodings=known_encodings, student_ids=student_ids, tolerance=tolerance)


def detect_face_pose(frame, known_encodings=None, student_ids=None, tolerance=None):
    """Estimate the pose of the first face in ``frame``.

    Returns one of: 'front', 'up', 'down', 'left', 'right', 'none'.
    """
    if not FACE_RECOGNITION_AVAILABLE:
        return 'none'
    small = cv2.resize(frame, (0, 0), fx=0.25, fy=0.25)
    rgb_small = cv2.cvtColor(small, cv2.COLOR_BGR2RGB)
    locations = face_recognition.face_locations(rgb_small)
    if not locations:
        return 'none'
    landmarks_list = face_recognition.face_landmarks(rgb_small, [locations[0]])
    if not landmarks_list:
        return 'front'
    lm = landmarks_list[0]
    nose = lm.get('nose_tip') or lm.get('nose_bridge') or []
    chin = lm.get('chin') or []
    left_eye = lm.get('left_eye') or []
    right_eye = lm.get('right_eye') or []

    if not nose or not chin or not left_eye or not right_eye:
        return 'front'

    def mean(points, idx):
        return sum(p[idx] for p in points) / len(points)

    eye_cx = (mean(left_eye, 0) + mean(right_eye, 0)) / 2.0
    eye_cy = (mean(left_eye, 1) + mean(right_eye, 1)) / 2.0
    nose_x = mean(nose, 0)
    nose_y = mean(nose, 1)
    chin_y = mean(chin, 1)
    eye_span = max(1.0, mean(right_eye, 0) - mean(left_eye, 0))

    vertical_ratio = (nose_y - eye_cy) / max(1.0, chin_y - eye_cy)
    horizontal_ratio = (nose_x - eye_cx) / eye_span

    if vertical_ratio < 0.42:
        return 'up'
    if vertical_ratio > 0.72:
        return 'down'
    if horizontal_ratio > 0.18:
        return 'right'
    if horizontal_ratio < -0.18:
        return 'left'
    return 'front'


def open_camera(index):
    import platform

    backends = []
    if platform.system().lower() == "windows" and hasattr(cv2, "CAP_DSHOW"):
        backends.append(cv2.CAP_DSHOW)
    backends.append(None)  # default

    # Normalize index to an int when possible.
    try:
        idx = int(index)
    except (TypeError, ValueError):
        idx = 0

    for backend in backends:
        if backend is None:
            capture = cv2.VideoCapture(idx)
        else:
            capture = cv2.VideoCapture(idx, backend)
        if capture is not None and capture.isOpened():
            ok, _ = capture.read()
            if ok:
                return capture, idx
            capture.release()

    # Try a few more indices in case the requested one is unavailable.
    for candidate in range(0, 5):
        for backend in backends:
            if backend is None:
                capture = cv2.VideoCapture(candidate)
            else:
                capture = cv2.VideoCapture(candidate, backend)
            if capture is not None and capture.isOpened():
                ok, _ = capture.read()
                if ok:
                    return capture, candidate
                capture.release()
    return None, None


class StreamHandler(BaseHTTPRequestHandler):
    def _send_json(self, payload, status=200):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            body = b"<html><body><img src='/video_feed' style='max-width:100%'><div id='student'></div></body></html>"
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        if self.path.startswith("/current_student") or self.path.startswith("/current"):
            info = getattr(self.server, "current_student", None)
            face_detected = getattr(self.server, "face_detected", False)
            if FACE_RECOGNITION_AVAILABLE:
                face_detected = len(getattr(self.server, "last_face_locations", [])) > 0
            self._send_json({"student": info, "face_detected": bool(face_detected)})
            return

        if self.path.startswith("/face_pose") or self.path.startswith("/pose"):
            pose = getattr(self.server, "current_pose", "none")
            self._send_json({"pose": pose})
            return

        if self.path.startswith("/students"):
            students = [
                {"student_id": sid, "name": KNOWN_STUDENT_NAMES.get(sid, sid)}
                for sid in KNOWN_STUDENT_IDS
            ]
            self._send_json({"students": students, "face_recognition": FACE_RECOGNITION_AVAILABLE})
            return

        if self.path != "/video_feed":
            self.send_response(404)
            self.end_headers()
            return

        self.send_response(200)
        self.send_header("Age", "0")
        self.send_header("Cache-Control", "no-cache, private")
        self.send_header("Pragma", "no-cache")
        self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
        self.end_headers()

        capture = self.server.camera[0]  # (capture, index)
        try:
            while True:
                ok, frame = capture.read()
                if not ok or frame is None:
                    time.sleep(0.05)
                    continue

                height, width = frame.shape[:2]
                target_w, target_h = self.server.target_size
                target_aspect = target_w / target_h if target_h else (9.0 / 16.0)
                current_aspect = width / height if height else target_aspect
                if current_aspect > target_aspect:
                    new_width = int(height * target_aspect)
                    x_offset = (width - new_width) // 2
                    frame = frame[:, x_offset:x_offset + new_width]
                elif current_aspect < target_aspect:
                    new_height = int(width / target_aspect)
                    y_offset = (height - new_height) // 2
                    frame = frame[y_offset:y_offset + new_height, :]

                frame = cv2.resize(frame, (target_w, target_h))

                # Face recognition (throttled).
                now = time.time()
                if FACE_RECOGNITION_AVAILABLE and (now - getattr(self.server, "last_recognition_time", 0.0) >= RECOGNITION_INTERVAL_SECONDS):
                    self.server.last_recognition_time = now
                    locations, matched_ids, names, confidences = recognize_frame(frame)
                    self.server.last_face_locations = locations
                    self.server.last_face_names = names
                    self.server.last_face_ids = matched_ids
                    self.server.face_detected = len(locations) > 0
                    # Current student = first recognised face in frame.
                    current = None
                    for sid, name, conf in zip(matched_ids, names, confidences):
                        if sid is not None:
                            current = {"student_id": sid, "name": name, "confidence": conf, "timestamp": now}
                            break
                    if current is not None:
                        self.server.current_student = current
                        self.server.current_student_seen_at = now
                    else:
                        last_seen = getattr(self.server, "current_student_seen_at", 0.0)
                        if now - last_seen >= ABSENCE_SECONDS:
                            self.server.current_student = None

                # Pose detection (throttled).
                if FACE_RECOGNITION_AVAILABLE and (now - getattr(self.server, "last_pose_time", 0.0) >= POSE_INTERVAL_SECONDS):
                    self.server.last_pose_time = now
                    self.server.current_pose = detect_face_pose(frame)

                pass

                # Draw overlays.
                locations = getattr(self.server, "last_face_locations", [])
                names = getattr(self.server, "last_face_names", [])
                for location, name in zip(locations, names):
                    top, right, bottom, left = location
                    if name and name != "Unknown":
                        color = (0, 200, 0)
                    else:
                        color = (0, 0, 200)
                    cv2.rectangle(frame, (left, top), (right, bottom), color, 2)
                    label = name or "Unknown"
                    (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 2)
                    cv2.rectangle(frame, (left, bottom), (left + tw + 8, bottom + th + 10), color, cv2.FILLED)
                    cv2.putText(frame, label, (left + 4, bottom + th + 4), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)

                current_info = getattr(self.server, "current_student", None)
                if current_info:
                    overlay = "Current: {} ({})".format(current_info.get("name"), current_info.get("student_id"))
                else:
                    overlay = "No student detected"
                cv2.putText(frame, overlay, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 0), 2)

                ok, buffer = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
                if not ok:
                    continue

                payload = buffer.tobytes()
                self.wfile.write(b"--frame\r\n")
                self.wfile.write(b"Content-Type: image/jpeg\r\n")
                self.wfile.write(f"Content-Length: {len(payload)}\r\n\r\n".encode("ascii"))
                self.wfile.write(payload)
                self.wfile.write(b"\r\n")
                time.sleep(0.033)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def log_message(self, format, *args):
        # Keep the console quiet.
        pass


def main():
    camera_index, port, target_width, target_height = parse_args()

    capture, opened_index = open_camera(camera_index)
    if capture is None:
        print(f"Unable to open any camera (requested index {camera_index}).", file=sys.stderr)
        sys.exit(1)

    # Load known faces (from DB-backed face_images when available).
    load_known_faces()

    print(f"Streaming camera index {opened_index} on http://{HOST}:{port}/video_feed ({target_width}x{target_height})")
    if FACE_RECOGNITION_AVAILABLE:
        print(f"[faces] recognition enabled with {len(KNOWN_ENCODINGS)} known face(s)")
    else:
        print("[faces] recognition disabled (face_recognition not installed)")

    server = ThreadingHTTPServer((HOST, port), StreamHandler)
    server.camera = (capture, opened_index)
    server.target_size = (target_width, target_height)
    server.current_student = None
    server.current_student_seen_at = 0.0
    server.last_recognition_time = 0.0
    server.current_pose = "none"
    server.last_pose_time = 0.0
    server.face_detected = False
    server.last_cascade_time = 0.0
    server.last_face_locations = []
    server.last_face_names = []
    server.last_face_ids = []
    try:
        server.serve_forever()
    finally:
        capture.release()
        server.server_close()


if __name__ == "__main__":
    main()
