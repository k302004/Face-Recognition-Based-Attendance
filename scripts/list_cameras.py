#!/usr/bin/env python3
import json
import os
import platform
import subprocess
import sys


def detect_macos():
    cameras = []
    try:
        result = subprocess.run(
            ["system_profiler", "SPCameraDataType", "-json"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if result.returncode == 0 and result.stdout.strip():
            data = json.loads(result.stdout)
            for item in data.get("SPCameraDataType", []):
                name = item.get("_name") or item.get("model_id") or "Unknown Camera"
                cameras.append({
                    "id": item.get("spcamera_unique-id") or item.get("_name") or name,
                    "name": name,
                    "modelId": item.get("spcamera_model-id"),
                    "uniqueId": item.get("spcamera_unique-id"),
                })
    except Exception as error:
        pass

    # Fallback: parse the plain text output if JSON parsing failed.
    if not cameras:
        try:
            result = subprocess.run(
                ["system_profiler", "SPCameraDataType"],
                capture_output=True,
                text=True,
                timeout=15,
            )
            current = None
            for line in result.stdout.splitlines():
                stripped = line.strip()
                if stripped and not stripped.endswith(":") and ":" not in stripped and current is None:
                    # Heuristic: top-level camera names appear without a colon.
                    pass
            # Simpler heuristic: lines that end with "Camera" or contain "Camera".
            for line in result.stdout.splitlines():
                stripped = line.strip().rstrip(":")
                if stripped and "Camera" in stripped and not stripped.startswith("Model") and not stripped.startswith("Unique"):
                    if stripped not in [c["name"] for c in cameras]:
                        cameras.append({"id": stripped, "name": stripped, "modelId": None, "uniqueId": None})
        except Exception:
            pass

    return cameras


def detect_linux():
    cameras = []
    # Try OpenCV if available.
    try:
        import cv2  # type: ignore

        for index in range(10):
            capture = cv2.VideoCapture(index)
            if capture.isOpened():
                cameras.append({
                    "id": str(index),
                    "name": f"Camera {index}",
                    "modelId": None,
                    "uniqueId": None,
                })
                capture.release()
        if cameras:
            return cameras
    except Exception:
        pass

    # Fall back to /dev/video* entries.
    try:
        for entry in sorted(os.listdir("/dev")):
            if entry.startswith("video"):
                cameras.append({
                    "id": "/dev/" + entry,
                    "name": entry,
                    "modelId": None,
                    "uniqueId": None,
                })
    except Exception:
        pass

    return cameras


def detect_windows():
    cameras = []
    # Prefer DirectShow backend on Windows for reliable device enumeration.
    try:
        import cv2  # type: ignore

        backends = []
        if hasattr(cv2, "CAP_DSHOW"):
            backends.append(cv2.CAP_DSHOW)
        backends.append(0)  # default

        seen = set()
        for backend in backends:
            for index in range(10):
                try:
                    if backend == 0:
                        capture = cv2.VideoCapture(index)
                    else:
                        capture = cv2.VideoCapture(index, backend)
                except Exception:
                    continue
                if capture is not None and capture.isOpened():
                    # Try to read a frame to confirm the device is usable.
                    ok, _ = capture.read()
                    if ok and str(index) not in seen:
                        seen.add(str(index))
                        cameras.append({
                            "id": str(index),
                            "name": f"Camera {index}",
                            "modelId": None,
                            "uniqueId": None,
                        })
                    capture.release()
            if cameras:
                return cameras
    except Exception:
        pass

    # Fall back to PowerShell device enumeration (best effort, names only).
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-PnpDevice -Class Camera -Status OK | Select-Object -ExpandProperty FriendlyName"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if result.returncode == 0:
            for line in result.stdout.splitlines():
                name = line.strip()
                if name:
                    cameras.append({
                        "id": name,
                        "name": name,
                        "modelId": None,
                        "uniqueId": None,
                    })
    except Exception:
        pass

    return cameras


def main():
    system = platform.system().lower()
    if system == "darwin":
        cameras = detect_macos()
    elif system == "linux":
        cameras = detect_linux()
    elif system == "windows":
        cameras = detect_windows()
    else:
        # Generic fallback: probe indices with OpenCV.
        cameras = detect_linux()

    print(json.dumps({"cameras": cameras}, ensure_ascii=False))


if __name__ == "__main__":
    main()
