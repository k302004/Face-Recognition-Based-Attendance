"""Offline SMS protocol tests; no messages are sent."""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location(
    'sms_bridge', Path(__file__).resolve().parents[1] / 'scripts/send_to_pi.py'
)
bridge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bridge)


class SerialInput:
    def __init__(self, data):
        self.data = data

    @property
    def in_waiting(self):
        return len(self.data)

    def read(self, size):
        data, self.data = self.data[:size], self.data[size:]
        return data


class SmsTests(unittest.TestCase):
    def test_display_only_ack_matches_the_attendance_event(self):
        data = json.dumps({'event_id': 'old', 'attendance_received': True}).encode() + b'\n'
        data += json.dumps({'event_id': 'new', 'attendance_received': True, 'displayed': True}).encode() + b'\n'
        ack = bridge.read_sms_ack(SerialInput(data), {'event_id': 'new', 'send_sms': False}, 1)
        self.assertTrue(json.loads(ack)['displayed'])

    def test_boot_output_and_other_recipient_are_not_delivery_confirmations(self):
        data = b'load:0x403ce710,len:0x2f9c\n'
        data += json.dumps({'phone': '+63000', 'sent': True}).encode() + b'\n'
        data += json.dumps({'phone': '+63999', 'sent': True}).encode() + b'\n'
        ack = bridge.read_sms_ack(SerialInput(data), {'phone': '+63999'}, 1)
        self.assertEqual(json.loads(ack)['phone'], '+63999')

    def test_boot_output_alone_times_out(self):
        with self.assertRaises(TimeoutError):
            bridge.read_sms_ack(SerialInput(b'booting\n'), {'phone': '+63999'}, 0.02)

    def test_delivery_failure_is_not_success(self):
        data = json.dumps({'phone': '+63999', 'sent': False, 'reason': 'modem_error'}).encode() + b'\n'
        with self.assertRaisesRegex(RuntimeError, 'modem_error'):
            bridge.read_sms_ack(SerialInput(data), {'phone': '+63999'}, 1)

    def test_serial_connection_is_reused_for_time_in_then_time_out(self):
        writes = []
        serial = SimpleNamespace(is_open=True, write=writes.append, flush=lambda: None)
        with patch.object(bridge, 'SERIAL_CONNECTION', serial), \
                patch.object(bridge, 'read_sms_ack', return_value='confirmed'), \
                patch.object(bridge, 'log_sms'), patch.object(bridge.time, 'sleep'):
            for message in ('time_in', 'time_out'):
                bridge.send_to_serial('COM_TEST', 115200, {'phone': '+63999', 'message': message})
        lines = b''.join(writes).decode().splitlines()
        self.assertEqual([json.loads(line)['message'] for line in lines], ['time_in', 'time_out'])


if __name__ == '__main__':
    unittest.main()
