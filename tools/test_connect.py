import serial
import time
import json

s = serial.Serial("COM5", 115200, timeout=1)
time.sleep(0.5)

cfg = {
    "cmd": "CONFIGURE",
    "ssid": "Error101",
    "pass": "27011997",
    "room": "Living Room",
    "server": "192.168.100.128"
}

cmd_str = json.dumps(cfg) + "\n"
s.write(cmd_str.encode("utf-8"))
print("Sent CONFIGURE with password 27011997...")

start = time.time()
while time.time() - start < 35:
    raw = s.readline()
    if raw:
        text = raw.decode("ascii", errors="ignore").strip()
        if text:
            print(text)
        if "connected" in text.lower():
            print(">>> SUCCESS CONFIRMED! <<<")
            break

s.close()
