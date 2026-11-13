#!/usr/bin/env python3
"""Bridge between the Laravel app and the Raspberry Pi SMS sender.

Two modes:

1. One-shot CLI (testing):
       python scripts/send_to_pi.py --phone "+639..." --message "..." --name "..."
   or pipe JSON on stdin.

2. HTTP service (used by Laravel, which runs in a container without serial access):
       python scripts/send_to_pi.py --serve --http-port 8092 --serial-port /dev/cu.usbmodem101
   Then Laravel POSTs JSON {"phone","message","name"} to http://<host>:8092/send-sms
   and this process forwards it to the Pi over the serial link.
"""

import argparse
import json
import os
import sys
import threading
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

# Make sure we run inside a project virtualenv when one is available.
def _venv_python():
    if os.name == "nt":
        rel = Path("Scripts") / "python.exe"
    else:
        rel = Path("bin") / "python"
    candidates = [
        Path(__file__).resolve().parents[1] / ".venv" / rel,
        Path(__file__).resolve().parent / ".venv" / rel,
        Path.cwd() / ".venv" / rel,
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None

_venv = _venv_python()
if _venv is not None and Path(sys.executable).resolve() != _venv.resolve():
    os.execv(str(_venv), [str(_venv), *sys.argv])

try:
    import serial
except ImportError:
    print("pyserial is not installed. Install with: pip install pyserial", file=sys.stderr)
    raise SystemExit(1)

DEFAULT_SERIAL_PORT = "/dev/cu.usbmodem101"
DEFAULT_BAUD = 115200
DEFAULT_HTTP_PORT = 8092
SERIAL_LOCK = threading.Lock()


def send_to_serial(serial_port, baud, payload, timeout=5):
    """Send one payload to the Pi over serial and return the ACK string."""
    if not payload.get("phone"):
        raise ValueError("Missing phone number in payload")
    if not payload.get("message"):
        raise ValueError("Missing message in payload")

    with SERIAL_LOCK:
        # Opening the port can hang indefinitely on some platforms if the
        # device is busy or not ready, so do it in a thread with a timeout.
        result = {"ser": None, "error": None}
        def _open():
            try:
                result["ser"] = serial.Serial(serial_port, baud, timeout=2, write_timeout=2, rtscts=False, dsrdtr=False, xonxoff=False)
            except Exception as exc:  # pragma: no cover - depends on hardware
                result["error"] = exc
        opener = threading.Thread(target=_open, daemon=True)
        opener.start()
        opener.join(8)
        if opener.is_alive():
            raise TimeoutError(f"Timed out opening serial port {serial_port}")
        if result["error"] is not None:
            raise result["error"]
        ser = result["ser"]
        time.sleep(2)
        line = (json.dumps(payload) + "\n").encode("utf-8")
        for i in range(0, len(line), 4):
            ser.write(line[i:i + 4])
            ser.flush()
            time.sleep(0.005)
        time.sleep(0.2)

        ack_buf = b""
        deadline = time.time() + (timeout or 5)
        while time.time() < deadline:
            if ser.in_waiting:
                ack_buf += ser.read(ser.in_waiting)
                if b"\n" in ack_buf:
                    break
            time.sleep(0.01)
        response = ack_buf.split(b"\n", 1)[0].decode("utf-8", errors="ignore").strip()

        try:
            log_path = Path(__file__).resolve().parents[1] / "storage" / "logs" / "pi-sms.log"
            log_path.parent.mkdir(parents=True, exist_ok=True)
            with log_path.open("a", encoding="utf-8") as lf:
                lf.write(f"{datetime.now().isoformat()} payload={json.dumps(payload)} ack={response}\n")
        except Exception:
            pass

        ser.close()
        return response


def build_payload(args):
    if not sys.stdin.isatty():
        try:
            data = json.load(sys.stdin)
            if isinstance(data, dict):
                return {
                    "phone": data.get("phone") or data.get("phoneNumber") or data.get("recipient"),
                    "message": data.get("message"),
                    "name": data.get("name") or data.get("userName"),
                }
        except (json.JSONDecodeError, ValueError):
            pass
    return {
        "phone": args.phone,
        "message": args.message,
        "name": args.name,
    }


class SmsHandler(BaseHTTPRequestHandler):
    serial_port = DEFAULT_SERIAL_PORT
    baud = DEFAULT_BAUD

    def _send_json(self, status, obj):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if self.path not in ("/send", "/send-sms", "/api/send-sms"):
            self._send_json(404, {"error": "not found"})
            return
        try:
            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length) if length else b""
            payload = json.loads(raw.decode("utf-8")) if raw else {}
        except Exception as e:
            self._send_json(400, {"error": str(e)})
            return
        if not isinstance(payload, dict):
            self._send_json(400, {"error": "payload must be a JSON object"})
            return
        try:
            ack = send_to_serial(self.serial_port, self.baud, payload)
            self._send_json(200, {"ok": True, "ack": ack})
        except Exception as e:
            self._send_json(500, {"ok": False, "error": str(e)})

    def do_GET(self):
        if self.path in ("/", "/health"):
            self._send_json(200, {"status": "ok"})
        else:
            self._send_json(404, {"error": "not found"})

    def log_message(self, *args):
        # keep console output concise
        sys.stderr.write("%s - %s\n" % (self.address_string(), args[0]))


def serve(http_port, serial_port, baud):
    SmsHandler.serial_port = serial_port
    SmsHandler.baud = baud
    httpd = ThreadingHTTPServer(("0.0.0.0", http_port), SmsHandler)
    print(f"SMS bridge listening on http://0.0.0.0:{http_port}")
    print(f"Forwarding to Pi via {serial_port} @ {baud}")
    print("Endpoints: POST /send-sms  {\"phone\",\"message\",\"name\"}, GET /health")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
        httpd.server_close()


def main():
    parser = argparse.ArgumentParser(description="Bridge between Laravel and the Pi SMS sender.")
    parser.add_argument("--serve", action="store_true", help="Run as an HTTP service")
    parser.add_argument("--http-port", type=int, default=DEFAULT_HTTP_PORT, help="HTTP listen port")
    parser.add_argument("--serial-port", default=DEFAULT_SERIAL_PORT, help="Serial port to the Pi")
    parser.add_argument("--baud", type=int, default=DEFAULT_BAUD, help="Baud rate")
    parser.add_argument("--port", default=DEFAULT_SERIAL_PORT, help="Serial port (one-shot mode)")
    parser.add_argument("--timeout", type=int, default=5, help="Response timeout (seconds)")
    parser.add_argument("--phone", help="Recipient phone number (one-shot mode)")
    parser.add_argument("--message", help="SMS message body (one-shot mode)")
    parser.add_argument("--name", help="User/student name (one-shot mode)")
    args = parser.parse_args()

    if args.serve:
        serve(args.http_port, args.serial_port or args.port, args.baud)
        return

    # one-shot mode
    payload = build_payload(args)
    try:
        ack = send_to_serial(args.serial_port or args.port, args.baud, payload, args.timeout)
        print(f"[PC <- RPi]: Received -> '{ack}'")
    except Exception as error:
        print(f"\n[Error] {error}", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
