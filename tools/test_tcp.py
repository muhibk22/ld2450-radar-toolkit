import socket

try:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(3)
    s.connect(("192.168.100.129", 8888))
    print("SUCCESS: Connected to ESP32 TCP Radar Server on 192.168.100.129:8888!")
    # Read a few bytes of radar telemetry
    data = s.recv(60)
    print("Received raw radar bytes:", len(data), "bytes:", data[:10].hex())
    s.close()
except Exception as e:
    print("Socket error:", e)
