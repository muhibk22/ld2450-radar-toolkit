/*
  ESP32-S3 Transparent HardwareSerial Bridge for HLK-LD2450 mmWave Radar
  
  Baud rate: 256000
  RX Pin: 18 (ESP32 RX <- LD2450 TX)
  TX Pin: 17 (ESP32 TX -> LD2450 RX)
*/

#include <Arduino.h>

HardwareSerial Radar(2);

#define RX_PIN 18
#define TX_PIN 17
#define BAUDRATE 256000

void setup() {
  // USB CDC Serial to PC
  Serial.begin(BAUDRATE);
  #if ARDUINO_USB_CDC_ON_BOOT
  Serial.setTxTimeoutMs(0); // Debug output must never stall radar UART when USB is absent.
  #endif
  
  // Hardware UART2 to LD2450 Radar
  Radar.setRxBufferSize(2048);
  Radar.setTimeout(5);
  Radar.begin(BAUDRATE, SERIAL_8N1, RX_PIN, TX_PIN);
}

void loop() {
  uint8_t buffer[256];
  int available = Radar.available();
  if (available > 0) {
    int capacity = Serial ? Serial.availableForWrite() : 0;
    // Drop data while USB is absent instead of blocking UART or replaying backlog.
    int n = min(available, (int)sizeof(buffer));
    if (capacity > 0) n = min(n, capacity);
    int received = Radar.readBytes(buffer, n);
    if (capacity > 0 && received > 0) Serial.write(buffer, received);
  }
  if (Serial.available() > 0) {
    int n = Serial.readBytes(buffer, min(Serial.available(), (int)sizeof(buffer)));
    if (n > 0) Radar.write(buffer, n);
  }
  delay(1);
}
