#!/usr/bin/env python3
"""Simple MJPEG camera stream server for the DRLCEFI attendance app.

Run:
    python3 scripts/camera_stream.py [camera_index] [port]

Then open http://127.0.0.1:<port>/video_feed in a browser or point an <img> tag at it.
"""
import json
import os
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import cv2

HOST = "127.0.0.1"
DEFAULT_PORT = 8090
DEFAULT_CAMERA = 0


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

    config_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "public", "camera.config")
    if os.path.isfile(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as handle:
                config = json.load(handle)
            # camera.config stores a unique id, not an OpenCV index. Fall back to 0
            # unless the id itself is numeric.
            camera_id = str(config.get("id", "")).strip()
            if camera_id.isdigit():
                return int(camera_id)
        except Exception:
            pass
    return DEFAULT_CAMERA


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
    def do_GET(self):
        if self.path in ("/", "/index.html"):
            body = b"<html><body><img src='/video_feed' style='max-width:100%'></body></html>"
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
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

        capture, _ = self.server.camera  # (capture, index)
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

    print(f"Streaming camera index {opened_index} on http://{HOST}:{port}/video_feed ({target_width}x{target_height})")

    server = ThreadingHTTPServer((HOST, port), StreamHandler)
    server.camera = (capture, opened_index)
    server.target_size = (target_width, target_height)
    try:
        server.serve_forever()
    finally:
        capture.release()
        server.server_close()


if __name__ == "__main__":
    main()
