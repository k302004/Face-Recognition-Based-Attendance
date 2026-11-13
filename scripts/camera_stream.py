#!/usr/bin/python3
"""Simple MJPEG camera stream server for the DRLCEFI attendance app.

Run:
    python3 scripts/camera_stream.py [camera_index] [port]

The stream performs face recognition in a background worker (when the optional
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
import socket
import multiprocessing
import queue
from types import SimpleNamespace
try:
    import websockets
    import asyncio
    WEBSOCKETS_AVAILABLE = True
except ImportError:
    WEBSOCKETS_AVAILABLE = False
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

try:
    import cv2
except ImportError:
    print('OpenCV (cv2) is not installed. Install with: pip install opencv-python', file=sys.stderr)
    raise SystemExit(1)

HOST = "0.0.0.0"
DEFAULT_PORT = 8090
WEBSOCKET_PORT = 8091
DEFAULT_CAMERA = 0

ROOT = Path(__file__).resolve().parent.parent
FACE_IMAGES_DIR = ROOT / "public" / "face_images"
DB_PATH = ROOT / "public" / "attendance.sqlite"
CAMERA_CONFIG_PATH = ROOT / "public" / "camera.config"

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
STUDENT_DETAILS = {}
KNOWN_IMAGE_FILES = set()
FACE_CACHE = {}
FACE_STATE_LOCK = threading.Lock()
# dlib uses shared native detector objects; concurrent calls can crash Windows.
FACE_ENGINE_LOCK = threading.Lock()
http_server = None
FACE_MATCH_TOLERANCE = 0.40
FACE_MATCH_MARGIN = 0.07
RECOGNITION_INTERVAL_SECONDS = 0.15
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

    # The saved selection is authoritative, including legacy API launches
    # that still pass a positional camera index.
    if CAMERA_CONFIG_PATH.is_file() or camera_index is None:
        camera_index = load_camera_index_from_config()

    return camera_index, port, target_width, target_height


def load_camera_index_from_config():
    if not CAMERA_CONFIG_PATH.is_file():
        return DEFAULT_CAMERA
    try:
        with CAMERA_CONFIG_PATH.open(encoding="utf-8-sig") as handle:
            config = json.load(handle)
        camera_id = str(config.get("id", "")).strip()
        if not camera_id.isdigit():
            raise ValueError("id must be a non-negative camera index")
        return int(camera_id)
    except (OSError, ValueError, AttributeError) as error:
        raise ValueError(f"Invalid camera configuration in {CAMERA_CONFIG_PATH}: {error}") from error

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
                mapping[image_path.replace("\\", "/").rsplit("/", 1)[-1]] = (str(row["student_id"]), str(row["full_name"]))
    except Exception as error:
        print(f"[faces] could not read student database: {error}")
    return mapping


def load_student_details(db_path=None):
    """Load full student records keyed by student_id from the SQLite DB."""
    details = {}
    path = Path(db_path) if db_path is not None else DB_PATH
    if not path.is_file():
        return details
    try:
        connection = sqlite3.connect(str(path))
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            "SELECT student_id, full_name, course, year, age, school_year, status, parent_phone, face_image_path "
            "FROM students WHERE is_archived = 0"
        ).fetchall()
        connection.close()
        for row in rows:
            sid = str(row["student_id"])
            details[sid] = {
                "student_id": sid,
                "name": str(row["full_name"] or sid),
                "full_name": str(row["full_name"] or sid),
                "course": row["course"],
                "year": row["year"],
                "age": row["age"],
                "school_year": row["school_year"],
                "status": row["status"],
                "parent_phone": row["parent_phone"],
                "face_image_path": row["face_image_path"],
            }
    except Exception as error:
        print(f"[faces] could not read student details: {error}")
    return details


def load_known_faces(directory=None, student_names=None, db_path=None):
    """Load known face encodings from ``directory``.

    Returns ``(encodings, student_ids)`` to stay compatible with the reference
    ``attendance_client.load_known_faces``. Recognised names are stored in the
    module-level ``KNOWN_STUDENT_NAMES`` mapping.
    """
    global KNOWN_ENCODINGS, KNOWN_STUDENT_IDS, KNOWN_STUDENT_NAMES, STUDENT_DETAILS, KNOWN_IMAGE_FILES

    if directory is None:
        if FACE_IMAGES_DIR.is_dir():
            directory = FACE_IMAGES_DIR
        else:
            directory = ROOT / "known_faces"
    directory = Path(directory)

    name_map = load_student_name_map(db_path)
    details = load_student_details(db_path)
    image_files = set()
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
        db_entry = name_map.get(image_path.name)
        # Attendance photos must belong to an active registered student.
        if db_entry is None and directory.resolve() == FACE_IMAGES_DIR.resolve():
            continue
        try:
            stat = image_path.stat()
            key = (str(image_path.resolve()), stat.st_mtime_ns, stat.st_size)
            if key in FACE_CACHE:
                face_encodings = FACE_CACHE[key]
            else:
                image = face_recognition.load_image_file(str(image_path))
                height, width = image.shape[:2]
                if max(height, width) > 640:
                    scale = 640 / max(height, width)
                    image = cv2.resize(image, (round(width * scale), round(height * scale)))
                with FACE_ENGINE_LOCK:
                    face_encodings = face_recognition.face_encodings(image)
                FACE_CACHE[key] = face_encodings
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
            if student_id in details:
                details[student_id]['full_name'] = student_name
        else:
            student_id = image_path.stem
            student_name = provided_names.get(student_id, student_id)

        encodings.append(face_encodings[0])
        student_ids.append(student_id)
        names[student_id] = student_name
        image_files.add(image_path.name)

    if student_ids != KNOWN_STUDENT_IDS:
        print(f"[faces] loaded {len(encodings)} registered face(s) from {directory}")

    with FACE_STATE_LOCK:
        KNOWN_ENCODINGS = encodings
        KNOWN_STUDENT_IDS = student_ids
        KNOWN_STUDENT_NAMES = names
        STUDENT_DETAILS = details
        KNOWN_IMAGE_FILES = image_files
    return encodings, student_ids


def get_student_name(student_id):
    if student_id is None:
        return None
    return KNOWN_STUDENT_NAMES.get(str(student_id), str(student_id))


def select_face_match(distances, student_ids, tolerance):
    """Compare distinct students, rather than competing photos of one student."""
    scores = {}
    for distance, sid in zip(distances, student_ids):
        scores[sid] = min(float(distance), scores.get(sid, float('inf')))
    ranked = sorted(scores.items(), key=lambda item: item[1])
    if not ranked or ranked[0][1] > tolerance:
        return None, None
    if len(ranked) > 1 and ranked[1][1] - ranked[0][1] < FACE_MATCH_MARGIN:
        return None, None
    return ranked[0]


class MatchConfirmation:
    def __init__(self):
        self.sid = None
        self.count = 0
        self.started = 0.0
        self.last_seen = 0.0

    def update(self, ids, now):
        sid = ids[0] if len(ids) == 1 else None
        if sid is None:
            self.sid = None
            self.count = 0
            return None
        if sid != self.sid or now - self.last_seen > 1.5:
            self.sid, self.count, self.started = sid, 0, now
        self.last_seen = now
        self.count += 1
        return sid if self.count >= 3 and now - self.started >= 0.5 else None


def recognition_image(frame):
    height, width = frame.shape[:2]
    scale = min(1.0, 320.0 / max(height, width))
    small = cv2.resize(frame, (max(1, round(width * scale)), max(1, round(height * scale))))
    return cv2.cvtColor(small, cv2.COLOR_BGR2RGB), width / small.shape[1], height / small.shape[0]


def resize_output(frame, target_size):
    height, width = frame.shape[:2]
    scale = min(1.0, target_size[0] / width, target_size[1] / height)
    if scale < 1.0:
        return cv2.resize(frame, (max(1, round(width * scale)), max(1, round(height * scale))))
    return frame


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

    rgb_small, scale_x, scale_y = recognition_image(frame)
    with FACE_ENGINE_LOCK:
        # The fast detector handles nearby faces; keep the higher-resolution
        # fallback for small faces rather than sacrificing detection coverage.
        face_locations_small = face_recognition.face_locations(rgb_small, number_of_times_to_upsample=0)
        if not face_locations_small:
            face_locations_small = face_recognition.face_locations(rgb_small, number_of_times_to_upsample=1)
        face_encodings = face_recognition.face_encodings(rgb_small, face_locations_small)

    for location, encoding in zip(face_locations_small, face_encodings):
        top, right, bottom, left = location
        scaled_location = (round(top * scale_y), round(right * scale_x), round(bottom * scale_y), round(left * scale_x))
        locations.append(scaled_location)

        if not known_encodings:
            matched_ids.append(None)
            names.append("Unknown")
            confidences.append(None)
            continue

        distances = face_recognition.face_distance(known_encodings, encoding)
        student_id, distance = select_face_match(distances, student_ids, tolerance)
        if student_id is not None:
            matched_ids.append(student_id)
            names.append(get_student_name(student_id))
            confidences.append(float(1.0 - distance))
        else:
            matched_ids.append(None)
            names.append("Unknown")
            confidences.append(None)

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
    rgb_small, _, _ = recognition_image(frame)
    with FACE_ENGINE_LOCK:
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
    if platform.system().lower() == "windows" and hasattr(cv2, "CAP_MSMF"):
        backends.append(cv2.CAP_MSMF)
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
        if capture is None:
            continue
        if capture.isOpened():
            for attempt in range(5):
                ok, frame = capture.read()
                if ok and frame is not None:
                    capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                    return capture, idx
                if attempt < 4:
                    time.sleep(0.1)
        capture.release()

    return None, None


class CameraPipeline:
    """One camera owner, latest-only frames, and independent face analysis."""

    def __init__(self, server):
        self.server = server
        self.stop = threading.Event()
        self.condition = threading.Condition()
        self.frame = None
        self.jpeg = None
        self.sequence = 0
        self.threads = []
        self.worker = None
        self.frame_queue = None
        self.result_queue = None
        self.last_submitted = 0.0

    def start(self, use_process=True):
        if use_process and FACE_RECOGNITION_AVAILABLE:
            context = multiprocessing.get_context('spawn')
            self.worker_stop = context.Event()
            self.frame_queue = context.Queue(maxsize=1)
            self.result_queue = context.Queue(maxsize=1)
            self.worker = context.Process(target=recognition_worker, args=(self.frame_queue, self.result_queue, self.worker_stop), daemon=True)
            self.worker.start()
            targets = (self.capture_frames, self.receive_results)
        else:
            targets = (self.capture_frames, self.analyze_frames, self.reload_faces)
        for target in targets:
            thread = threading.Thread(target=target, daemon=True)
            self.threads.append(thread)
            thread.start()

    def capture_frames(self):
        capture = self.server.camera[0]
        try:
            while not self.stop.is_set():
                started = time.monotonic()
                ok, frame = capture.read()
                if not ok or frame is None:
                    self.stop.wait(0.05)
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

                # The browser handles display scaling. Enlarging a 270x480 USB
                # crop to 720x1280 adds JPEG/IPC/network work without detail.
                frame = resize_output(frame, (target_w, target_h))
                # Publish an untouched frame for analysis; drawing uses a copy.
                with self.condition:
                    self.frame = frame
                if self.frame_queue is not None and time.monotonic() - self.last_submitted >= RECOGNITION_INTERVAL_SECONDS:
                    replace_latest(self.frame_queue, (frame, getattr(self.server, 'pose_requested_at', -10.0)))
                    self.last_submitted = time.monotonic()
                frame = frame.copy()
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
                with self.condition:
                    self.jpeg = payload
                    self.sequence += 1
                    self.condition.notify_all()
                self.stop.wait(max(0.0, 1.0 / 30.0 - (time.monotonic() - started)))
        finally:
            capture.release()

    def analyze_frames(self):
        confirmation = MatchConfirmation()
        last_analyzed = None
        while not self.stop.is_set():
            started = time.monotonic()
            with self.condition:
                frame = self.frame
            if frame is None:
                self.stop.wait(0.02)
                continue
            if frame is last_analyzed:
                self.stop.wait(0.02)
                continue
            last_analyzed = frame
            try:
                # Face recognition (throttled).
                now = time.monotonic()
                if FACE_RECOGNITION_AVAILABLE and (now - getattr(self.server, "last_recognition_time", 0.0) >= RECOGNITION_INTERVAL_SECONDS):
                    self.server.last_recognition_time = now
                    with FACE_STATE_LOCK:
                        encodings, ids = KNOWN_ENCODINGS, KNOWN_STUDENT_IDS
                    locations, matched_ids, names, confidences = recognize_frame(frame, encodings, ids)
                    confirmed_id = confirmation.update(matched_ids, now)
                    # Never expose provisional identities to attendance clients.
                    if confirmed_id is None:
                        matched_ids = [None] * len(locations)
                        names = ['Unknown'] * len(locations)
                    self.server.last_face_locations = locations
                    self.server.last_face_names = names
                    self.server.last_face_ids = matched_ids
                    self.server.face_detected = len(locations) > 0
                    # Current student = first recognised face in frame.
                    current = None
                    for sid, name, conf in zip(matched_ids, names, confidences):
                        if sid is not None:
                            current = {"student_id": sid, "name": name, "confidence": conf, "timestamp": time.time()}
                            details = STUDENT_DETAILS.get(str(sid))
                            if details:
                                current.update({k: v for k, v in details.items() if k not in ("student_id", "name")})
                                current["full_name"] = details.get("full_name") or name
                            break
                    if current is not None:
                        self.server.current_student = current
                        self.server.current_student_seen_at = now
                    else:
                        self.server.current_student = None

                # Pose detection (throttled).
                if FACE_RECOGNITION_AVAILABLE and (now - getattr(self.server, "pose_requested_at", -10.0) < 2.0) and (now - getattr(self.server, "last_pose_time", 0.0) >= POSE_INTERVAL_SECONDS):
                    self.server.last_pose_time = now
                    self.server.current_pose = detect_face_pose(frame)
                if self.result_queue is not None:
                    state = {key: getattr(self.server, key, None) for key in (
                        'current_student', 'current_pose', 'face_detected', 'last_face_locations', 'last_face_names', 'last_face_ids'
                    )}
                    state['known_ids'] = KNOWN_STUDENT_IDS
                    state['known_names'] = KNOWN_STUDENT_NAMES
                    replace_latest(self.result_queue, state)

            except Exception as error:
                print(f"[faces] analysis error: {error}")
            self.stop.wait(max(0.01, RECOGNITION_INTERVAL_SECONDS - (time.monotonic() - started)))

    def reload_faces(self):
        while not self.stop.is_set():
            try:
                load_known_faces()
            except Exception as error:
                print(f"[faces] reload error: {error}")
            self.stop.wait(2.0)

    def close(self):
        self.stop.set()
        if self.worker is not None:
            self.worker_stop.set()
            self.worker.join(timeout=3)
            if self.worker.is_alive():
                self.worker.terminate()
                self.worker.join(timeout=2)
            for channel in (self.frame_queue, self.result_queue):
                channel.cancel_join_thread()
                channel.close()
        with self.condition:
            self.condition.notify_all()
        for thread in self.threads:
            thread.join(timeout=2.0)

    def receive_results(self):
        global KNOWN_STUDENT_IDS, KNOWN_STUDENT_NAMES
        last_result = time.monotonic()
        while not self.stop.is_set():
            try:
                state = self.result_queue.get(timeout=0.2)
                last_result = time.monotonic()
                KNOWN_STUDENT_IDS = state.pop('known_ids')
                KNOWN_STUDENT_NAMES = state.pop('known_names')
                for key, value in state.items():
                    setattr(self.server, key, value)
            except queue.Empty:
                if time.monotonic() - last_result > 2.0:
                    self.server.current_student = None
                    self.server.face_detected = False
                    self.server.last_face_locations = []
                    self.server.last_face_names = []


def replace_latest(channel, value):
    try:
        channel.put_nowait(value)
    except queue.Full:
        try:
            channel.get_nowait()
        except queue.Empty:
            pass
        try:
            channel.put_nowait(value)
        except queue.Full:
            pass


def recognition_worker(frames, results, stop):
    """Keep the CPU-heavy native encoder out of the video process's GIL."""
    cv2.setNumThreads(1)
    server = SimpleNamespace(current_student=None, current_student_seen_at=0.0,
                             current_pose='none', face_detected=False,
                             last_face_locations=[], last_face_names=[], last_face_ids=[])
    pipeline = CameraPipeline(server)
    pipeline.stop = stop
    pipeline.result_queue = results

    def receive_frames():
        while not stop.is_set():
            parent = multiprocessing.parent_process()
            if parent is not None and not parent.is_alive():
                stop.set()
                break
            try:
                frame, pose_requested_at = frames.get(timeout=0.2)
                server.pose_requested_at = pose_requested_at
                with pipeline.condition:
                    pipeline.frame = frame
            except queue.Empty:
                pass

    threading.Thread(target=receive_frames, daemon=True).start()
    threading.Thread(target=pipeline.reload_faces, daemon=True).start()
    pipeline.analyze_frames()


class StreamHandler(BaseHTTPRequestHandler):
    def _send_json(self, payload, status=200):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        origin = self.headers.get("Origin", "*")
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", origin)
        self.send_header("Access-Control-Allow-Credentials", "true")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        origin = self.headers.get("Origin", "*")
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", origin)
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.send_header("Access-Control-Allow-Credentials", "true")
        self.end_headers()

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

        if self.path.startswith("/events") or self.path.startswith("/stream"):
            self.send_response(200)
            origin = self.headers.get("Origin", "*")
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Access-Control-Allow-Credentials", "true")
            self.end_headers()
            last_payload = None
            try:
                while True:
                    info = getattr(self.server, "current_student", None)
                    face_detected = getattr(self.server, "face_detected", False)
                    if FACE_RECOGNITION_AVAILABLE:
                        face_detected = len(getattr(self.server, "last_face_locations", [])) > 0
                    payload = {"student": info, "face_detected": bool(face_detected)}
                    if payload != last_payload:
                        self.wfile.write(("data: " + json.dumps(payload) + "\n\n").encode())
                        self.wfile.flush()
                        last_payload = payload
                    time.sleep(0.25)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass
            return

        if self.path.startswith("/face_pose") or self.path.startswith("/pose"):
            self.server.pose_requested_at = time.monotonic()
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

        if self.path.split("?", 1)[0] == "/snapshot":
            # Reuse the latest encoded frame; never read the camera per viewer.
            with self.server.pipeline.condition:
                payload = self.server.pipeline.jpeg
            if payload is None:
                self._send_json({"message": "Camera is warming up."}, 503)
                return
            self.send_response(200)
            self.send_header("Content-Type", "image/jpeg")
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(payload)
            return

        monitor_feed = self.path.split("?", 1)[0] == "/monitor_feed"
        if monitor_feed and not getattr(self.server, "monitor_active", False):
            self._send_json({"message": "Operation Mode is stopped."}, 409)
            return
        if self.path != "/video_feed" and not monitor_feed:
            self.send_response(404)
            self.end_headers()
            return

        self.send_response(200)
        self.send_header("Age", "0")
        self.send_header("Cache-Control", "no-cache, private")
        self.send_header("Pragma", "no-cache")
        origin = self.headers.get("Origin", "*")
        self.send_header("Access-Control-Allow-Origin", origin)
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.send_header("Access-Control-Allow-Credentials", "true")
        self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
        self.end_headers()

        sequence = -1
        # Bound the network backlog. A slow Wi-Fi viewer must not accumulate
        # seconds of old JPEGs in the socket while capture keeps moving.
        self.connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self.connection.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 65536)
        self.connection.settimeout(1.0)
        try:
            while not self.server.pipeline.stop.is_set():
                if monitor_feed and not getattr(self.server, "monitor_active", False):
                    break
                with self.server.pipeline.condition:
                    self.server.pipeline.condition.wait_for(
                        lambda: self.server.pipeline.sequence != sequence
                        or self.server.pipeline.stop.is_set(), timeout=1.0
                    )
                    if self.server.pipeline.sequence == sequence:
                        continue
                    sequence = self.server.pipeline.sequence
                    payload = self.server.pipeline.jpeg
                if payload is None:
                    continue
                self.wfile.write(
                    b"--frame\r\nContent-Type: image/jpeg\r\n"
                    + f"Content-Length: {len(payload)}\r\n\r\n".encode("ascii")
                    + payload + b"\r\n"
                )
                self.wfile.flush()
        except (OSError, TimeoutError):
            pass

    def log_message(self, format, *args):
        # Keep the console quiet.
        pass



async def websocket_handler(websocket):
    """Push face detection updates to connected clients."""
    last_payload = None
    try:
        while True:
            info = getattr(http_server, "current_student", None)
            face_detected = getattr(http_server, "face_detected", False)
            if FACE_RECOGNITION_AVAILABLE:
                face_detected = len(getattr(http_server, "last_face_locations", [])) > 0
            payload = {"student": info, "face_detected": bool(face_detected)}
            if payload != last_payload:
                await websocket.send(json.dumps(payload))
                last_payload = payload
            await asyncio.sleep(0.1)
    except websockets.exceptions.ConnectionClosed:
        pass


def start_websocket_server():
    """Run the WebSocket server in a separate thread."""
    if not WEBSOCKETS_AVAILABLE:
        print("[ws] websockets library not available, skipping WebSocket server")
        return
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    async def serve():
        async with websockets.serve(websocket_handler, HOST, WEBSOCKET_PORT):
            await asyncio.Future()  # run forever

    try:
        loop.run_until_complete(serve())
    except Exception as e:
        print(f"[ws] WebSocket server error: {e}")


def update_monitor_gate(server, active, now=None):
    """A failed status request is not an explicit Operation Mode stop."""
    now = time.monotonic() if now is None else now
    if active is True:
        server.monitor_valid_until = now + 20.0
        server.monitor_active = True
    elif active is False:
        server.monitor_valid_until = 0.0
        server.monitor_active = False
    else:
        server.monitor_active = now < getattr(server, 'monitor_valid_until', 0.0)


def poll_monitor_operation(server):
    from urllib.request import urlopen
    while not server.pipeline.stop.is_set():
        try:
            with urlopen('http://127.0.0.1:8000/api/monitor/active', timeout=3) as reply:
                update_monitor_gate(server, json.load(reply).get('active') is True)
        except Exception:
            update_monitor_gate(server, None)
        server.pipeline.stop.wait(1.0)


class CameraHTTPServer(ThreadingHTTPServer):
    # Prevent a second instance from sharing the stream port on Windows.
    allow_reuse_address = False


def main():
    try:
        camera_index, port, target_width, target_height = parse_args()
    except ValueError as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
    print(f"[camera] selected index {camera_index} (config: {CAMERA_CONFIG_PATH})")

    # Reserve the port before touching the webcam: duplicate launches must not
    # open the same USB device and disrupt the active capture.
    try:
        server = CameraHTTPServer((HOST, port), StreamHandler)
    except OSError as error:
        print(f"Camera stream port {port} is already in use: {error}. Keep only one camera stream running.", file=sys.stderr)
        sys.exit(1)
    capture, opened_index = open_camera(camera_index)
    if capture is None:
        server.server_close()
        print(f"Unable to open selected camera {camera_index}. Check public/camera.config and close other camera apps.", file=sys.stderr)
        sys.exit(1)

    # Known faces load in the background so startup does not block video.

    print(f"Streaming camera index {opened_index} on http://{HOST}:{port}/video_feed ({target_width}x{target_height})")
    if FACE_RECOGNITION_AVAILABLE:
        print("[faces] recognition enabled; registered photos are loading in the background")
    else:
        print("[faces] recognition disabled (face_recognition not installed)")

    server.camera = (capture, opened_index)
    server.target_size = (target_width, target_height)
    server.current_student = None
    server.current_student_seen_at = 0.0
    server.last_recognition_time = 0.0
    server.last_db_reload = 0.0
    server.current_pose = "none"
    server.last_pose_time = 0.0
    server.face_detected = False
    server.last_cascade_time = 0.0
    server.last_face_locations = []
    server.last_face_names = []
    server.last_face_ids = []
    global http_server
    http_server = server
    server.pipeline = CameraPipeline(server)
    server.pipeline.start()
    server.monitor_active = False
    threading.Thread(target=poll_monitor_operation, args=(server,), daemon=True).start()
    # Start WebSocket server in a separate thread.
    ws_thread = threading.Thread(target=start_websocket_server, daemon=True)
    ws_thread.start()
    if WEBSOCKETS_AVAILABLE:
        print(f"[ws] WebSocket server starting on ws://{HOST}:{WEBSOCKET_PORT}")
    try:
        server.serve_forever()
    finally:
        server.pipeline.close()
        server.server_close()


if __name__ == "__main__":
    main()
