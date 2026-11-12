import serial
import time

# Replace 'COM3' with your laptop's port (e.g., '/dev/ttyACM0' on Linux/Mac)
PORT = 'COM3' 
BAUD_RATE = 9600

ser = serial.Serial(PORT, BAUD_RATE, timeout=1)
time.sleep(2)  # Wait for connection initialization

print("Connected to Raspberry Pi via USB!")

try:
    for i in range(5):
        msg = f"Hello Pi packet #{i}\n"
        print(f"Sending: {msg.strip()}")
        
        # Send data to Pi
        ser.write(msg.encode('utf-8'))
        
        # Read response from Pi
        response = ser.readline().decode('utf-8').rstrip()
        if response:
            print(f"Response: {response}")
            
        time.sleep(1)

finally:
    ser.close()
    print("Serial port closed.")
