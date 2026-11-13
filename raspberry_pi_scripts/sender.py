import serial
import time
import sys

# Update to match your OS device port:
# Windows: 'COM3', 'COM4'
# Linux: '/dev/ttyACM0' or '/dev/tty_pi_bridge'
# macOS: '/dev/tty.usbmodem*'
PORT = 'COM3'  
BAUD_RATE = 115200

def start_host_test():
    try:
        print(f"Opening port {PORT} at {BAUD_RATE} baud...")
        ser = serial.Serial(PORT, BAUD_RATE, timeout=2)
        time.sleep(2)  # Wait for serial connection initialization

        messages = [
            "PING",
            "STATUS_CHECK",
            "HELLO_FROM_PC"
            "PING",
            "STATUS_CHECK",
            "HELLO_FROM_PC"
        ]

        for msg in messages:
            print(f"\n[PC -> RPi]: Sending -> '{msg}'")
            payload = f"{msg}\n".encode('utf-8')
            
            start_time = time.time()
            ser.write(payload)
            ser.flush()

            # Read response line from Raspberry Pi
            response = ser.readline().decode('utf-8', errors='ignore').strip()
            elapsed = (time.time() - start_time) * 1000

            if response:
                print(f"[PC <- RPi]: Received -> '{response}' ({elapsed:.2f} ms)")
            else:
                print("[PC <- RPi]: ⚠️ Timeout - No response received.")

            time.sleep(1)

        ser.close()
        print("\nTest completed successfully.")

    except serial.SerialException as e:
        print(f"\n[Error] Failed to open port {PORT}: {e}")
        print("Tip: Verify port permissions (e.g., sudo usermod -a -G dialout $USER).")

if __name__ == '__main__':
    start_host_test()

