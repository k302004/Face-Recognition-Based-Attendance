import importlib.util
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1] / 'raspberry_pi'
spec = importlib.util.spec_from_file_location('attendance_lcd', ROOT / 'attendance_lcd.py')
display = importlib.util.module_from_spec(spec)
spec.loader.exec_module(display)
spec = importlib.util.spec_from_file_location('pi_sms_sender', ROOT / 'sms_sender.py')
sender = importlib.util.module_from_spec(spec)
with patch.dict(sys.modules, {'attendance_lcd': display}):
    spec.loader.exec_module(sender)


class FakeLCD:
    def __init__(self):
        self.cursor_pos = (0, 0)
        self.writes = []

    def clear(self):
        self.cursor_pos = (0, 0)

    def write_string(self, text):
        self.writes.append((self.cursor_pos, text))


class LcdTests(unittest.TestCase):
    def test_lcd_test_command_does_not_open_serial_or_send_sms(self):
        with patch.object(sender.sys, 'argv', ['sms_sender.py', '--test-lcd', 'time_in', '--name', 'Test Student']), \
                patch.object(sender, 'load_config', return_value={}), \
                patch.object(sender, 'initialize_lcd', return_value=FakeLCD()), \
                patch.object(sender, 'show_attendance', return_value=True) as show, \
                patch.object(sender, 'reset_lcd_idle'), \
                patch.object(sender.serial, 'Serial') as serial, \
                patch.object(sender, 'send_sms') as sms:
            sender.main()
        show.assert_called_once()
        serial.assert_not_called()
        sms.assert_not_called()

    def test_time_in_and_out_flash_recorded_and_scroll_full_name(self):
        for action, label in [('time_in', 'IN: Recorded'), ('time_out', 'OUT: Recorded')]:
            lcd = FakeLCD()
            name = 'A Student With A Long Name'
            with patch.object(display.time, 'sleep'):
                self.assertTrue(display.show_attendance(lcd, name, action, {}))
            self.assertIn(((1, 0), label.ljust(16)), lcd.writes)
            self.assertIn(((1, 0), ' ' * 16), lcd.writes)
            self.assertIn(((0, 0), name[-16:]), lcd.writes)
            self.assertTrue(all(len(text) == 16 for _, text in lcd.writes))

    def test_attendance_displays_before_sms_and_display_only_skips_sms(self):
        for wants_sms in (True, False):
            order = []
            payload = {'event_id': 'test-event', 'action': 'time_out', 'name': 'Test Student',
                       'phone': '+639000000000', 'message': 'Test', 'send_sms': wants_sms}
            with patch.object(sender, 'show_attendance', side_effect=lambda *args: order.append('lcd') or True), \
                    patch.object(sender, 'send_sms', side_effect=lambda *args: (order.append('sms') or True, 'sent')), \
                    patch.object(sender, 'reset_lcd_idle'):
                result = sender.handle_payload(payload, FakeLCD(), {})
            self.assertEqual(order, ['lcd', 'sms'] if wants_sms else ['lcd'])
            self.assertTrue(result['attendance_received'])
            self.assertEqual(result['event_id'], 'test-event')
            self.assertTrue(result['displayed'])


if __name__ == '__main__':
    unittest.main()
