#include <stdint.h>
#include <stddef.h>
#include <string.h>

// Inlined RadarStream framing and output queues; no local header is needed.
namespace RadarStream {
static const size_t FRAME_BYTES = 30;
struct Framer {
  uint8_t bytes[FRAME_BYTES];
  size_t used = 0;
  bool push(uint8_t value, uint8_t* frame) {
    bytes[used++] = value;
    if (used < FRAME_BYTES) return false;
    if (bytes[0] == 0xAA && bytes[1] == 0xFF && bytes[2] == 3 && bytes[3] == 0 &&
        bytes[28] == 0x55 && bytes[29] == 0xCC) {
      memcpy(frame, bytes, FRAME_BYTES);
      used = 0;
      return true;
    }
    memmove(bytes, bytes + 1, FRAME_BYTES - 1);
    used = FRAME_BYTES - 1;
    return false;
  }
};

struct Output {
  uint8_t active[128], latest[FRAME_BYTES];
  size_t length = 0, offset = 0;
  bool hasLatest = false;
  uint32_t startedAt = 0, latestAt = 0;
  void reset() { length = offset = 0; hasLatest = false; }
  void queueFrame(const uint8_t* frame, uint32_t now) {
    memcpy(latest, frame, FRAME_BYTES);
    hasLatest = true;
    latestAt = now;
  }
  bool queueNotice(const uint8_t* data, size_t size, uint32_t now) {
    if (length || hasLatest || size > sizeof(active)) return false;
    memcpy(active, data, size);
    length = size; offset = 0; startedAt = now;
    return true;
  }
  const uint8_t* front(uint32_t now, size_t& size) {
    if (!length && hasLatest) {
      hasLatest = false;
      if (uint32_t(now - latestAt) <= 500) {
        memcpy(active, latest, FRAME_BYTES);
        length = FRAME_BYTES; offset = 0; startedAt = now;
      }
    }
    size = length - offset;
    return size ? active + offset : nullptr;
  }
  void advance(size_t count) {
    if (count > length - offset) count = length - offset;
    offset += count;
    if (offset == length) length = offset = 0;
  }
  bool expired(uint32_t now) const {
    return length && uint32_t(now - startedAt) >= 250;
  }
};
}
#include <lwip/sockets.h>
#include <errno.h>
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

// Wi-Fi credentials are configured below; no env.h is needed.

#define TCP_PORT 8888
#define UDP_PORT 8889

// --- Hardware Pins ---
#define RX_PIN 18    // ESP32 RX <- LD2450 TX
#define TX_PIN 17    // ESP32 TX -> LD2450 RX
#define RADAR_BAUD 256000
const char* AP_SSID = "LD2450-Radar-AP";
const char* AP_PASS = "12345678";

const char* STA_SSID = "YOUR_WIFI_NAME"; // Replace with your Wi-Fi name
const char* STA_PASS = "YOUR_WIFI_PASSWORD"; // Replace with your Wi-Fi password

HardwareSerial Radar(2);
WiFiServer server(TCP_PORT);
const int MAX_TCP_CLIENTS = 4;
WiFiClient clients[MAX_TCP_CLIENTS];
RadarStream::Output outputs[MAX_TCP_CLIENTS];
RadarStream::Framer framer;
void flushClients() {
  for (int i=0; i<MAX_TCP_CLIENTS; ++i) {
    if (!clients[i] || !clients[i].connected()) { outputs[i].reset(); continue; }
    if (outputs[i].expired(millis())) { clients[i].stop(); outputs[i].reset(); continue; }
    size_t length=0;
    const uint8_t* data=outputs[i].front(millis(),length);
    if (!data) continue;
    int n=::send(clients[i].fd(),data,length,MSG_DONTWAIT);
    if (n>0) outputs[i].advance((size_t)n);
    else if (n==0 || (errno!=EAGAIN && errno!=EWOULDBLOCK && errno!=EINTR)) {
      clients[i].stop(); outputs[i].reset();
    }
  }
}
WiFiUDP udp;

// --- RGB Status LED Control ---
void setStatusLed(uint8_t r, uint8_t g, uint8_t b) {
  #ifdef RGB_BUILTIN
  rgbLedWrite(RGB_BUILTIN, r, g, b);
  #endif
  neopixelWrite(48, r, g, b);
  neopixelWrite(38, r, g, b);
  #ifdef LED_BUILTIN
  digitalWrite(LED_BUILTIN, (r > 0 || g > 0 || b > 0) ? HIGH : LOW);
  #endif
}

void setup() {
  Serial.begin(115200);
  #if ARDUINO_USB_CDC_ON_BOOT
  Serial.setTxTimeoutMs(0); // Debug output must never stall radar UART when USB is absent.
  #endif
  #ifdef LED_BUILTIN
  pinMode(LED_BUILTIN, OUTPUT);
  #endif
  setStatusLed(0, 0, 0);
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
    setStatusLed(160, 60, 0); // Amber in AP mode
  } else {
    WiFi.mode(WIFI_STA);
    WiFi.begin(STA_SSID, STA_PASS);
    Serial.printf("Connecting to Wi-Fi '%s'...", STA_SSID);
    bool ledToggle = false;
    while (WiFi.status() != WL_CONNECTED) {
      delay(500);
      Serial.print(".");
      ledToggle = !ledToggle;
      setStatusLed(0, 0, ledToggle ? 160 : 0); // Blink Blue while connecting
    }
    // Turn OFF LED once connected to Wi-Fi
    setStatusLed(0, 0, 0);
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
  WiFiClient newClient = server.accept();
  if (newClient) {
    bool accepted=false;
    for (int i=0; i<MAX_TCP_CLIENTS; ++i) {
      if (!clients[i] || !clients[i].connected()) {
        clients[i].stop(); outputs[i].reset();
        clients[i]=newClient; clients[i].setNoDelay(true);
        accepted=true; break;
      }
    }
    if (!accepted) newClient.stop();
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

    uint8_t frame[30];
    for (int b=0;b<readLen;++b) {
      if (framer.push(buffer[b],frame)) {
        for (int i=0;i<MAX_TCP_CLIENTS;++i) {
          if (clients[i] && clients[i].connected()) outputs[i].queueFrame(frame,millis());
        }
      }
    }
  }
  flushClients();
  for (int i=0;i<MAX_TCP_CLIENTS;++i) {
    if (clients[i] && clients[i].connected() && clients[i].available()>0) {
      int n=clients[i].read(buffer,sizeof(buffer));
      if (n>0) Radar.write(buffer,n);
    }
  }
  delay(1);
}
