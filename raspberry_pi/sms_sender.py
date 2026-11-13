#!/usr/bin/env python3
"""Listen for SMS requests from the PC over the serial link and send them
through the Pi's SIM7600 modem using PDU mode (supports concatenated SMS).

Run on the Raspberry Pi:
    python3 sms_sender.py
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path
from attendance_lcd import initialize_lcd as create_attendance_lcd, show_attendance

# Prefer the project virtualenv so RPLCD/pyserial/gsmmodem are importable.
def _venv_python():
    if os.name == "nt":
        rel = Path("Scripts") / "python.exe"
    else:
        rel = Path("bin") / "python"
    candidates = [
        Path(__file__).resolve().parent / ".venv" / rel,        # raspberry_pi/.venv
        Path(__file__).resolve().parents[1] / ".venv" / rel,   # project root
        Path.cwd() / ".venv" / rel,
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None

_venv = _venv_python()
if __name__ == "__main__" and _venv is not None and Path(sys.prefix).absolute() != _venv.parent.parent.absolute():
    os.execv(str(_venv), [str(_venv), *sys.argv])

try:
    import serial
except ImportError:
    print("pyserial is not installed. Install with: pip install pyserial", file=sys.stderr)
    raise SystemExit(1)

try:
    from gsmmodem.pdu import encodeSmsSubmitPdu
except ImportError:
    encodeSmsSubmitPdu = None

try:
    from RPLCD.i2c import CharLCD
except ImportError:
    CharLCD = None

ROOT = Path(__file__).resolve().parent
MODEM = None


def load_config():
    config_path = ROOT / "config.json"
    if not config_path.is_file():
        print("Missing config.json; SMS modem settings unavailable. Continuing with defaults.",
              file=sys.stderr)
        return {}
    try:
        with config_path.open(encoding="utf-8") as config_file:
            return json.load(config_file)
    except (OSError, ValueError) as error:
        print(f"Could not read config.json: {error}", file=sys.stderr)
        return {}


def initialize_lcd(config=None):
    return create_attendance_lcd(config or {})


def reset_lcd_idle(lcd):
    if lcd is None:
        return
    try:
        lcd.clear()
        lcd.write_string("Attendance Ready")
        lcd.cursor_pos = (1, 0)
        lcd.write_string("Scan your face")
    except Exception as error:
        print(f"[LCD] Display reset failed: {error}")


def show_lcd_status(lcd, line1, line2=""):
    if lcd is None:
        return
    try:
        lcd.clear()
        lcd.write_string(str(line1)[:16])
        if line2:
            lcd.cursor_pos = (1, 0)
            lcd.write_string(str(line2)[:16])
    except Exception as error:
        print(f"[LCD] Display update failed: {error}")


def extract_pdu_hex(pdu):
    """Safely extract Hex representation of PDU object across gsmmodem versions."""
    # 1. Direct hex string properties/methods provided by gsmmodem-new
    if hasattr(pdu, "toHex"):
        res = pdu.toHex()
        return res.upper() if isinstance(res, str) else res.hex().upper()
    if hasattr(pdu, "hex"):
        return pdu.hex.upper() if isinstance(pdu.hex, str) else pdu.hex().upper()

    # 2. Extract internal raw PDU bytearray/list if available
    if hasattr(pdu, "pdu"):
        return bytes(pdu.pdu).hex().upper()
    if hasattr(pdu, "data"):
        return bytes(pdu.data).hex().upper()

    # 3. Standard bytes fallback
    try:
        return bytes(pdu).hex().upper()
    except TypeError:
        # 4. Fallback: inspect object attributes for string hex representation
        return str(pdu).upper()


def init_modem(config):
    """Open and initialize the SIM7600 modem once at startup (PDU mode)."""
    global MODEM
    port = config.get("sms_port", "/dev/ttyAMA0")
    baud = config.get("sms_baud", 115200)
    try:
        modem = serial.Serial(port, baud, timeout=5, rtscts=False, dsrdtr=False)
    except Exception as error:
        print(f"[MODEM] could not open {port}: {error}")
        MODEM = None
        return None

    modem.reset_input_buffer()

    # Wait for the modem to finish booting
    boot_buf = ""
    deadline = time.time() + 10
    while time.time() < deadline:
        if modem.in_waiting:
            boot_buf += modem.read(modem.in_waiting).decode("utf-8", errors="ignore")
            if any(k in boot_buf for k in ("SMS DONE", "PB DONE", "READY")):
                break
        time.sleep(0.2)
    print(f"[MODEM] boot -> {boot_buf.strip()!r}")

    # Reset modem command echoes and verify AT sync
    for _ in range(5):
        modem.reset_input_buffer()
        modem.write(b"ATE0\r")  # Turn off echo
        time.sleep(0.5)
        resp = modem.read(modem.in_waiting or 0).decode("utf-8", errors="ignore")
        if "OK" in resp:
            break
        time.sleep(0.5)

    # Set PDU mode (AT+CMGF=0)
    modem.write(b"AT+CMGF=0\r")
    time.sleep(0.5)
    mode_resp = modem.read(modem.in_waiting or 0).decode("utf-8", errors="ignore")
    print(f"[MODEM] CMGF=0 -> {mode_resp.strip()!r}")

    MODEM = modem
    print("[MODEM] initialized and ready (PDU mode)")
    return modem


def send_sms(config, recipient, message):
    if encodeSmsSubmitPdu is None:
        return False, "python-gsmmodem-new is not installed"
    if not recipient:
        print("SMS skipped: no recipient phone number")
        return False, "no_recipient"
    if not message:
        print("SMS skipped: empty message")
        return False, "empty_message"

    global MODEM
    if MODEM is None:
        init_modem(config)
    if MODEM is None:
        return False, "modem not initialized"

    modem = MODEM
    try:
        # Encode into one or more PDU segments (concatenated if needed)
        pdus = encodeSmsSubmitPdu(recipient, message)
        print(f"[SMS] {len(pdus)} segment(s) to send")

        for idx, pdu in enumerate(pdus, start=1):
            pdu_hex = extract_pdu_hex(pdu)
            tpdu_length = pdu.tpduLength
            print(f"[SMS] segment {idx}/{len(pdus)} tpdu_length={tpdu_length}")

            for attempt in range(1, 4):
                modem.reset_input_buffer()
                modem.write(f"AT+CMGS={tpdu_length}\r".encode())
                
                # Wait for '>' prompt
                deadline = time.time() + 5
                prompt_buf = ""
                while time.time() < deadline:
                    if modem.in_waiting:
                        prompt_buf += modem.read(modem.in_waiting).decode("utf-8", errors="ignore")
                        if ">" in prompt_buf:
                            break
                    time.sleep(0.1)

                if ">" not in prompt_buf:
                    print(f"[SMS] no prompt on attempt {attempt}: {prompt_buf.strip()!r}")
                    modem.write(b"\x1b")  # Send ESC to cancel stalled command
                    time.sleep(1)
                    continue

                # Write payload hex followed by Ctrl+Z (0x1A)
                modem.write((pdu_hex + "\x1a").encode())
                final_resp = ""
                deadline = time.time() + 15
                while time.time() < deadline:
                    if modem.in_waiting:
                        final_resp += modem.read(modem.in_waiting).decode("utf-8", errors="ignore")
                        if any(k in final_resp for k in ("OK", "+CMGS:", "ERROR", "+CMS ERROR")):
                            break
                    time.sleep(0.3)
                print(f"[MODEM] segment {idx} final -> {final_resp.strip()!r}")

                if "OK" in final_resp or "+CMGS" in final_resp:
                    break
                
                print(f"[SMS] segment {idx} failed on attempt {attempt}, retrying...")
                time.sleep(2)
            else:
                return False, f"segment {idx} failed"

        print(f"SMS sent successfully to {recipient}")
        return True, "sent"

    except Exception as error:
        print(f"[SMS] Failed to send: {error}")
        try:
            modem.close()
        except Exception:
            pass
        MODEM = None
        return False, str(error)


def handle_payload(payload, lcd, config):
    phone = payload.get("phone") or payload.get("phoneNumber") or payload.get("recipient")
    message = payload.get("message")
    name = payload.get("name") or payload.get("userName") or payload.get("studentName")

    print(f"[RPi] Payload received: phone={phone}, name={name}")

    action = payload.get('action')
    attendance = action in ('time_in', 'time_out')
    displayed = show_attendance(lcd, name or payload.get('student_id', 'Student'), action, config) if attendance else False
    wants_sms = payload.get('send_sms', True) is not False
    if wants_sms:
        if not attendance:
            show_lcd_status(lcd, 'Sending SMS...', name or '')
        sent, reason = send_sms(config, phone, message)
        if not attendance:
            show_lcd_status(lcd, 'SMS Sent OK!' if sent else 'SMS Failed!', name or reason[:16])
            time.sleep(1.5)
    else:
        sent, reason = False, 'not_requested'
    reset_lcd_idle(lcd)
    return {
        'status': 'ok' if sent or not wants_sms else 'failed',
        'event_id': payload.get('event_id'),
        'attendance_received': attendance,
        'displayed': displayed,
        'name': name,
        'phone': phone,
        'sent': sent,
        'reason': reason,
    }

def main():
    parser = argparse.ArgumentParser(description="Listen for SMS payloads from PC and send via SIM7600 (PDU mode).")
    parser.add_argument("--port", default="/dev/ttyAMA1", help="Serial port connected to PC")
    parser.add_argument("--baud", type=int, default=115200, help="Baud rate")
    parser.add_argument("--test-lcd", choices=['time_in', 'time_out'], help="Test only the LCD; no SMS or serial connection")
    parser.add_argument("--name", default='Test Student', help="Name for --test-lcd")
    args = parser.parse_args()

    config = load_config()
    lcd = initialize_lcd(config)
    if args.test_lcd:
        if lcd is None:
            raise SystemExit('LCD is unavailable. Check I2C, lcd_address, and RPLCD dependencies.')
        show_attendance(lcd, args.name, args.test_lcd, config)
        reset_lcd_idle(lcd)
        return
    # Initialize the modem only when SMS is requested; LCD-only events need no modem.

    print(f"Starting Pi serial listener on {args.port} at {args.baud} baud...")
    try:
        ser = serial.Serial(args.port, args.baud, timeout=2, rtscts=False, dsrdtr=False, xonxoff=False)
    except serial.SerialException as error:
        print(f"\n[Error] Unable to open {args.port}: {error}", file=sys.stderr)
        print("Tip: run with sudo or add user to dialout group.", file=sys.stderr)
        raise SystemExit(1)

    time.sleep(1)
    print("Waiting for payloads from PC...\n")

    rx_buf = ""
    try:
        while True:
            if ser.in_waiting:
                chunk = ser.read(ser.in_waiting).decode("utf-8", errors="ignore")
                rx_buf += chunk

                # Process complete JSON objects or newline-terminated strings
                while True:
                    raw_line = None
                    if "\n" in rx_buf:
                        raw_line, _, rx_buf = rx_buf.partition("\n")
                    elif "{" in rx_buf and "}" in rx_buf:
                        start = rx_buf.find("{")
                        end = rx_buf.rfind("}") + 1
                        candidate = rx_buf[start:end]
                        try:
                            json.loads(candidate)
                        except (json.JSONDecodeError, ValueError):
                            break
                        raw_line = candidate
                        rx_buf = rx_buf[end:]
                    else:
                        break
                    if raw_line is None:
                        break

                    raw_line = raw_line.strip()
                    if not raw_line:
                        continue

                    print(f"[RPi Received]: '{raw_line}'")

                    payload = None
                    try:
                        payload = json.loads(raw_line)
                    except json.JSONDecodeError as err:
                        print(f"[RPi] Malformed JSON received ({err}). Raw line: '{raw_line}'")

                    if payload and isinstance(payload, dict):
                        result = handle_payload(payload, lcd, config)
                    else:
                        result = {
                            "status": "failed",
                            "name": None,
                            "phone": None,
                            "sent": False,
                            "reason": "invalid_json_format"
                        }

                    # Package and send response back to PC over serial link
                    reply_str = json.dumps(result) + "\n"
                    reply_bytes = reply_str.encode("utf-8")

                    # Chunked write to prevent buffer overflow on ESP32 bridge
                    chunk_size = 16
                    for i in range(0, len(reply_bytes), chunk_size):
                        ser.write(reply_bytes[i:i + chunk_size])
                        ser.flush()
                        time.sleep(0.005)

                    print(f"[RPi Sent]: '{reply_str.strip()}'")

            time.sleep(0.001)

    except KeyboardInterrupt:
        print("\nExiting listener.")
    finally:
        if MODEM is not None:
            try:
                MODEM.close()
            except Exception:
                pass
        ser.close()
        if lcd is not None:
            try:
                lcd.clear()
                lcd.write_string("SMS Sender Off")
            except Exception:
                pass


if __name__ == "__main__":
    main()
