/*
 * LD2450 ESP32 Wi-Fi Ultra-Low-Latency Wireless Bridge Firmware
 * (With Wall-Socket Non-Blocking USB CDC Fix)
 * 
 * Hardware Wiring:
 * ESP32 RX Pin 18 <--- LD2450 TX Pin
 * ESP32 TX Pin 17 ---> LD2450 RX Pin
 */

#include <WiFi.h>
#include <WiFiUdp.h>
#include <esp_wifi.h>

// --- Wi-Fi Configuration ---
#define USE_AP_MODE false  // Set to false to connect to your Wi-Fi router

#include "env.h"

#define TCP_PORT 8888
#define UDP_PORT 8889

// --- Hardware Pins ---
#define RX_PIN 18    // ESP32 RX <- LD2450 TX
#define TX_PIN 17    // ESP32 TX -> LD2450 RX
#define RADAR_BAUD 256000

HardwareSerial Radar(2);
WiFiServer server(TCP_PORT);
WiFiClient client;
WiFiUDP udp;

void setup() {
  Serial.begin(115200);
  delay(500);
  Serial.println("\n--- Starting LD2450 ESP32 Ultra-Low-Latency Wi-Fi Bridge ---");

  // Initialize Radar UART at 256000 baud with 2048-byte RX buffer
  Radar.setRxBufferSize(2048);
  Radar.begin(RADAR_BAUD, SERIAL_8N1, RX_PIN, TX_PIN);

  if (USE_AP_MODE) {
    WiFi.mode(WIFI_AP);
    WiFi.softAP(AP_SSID, AP_PASS);
    IPAddress apIP = WiFi.softAPIP();
    Serial.printf("Created Wi-Fi AP '%s' (IP: %s)\n", AP_SSID, apIP.toString().c_str());
  } else {
    WiFi.mode(WIFI_STA);
    WiFi.begin(STA_SSID, STA_PASS);
    Serial.printf("Connecting to Wi-Fi '%s'...", STA_SSID);
    while (WiFi.status() != WL_CONNECTED) {
      delay(500);
      Serial.print(".");
    }
    Serial.println("\nConnected to Wi-Fi!");
    Serial.print("ESP32 IP Address: ");
    Serial.println(WiFi.localIP());
  }

  // --- Ultra-Low Latency WiFi Optimization ---
  WiFi.setSleep(false);                 // Disable modem sleep
  esp_wifi_set_ps(WIFI_PS_NONE);        // Keep Wi-Fi radio fully active for <2ms response

  // Start TCP Server & UDP Discovery
  server.begin();
  udp.begin(UDP_PORT);
  Serial.printf("TCP Low-Latency Server started on Port %d.\n", TCP_PORT);
}

uint8_t buffer[512];
char udpBuffer[256];

void loop() {
  // 1. Handle UDP Auto-Discovery Pings from Desktop App
  int packetSize = udp.parsePacket();
  if (packetSize > 0) {
    int len = udp.read(udpBuffer, sizeof(udpBuffer) - 1);
    if (len > 0) udpBuffer[len] = 0;
    if (strstr(udpBuffer, "DISCOVER_LD2450") != NULL) {
      udp.beginPacket(udp.remoteIP(), udp.remotePort());
      String resp = "LD2450_IP:" + WiFi.localIP().toString();
      udp.print(resp);
      udp.endPacket();
    }
  }

  // 2. Handle Incoming TCP Client Connection (Set TCP_NODELAY to disable Nagle buffering)
  WiFiClient newClient = server.available();
  if (newClient) {
    if (client && client.connected()) {
      client.stop();
    }
    client = newClient;
    client.setNoDelay(true); // Disable Nagle's algorithm for instant 2ms packet transmission!
    Serial.printf("New PC Client connected from %s (TCP_NODELAY enabled)\n", client.remoteIP().toString().c_str());
  }

  // 3. Read raw bytes from LD2450 Radar UART and stream instantly over Wi-Fi
  int availableBytes = Radar.available();
  if (availableBytes > 0) {
    int readLen = Radar.readBytes(buffer, min(availableBytes, (int)sizeof(buffer)));
    
    // Echo to USB Serial ONLY if host terminal is connected AND there is enough space for the full payload
    // This prevents a partial-write blocking stall when powered by a wall socket
    if (Serial && Serial.availableForWrite() >= readLen) {
      Serial.write(buffer, readLen);
    }

    // Stream instantly over TCP socket
    if (client && client.connected()) {
      client.write(buffer, readLen);
    }
  }

  // 4. Handle incoming commands from PC client
  if (client && client.connected() && client.available() > 0) {
    int rxLen = client.read(buffer, sizeof(buffer));
    Radar.write(buffer, rxLen);
  }
}
