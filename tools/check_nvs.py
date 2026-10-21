import serial
import time

s = serial.Serial("COM5", 115200, timeout=2)
time.sleep(0.5)

# First query status
s.write(b"GET_STATUS\n")
time.sleep(0.5)
print("GET_STATUS response:")
for _ in range(3):
    ln = s.readline()
    if ln:
        print(ln.decode("utf-8", errors="replace").strip())

s.close()
