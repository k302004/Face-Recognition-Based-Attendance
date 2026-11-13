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
import queue
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
if __name__ == "__main__" and _venv is not None and Path(sys.executable).resolve() != _venv.resolve():
    os.execv(str(_venv), [str(_venv), *sys.argv])

try:
    import serial
except ImportError:
    print("pyserial is not installed. Install with: pip install pyserial", file=sys.stderr)
    raise SystemExit(1)

DEFAULT_SERIAL_PORT = "COM4"
DEFAULT_BAUD = 115200
DEFAULT_HTTP_PORT = 8092
SERIAL_LOCK = threading.Lock()
SERIAL_CONNECTION = None
SMS_QUEUE = queue.Queue(maxsize=100)


def read_sms_ack(ser, payload, timeout):
    """Ignore boot/debug lines and wait for a matching delivery result."""
    pending = b""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        available = ser.in_waiting
        if not available:
            time.sleep(0.01)
            continue
        pending += ser.read(available)
        while b"\n" in pending:
            line, pending = pending.split(b"\n", 1)
            try:
                ack = json.loads(line.decode("utf-8", errors="ignore").strip())
            except (json.JSONDecodeError, ValueError):
                continue
            if not isinstance(ack, dict):
                continue
            if payload.get("event_id") and ack.get("event_id") != payload["event_id"]:
                continue
            if payload.get("send_sms") is False and ack.get("attendance_received") is True:
                return json.dumps(ack)
            if "sent" not in ack or ack.get("phone") != payload.get("phone"):
                continue
            if ack.get("sent") is not True:
                raise RuntimeError(f"SMS delivery failed: {ack.get('reason', 'unknown')}")
            return json.dumps(ack)
    raise TimeoutError("No matching SMS delivery acknowledgment received")


def send_to_serial(serial_port, baud, payload, timeout=60):
    global SERIAL_CONNECTION
    display_only = payload.get("send_sms") is False and payload.get("action") in ("time_in", "time_out") and bool(payload.get("name"))
    if not display_only and (not payload.get("phone") or not payload.get("message")):
        raise ValueError("Missing phone number or message")
    with SERIAL_LOCK:
        try:
            # Reopening the serial port resets some USB bridges. Keep it open
            # between messages so time-in and time-out use the same connection.
            if SERIAL_CONNECTION is None or not SERIAL_CONNECTION.is_open:
                SERIAL_CONNECTION = serial.Serial(
                    serial_port, baud, timeout=2, write_timeout=2,
                    rtscts=False, dsrdtr=False, xonxoff=False,
                )
                time.sleep(2)
                SERIAL_CONNECTION.reset_input_buffer()
            ser = SERIAL_CONNECTION
            line = (json.dumps(payload) + "\n").encode("utf-8")
            for i in range(0, len(line), 4):
                ser.write(line[i:i + 4])
                ser.flush()
                time.sleep(0.005)
            response = read_sms_ack(ser, payload, timeout)
            log_sms(payload, response)
            return response
        except Exception:
            if SERIAL_CONNECTION is not None:
                SERIAL_CONNECTION.close()
                SERIAL_CONNECTION = None
            raise


def log_sms(payload, result):
    log_path = Path(__file__).resolve().parents[1] / "storage/logs/pi-sms.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(f"{datetime.now().isoformat()} payload={json.dumps(payload)} result={result}\n")


def sms_worker(serial_port, baud):
    while True:
        payload = SMS_QUEUE.get()
        try:
            send_to_serial(serial_port, baud, payload)
        except Exception as error:
            log_sms(payload, f"FAILED: {error}")
        finally:
            SMS_QUEUE.task_done()

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
        display_only = payload.get("send_sms") is False and payload.get("action") in ("time_in", "time_out") and bool(payload.get("name"))
        if not display_only and (not payload.get("phone") or not payload.get("message")):
            self._send_json(400, {"ok": False, "error": "phone and message are required"})
            return
        try:
            SMS_QUEUE.put_nowait(payload)
            self._send_json(202, {"ok": True, "state": "queued"})
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
    threading.Thread(target=sms_worker, args=(serial_port, baud), daemon=True).start()
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
    parser.add_argument("--timeout", type=int, default=60, help="Response timeout (seconds)")
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
