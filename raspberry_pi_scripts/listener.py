import serial
import time

# UART2 on Raspberry Pi (Pins 27 & 28)
PI_UART_PORT = '/dev/ttyAMA1'
BAUD_RATE = 115200

def start_pi_listener():
    try:
        print(f"Starting Pi UART listener on {PI_UART_PORT}...")
        ser = serial.Serial(PI_UART_PORT, BAUD_RATE, timeout=1)
        time.sleep(1)
        print("Waiting for messages from PC...\n")

        while True:
            if ser.in_waiting > 0:
                raw_line = ser.readline().decode('utf-8', errors='ignore').strip()
                
                if raw_line:
                    print(f"[RPi Received]: '{raw_line}'")
                    
                    # Process request & construct payload back to PC
                    reply = f"ACK: {raw_line} (Pi OK)"
                    ser.write(f"{reply}\n".encode('utf-8'))
                    ser.flush()
                    print(f"[RPi Sent]: '{reply}'")

            time.sleep(0.01)

    except serial.SerialException as e:
        print(f"\n[Error] Unable to access {PI_UART_PORT}: {e}")
        print("Tip: Run with 'sudo' or add user to dialout group: sudo usermod -a -G dialout $USER")
    except KeyboardInterrupt:
        print("\nExiting listener.")
        ser.close()

if __name__ == '__main__':
    start_pi_listener()
