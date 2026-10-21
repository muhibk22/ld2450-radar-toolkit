import os

def patch():
    ino_path = r"d:\Projects\FYP\Omnisense-\firmware\esp32_omnisense_firmware\esp32_omnisense_firmware.ino"
    with open(ino_path, "r", encoding="utf-8") as f:
        content = f.read()

    # 1. Update startCaptivePortal to also start tcpServer, udp and set SSID to LD2450-Radar-AP with pass 12345678
    old_portal = """void startCaptivePortal() {
  isApMode = true;
  WiFi.mode(WIFI_AP);
  WiFi.softAP("OmniSense-Radar-Setup", "");
  Serial.println("[Wi-Fi] SoftAP Started: 'OmniSense-Radar-Setup' (192.168.4.1)");

  webServer.on("/", handlePortalRoot);
  webServer.on("/save", handlePortalSave);
  webServer.begin();
}"""

    new_portal = """void startCaptivePortal() {
  isApMode = true;
  WiFi.disconnect(true);
  delay(100);
  WiFi.mode(WIFI_AP);
  WiFi.softAP("LD2450-Radar-AP", "12345678");
  IPAddress apIP = WiFi.softAPIP();
  Serial.printf("[Wi-Fi] SoftAP Active: 'LD2450-Radar-AP' (IP: %s, Pass: 12345678)\\n", apIP.toString().c_str());

  setStatusLed(160, 60, 0);

  // Enable TCP server & UDP discovery in AP mode so clients can stream radar directly!
  tcpServer.begin();
  udp.begin(UDP_PORT);

  webServer.on("/", handlePortalRoot);
  webServer.on("/save", handlePortalSave);
  webServer.begin();
}"""

    if old_portal in content:
        content = content.replace(old_portal, new_portal, 1)

    # 2. Update connectToWiFiSTA to do WiFi.disconnect(true), setAutoReconnect(true), maxAttempts default 60
    old_connect = """// --- Active Wi-Fi Connection with Real-time JSON Status Streaming & Blue LED Blink ---
bool connectToWiFiSTA(int maxAttempts) {
  if (wifiSsid.length() == 0) return false;

  if (isApMode) {
    webServer.stop();
    WiFi.softAPdisconnect(true);
    isApMode = false;
  }

  WiFi.mode(WIFI_STA);
  WiFi.setTxPower(WIFI_POWER_19_5dBm);
  WiFi.begin(wifiSsid.c_str(), wifiPass.c_str());
  Serial.printf("\\n[Wi-Fi] Connecting to '%s' (Room: %s)...\\n", wifiSsid.c_str(), assignedRoom.c_str());

  int attempts = 0;
  bool ledState = false;

  while (WiFi.status() != WL_CONNECTED && attempts < maxAttempts) {
    attempts++;
    int progress = (attempts * 100) / maxAttempts;
    String statusMsg = "Associating with " + wifiSsid + "...";
    if (attempts > 5) statusMsg = "Authenticating with WPA2 handshake...";
    if (attempts > 12) statusMsg = "Awaiting IP address from DHCP...";

    // Toggle Blue LED every 500ms so the user sees active Wi-Fi association attempts
    ledState = !ledState;
    if (ledState) {
      setStatusLed(0, 0, 160); // Bright Blue ON
    } else {
      setStatusLed(0, 0, 0);   // OFF
    }

    String jsonStatus = "{\\"type\\":\\"wifi_status\\",\\"status\\":\\"connecting\\",\\"attempt\\":" + String(attempts) + ",\\"max_attempts\\":" + String(maxAttempts) + ",\\"progress\\":" + String(progress) + ",\\"ssid\\":\\"" + wifiSsid + "\\",\\"msg\\":\\"" + statusMsg + "\\"}";
    Serial.println(jsonStatus);
    delay(500);
  }"""

    new_connect = """// --- Active Wi-Fi Connection with Real-time JSON Status Streaming & Blue LED Blink ---
bool connectToWiFiSTA(int maxAttempts) {
  if (wifiSsid.length() == 0) return false;

  // Fully reset Wi-Fi driver before connecting
  WiFi.disconnect(true);
  delay(200);

  if (isApMode) {
    webServer.stop();
    WiFi.softAPdisconnect(true);
    isApMode = false;
  }

  WiFi.mode(WIFI_STA);
  WiFi.setAutoReconnect(true);
  WiFi.setTxPower(WIFI_POWER_19_5dBm);
  WiFi.begin(wifiSsid.c_str(), wifiPass.c_str());
  Serial.printf("\\n[Wi-Fi] Connecting to '%s' (Room: %s)...\\n", wifiSsid.c_str(), assignedRoom.c_str());

  int attempts = 0;
  bool ledState = false;

  while (WiFi.status() != WL_CONNECTED && attempts < maxAttempts) {
    attempts++;
    int progress = (attempts * 100) / maxAttempts;
    String statusMsg = "Associating with " + wifiSsid + "...";
    if (attempts > 5) statusMsg = "Authenticating with WPA2 handshake...";
    if (attempts > 14) statusMsg = "Awaiting IP address from DHCP...";

    // Toggle Blue LED every 500ms so the user sees active Wi-Fi association attempts
    ledState = !ledState;
    if (ledState) {
      setStatusLed(0, 0, 160); // Bright Blue ON
    } else {
      setStatusLed(0, 0, 0);   // OFF
    }

    String jsonStatus = "{\\"type\\":\\"wifi_status\\",\\"status\\":\\"connecting\\",\\"attempt\\":" + String(attempts) + ",\\"max_attempts\\":" + String(maxAttempts) + ",\\"progress\\":" + String(progress) + ",\\"ssid\\":\\"" + wifiSsid + "\\",\\"msg\\":\\"" + statusMsg + "\\"}";
    Serial.println(jsonStatus);
    delay(500);
  }"""

    if old_connect in content:
        content = content.replace(old_connect, new_connect, 1)

    # 3. Increase maxAttempts in CONFIGURE to 60 (30 seconds)
    content = content.replace("connectToWiFiSTA(30)", "connectToWiFiSTA(60)")
    content = content.replace("connectToWiFiSTA(25)", "connectToWiFiSTA(60)")

    # 4. In loop, do not return on isApMode so radar streaming is alive in AP mode!
    content = content.replace("""  // Handle AP Web Server if in setup mode
  if (isApMode) {
    webServer.handleClient();
    return;
  }""", """  // Handle AP Web Server if in setup mode
  if (isApMode) {
    webServer.handleClient();
  }""")

    with open(ino_path, "w", encoding="utf-8") as f:
        f.write(content)
    print("SUCCESS: esp32_omnisense_firmware.ino updated with robust Wi-Fi & AP streaming!")

if __name__ == "__main__":
    patch()
