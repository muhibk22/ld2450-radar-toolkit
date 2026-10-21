import serial
import time

try:
    s = serial.Serial("COM5", 115200, timeout=12)
    time.sleep(0.5)
    s.write(b"SCAN_WIFI\n")
    print("Sent SCAN_WIFI. Reading response...")
    for _ in range(5):
        ln = s.readline()
        if ln:
            print("ESP32:", ln.decode("utf-8", errors="replace").strip())
    s.close()
except Exception as e:
    print("Error:", e)
