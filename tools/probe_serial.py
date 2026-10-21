import serial
import time

try:
    s = serial.Serial("COM5", 115200, timeout=1.5)
    s.dtr = False
    s.rts = True
    time.sleep(0.1)
    s.rts = False
    time.sleep(0.5)

    print("--- Reading boot log ---")
    for _ in range(12):
        raw = s.readline()
        if raw:
            text = raw.decode("ascii", errors="ignore").strip()
            if text:
                print("ESP32:", text)
    s.close()
except Exception as e:
    print("Error:", e)
