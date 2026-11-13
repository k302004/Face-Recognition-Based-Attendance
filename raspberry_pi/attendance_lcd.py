"""16x2 attendance confirmations for the Raspberry Pi I2C LCD."""
import time
import unicodedata


def initialize_lcd(config):
    if config.get('lcd_enabled', True) is False:
        return None
    try:
        from RPLCD.i2c import CharLCD
        address = config.get('lcd_address', '0x27')
        address = int(address, 0) if isinstance(address, str) else int(address)
        lcd = CharLCD('PCF8574', address, port=int(config.get('lcd_i2c_bus', 1)), cols=16, rows=2)
        show_idle(lcd)
        print(f'[LCD] Ready at {hex(address)}')
        return lcd
    except Exception as error:
        print(f'[LCD] Unavailable: {error}')
        return None


def show_idle(lcd):
    if lcd is None:
        return
    try:
        lcd.clear()
        lcd.write_string('Attendance Ready')
        lcd.cursor_pos = (1, 0)
        lcd.write_string('Scan your face')
    except Exception as error:
        print(f'[LCD] Idle display failed: {error}')


def show_attendance(lcd, name, action, config):
    """Flash the recorded action and scroll names longer than one LCD row."""
    if lcd is None or action not in ('time_in', 'time_out'):
        return False
    name = unicodedata.normalize('NFKD', str(name)).encode('ascii', 'ignore').decode()
    name = ' '.join(name.split()) or 'Student'
    label = 'IN: Recorded' if action == 'time_in' else 'OUT: Recorded'
    try:
        lcd.clear()
        lcd.write_string(name[:16].ljust(16))
        for _ in range(2):
            lcd.cursor_pos = (1, 0)
            lcd.write_string(label.ljust(16))
            time.sleep(0.35)
            lcd.cursor_pos = (1, 0)
            lcd.write_string(' ' * 16)
            time.sleep(0.15)
        lcd.cursor_pos = (1, 0)
        lcd.write_string(label.ljust(16))
        for offset in range(1, max(1, len(name) - 15)):
            lcd.cursor_pos = (0, 0)
            lcd.write_string(name[offset:offset + 16].ljust(16))
            time.sleep(0.2)
        time.sleep(max(0.0, min(10.0, float(config.get('lcd_hold_seconds', 2)))))
        return True
    except Exception as error:
        print(f'[LCD] Attendance display failed: {error}')
        return False
