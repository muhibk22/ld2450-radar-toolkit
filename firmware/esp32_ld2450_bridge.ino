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
  
  // Hardware UART2 to LD2450 Radar
  Radar.begin(BAUDRATE, SERIAL_8N1, RX_PIN, TX_PIN);
}

void loop() {
  // Transparent bi-directional pass-through
  while (Radar.available()) {
    Serial.write(Radar.read());
  }
  while (Serial.available()) {
    Radar.write(Serial.read());
  }
}
