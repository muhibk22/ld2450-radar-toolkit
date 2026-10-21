import os

# 1. Update esp32_omnisense_firmware.ino
fw_path = r"d:\Projects\FYP\Omnisense-\firmware\esp32_omnisense_firmware\esp32_omnisense_firmware.ino"
with open(fw_path, "r", encoding="utf-8") as f:
    fw_content = f.read()

old_led_block = """    delay(1000);
    // Subtle idle green
    setStatusLed(0, 30, 0);
    return true;"""

new_led_block = """    delay(400);
    // Turn LED completely OFF once connected to Wi-Fi per user requirement
    setStatusLed(0, 0, 0);
    return true;"""

if old_led_block in fw_content:
    fw_content = fw_content.replace(old_led_block, new_led_block)
    print("Updated LED turn-off logic in firmware.")

old_loop_tail = """    // Channel C: Buffer for MQTT transmission
    if (readLen == FRAME_SIZE && rxBuffer[0] == 0xAA && rxBuffer[1] == 0xFF) {
      enqueuePacket(rxBuffer);
    }
  }

  // 4. MQTT Connection & QoS 1 Publishing"""

new_loop_tail = """    // Channel C: Buffer for MQTT transmission
    if (readLen == FRAME_SIZE && rxBuffer[0] == 0xAA && rxBuffer[1] == 0xFF) {
      enqueuePacket(rxBuffer);
    }
  }

  // --- Auto-Baud Detection for HLK-LD2450 (256,000 <-> 115,200 baud) ---
  static uint32_t currentRadarBaud = RADAR_BAUD;
  static unsigned long lastValidRadarHeader = 0;
  static unsigned long lastBaudSwitch = 0;
  if (avail > 0 && rxBuffer[0] == 0xAA && rxBuffer[1] == 0xFF) {
    lastValidRadarHeader = millis();
  }
  if (millis() - lastBaudSwitch > 4000) {
    if (millis() - lastValidRadarHeader > 4000) {
      lastBaudSwitch = millis();
      currentRadarBaud = (currentRadarBaud == 256000) ? 115200 : 256000;
      Serial.printf("[Radar UART] Probing baud rate: switching to %u baud...\\n", currentRadarBaud);
      RadarSerial.begin(currentRadarBaud, SERIAL_8N1, RADAR_RX_PIN, RADAR_TX_PIN);
    }
  }

  // --- Periodic TCP Keepalive Heartbeat & Cleanup ---
  if (tcpClient && !tcpClient.connected()) {
    tcpClient.stop();
  }
  static unsigned long lastTcpKeepalive = 0;
  if (tcpClient && tcpClient.connected()) {
    if (millis() - lastTcpKeepalive > 2000) {
      lastTcpKeepalive = millis();
      const uint8_t keepalive[4] = {0xAA, 0xFF, 0x00, 0x55};
      tcpClient.write(keepalive, sizeof(keepalive));
    }
  }

  // 4. MQTT Connection & QoS 1 Publishing"""

if old_loop_tail in fw_content:
    fw_content = fw_content.replace(old_loop_tail, new_loop_tail)
    print("Added TCP keepalive & auto-baud to firmware.")

with open(fw_path, "w", encoding="utf-8") as f:
    f.write(fw_content)

print("Saved esp32_omnisense_firmware.ino.")
