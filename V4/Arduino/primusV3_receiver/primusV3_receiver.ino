/*
 * primusV3_receiver.ino — PrimusV3.6 Art-Net LED Receiver
 * =============================================================
 * Art-Net only.  Each output listens on its own universe.
 * Hardware brightness locked to 255; show brightness is sender-side RGB scaling.
 * Adaptive show interval for max FPS.
 * Sends FPS telemetry back to sender on port 6455.
 *
 * Hardware profiles:
 *   - V1 Huzzah32 direct NeoPixel outputs
 *   - V2 ESP32 Feather direct NeoPixel outputs
 *   - V3.1 ESP32-S3 Reverse TFT Feather + NeoPXL8 FeatherWing outputs 6/7
 *
 * Build profiles are selected by V3_6/Arduino/upload.sh.
 */

#include <WiFi.h>
#include <WiFiUdp.h>
#include <Preferences.h>
#include "config.h"
#include "receive_mode.h"

#if BOARD_OUTPUT_DRIVER == PRIMUS_DRIVER_NEOPXL8
  #include <Adafruit_NeoPXL8.h>
#else
  #include <Adafruit_NeoPixel.h>
#endif

#include "display.h"
#include "buttons.h"
#if BOARD_BATTERY_MONITOR
#include "battery.h"
#endif

// =====================================================================
//  Globals
// =====================================================================

OutputConfig outputs[NUM_OUTPUTS];

#if BOARD_OUTPUT_DRIVER == PRIMUS_DRIVER_NEOPXL8
int8_t pxl8Pins[8] = {
  -1, -1, -1, -1, -1, -1,
  PIN_PORT_6, PIN_PORT_7
};

Adafruit_NeoPXL8* leds = nullptr;
#else
Adafruit_NeoPixel* directLeds[NUM_OUTPUTS] = { nullptr, nullptr };
#endif

#if BOARD_HAS_STATUS_NEOPIXEL
Adafruit_NeoPixel statusPixel(1, BOARD_STATUS_NEOPIXEL_PIN, NEO_GRB + NEO_KHZ800);
#endif

// ── Art-Net ──────────────────────────────────────────────────────────
#define MAX_UDP_PACKET 600
WiFiUDP udp;
WiFiUDP udpFps;              // separate socket for FPS back-channel
uint8_t udpBuf[MAX_UDP_PACKET];

#define ARTNET_HEADER_LEN  8
#define ARTNET_DATA_OFFSET 18

static const uint8_t ARTNET_MAGIC[ARTNET_HEADER_LEN] =
  { 'A', 'r', 't', '-', 'N', 'e', 't', '\0' };

// ── Per-output buffers ───────────────────────────────────────────────
uint8_t outputBuffers[NUM_OUTPUTS][MAX_BUFFER_SIZE];
bool    outputDataReady[NUM_OUTPUTS]  = {};
bool    outputActive[NUM_OUTPUTS]     = {};
unsigned long outputLastPacket[NUM_OUTPUTS] = {};

// ── Frame assembly ───────────────────────────────────────────────────
FrameAssemblyState frameState = {};
uint8_t  activeOutputCount = 0;       // cached count of non-OFF outputs

// ── WiFi ─────────────────────────────────────────────────────────────
bool wifiConnected = false;
unsigned long lastReconnectAttempt = 0;

// No-screen board connection indicator. V1 uses LED_BUILTIN; V2 uses
// the onboard NeoPixel. V3.1 keeps using the TFT display.
bool statusIndicatorConnected = false;
bool statusIndicatorStaticIP = false;
bool statusIndicatorLit = false;
unsigned long lastStatusIndicatorBlink = 0;
static const unsigned long STATUS_INDICATOR_BLINK_INTERVAL = 500;

// ── Sender address (for FPS back-channel) ────────────────────────────
IPAddress senderIP;
bool      senderKnown = false;

// ── Custom device name (stored in NVS via ArtAddress) ────────────────
Preferences prefs;
char customShortName[18] = {0};
bool hasCustomName = false;

// ── Show info: character/performer names (stored in NVS) ─────────────
char showCharacterName[SHOW_INFO_FIELD_LEN + 1] = {0};
char showPerformerName[SHOW_INFO_FIELD_LEN + 1] = {0};

// ── Static IP config (stored in NVS) ─────────────────────────────────
bool useStaticIP = false;
bool activeStaticIP = false;
uint8_t storedIP[4]      = {0};
uint8_t storedGateway[4] = {0};
uint8_t storedSubnet[4]  = {0};

void loadStoredDeviceName() {
#ifdef PRIMUSV3_FORCE_DEVICE_NAME_OVERRIDE
  strncpy(customShortName, DEVICE_SHORT_NAME, sizeof(customShortName) - 1);
  customShortName[sizeof(customShortName) - 1] = '\0';
  hasCustomName = customShortName[0] != '\0';
  if (hasCustomName) {
    prefs.putString("shortName", customShortName);
    Serial.print("Firmware name override stored: \"");
    Serial.print(customShortName);
    Serial.println("\"");
  }
  return;
#endif

  if (prefs.isKey("shortName")) {
    String stored = prefs.getString("shortName", "");
    if (stored.length() > 0) {
      stored.toCharArray(customShortName, sizeof(customShortName));
      hasCustomName = true;
      Serial.print("Loaded custom name: \"");
      Serial.print(customShortName);
      Serial.println("\"");
    }
  }
}

void loadStoredShowInfo() {
  if (prefs.isKey("characterName")) {
    String stored = prefs.getString("characterName", "");
    stored.toCharArray(showCharacterName, sizeof(showCharacterName));
  }
  if (prefs.isKey("performerName")) {
    String stored = prefs.getString("performerName", "");
    stored.toCharArray(showPerformerName, sizeof(showPerformerName));
  }
  if (showCharacterName[0] != '\0' || showPerformerName[0] != '\0') {
    Serial.print("Loaded show info: character=\"");
    Serial.print(showCharacterName);
    Serial.print("\" performer=\"");
    Serial.print(showPerformerName);
    Serial.println("\"");
  }
}

void printIpBytes(const uint8_t* bytes) {
  Serial.print(bytes[0]); Serial.print(".");
  Serial.print(bytes[1]); Serial.print(".");
  Serial.print(bytes[2]); Serial.print(".");
  Serial.print(bytes[3]);
}

void loadStoredNetworkConfig() {
#ifdef PRIMUSV3_FORCE_DHCP_OVERRIDE
  useStaticIP = false;
  prefs.remove("staticIP");
  prefs.remove("gateway");
  prefs.remove("subnet");
  Serial.println("Firmware DHCP override stored: saved static IP settings cleared.");
  return;
#endif

#ifdef PRIMUSV3_FORCE_STATIC_IP_OVERRIDE
  const uint8_t ipOverride[4] = { PRIMUSV3_STATIC_IP_OCTETS };
  const uint8_t gatewayOverride[4] = { PRIMUSV3_STATIC_GATEWAY_OCTETS };
  const uint8_t subnetOverride[4] = { PRIMUSV3_STATIC_SUBNET_OCTETS };
  memcpy(storedIP, ipOverride, 4);
  memcpy(storedGateway, gatewayOverride, 4);
  memcpy(storedSubnet, subnetOverride, 4);
  useStaticIP = true;
  prefs.putBytes("staticIP", storedIP, 4);
  prefs.putBytes("gateway", storedGateway, 4);
  prefs.putBytes("subnet", storedSubnet, 4);
  Serial.print("Firmware static IP override stored: ");
  printIpBytes(storedIP);
  Serial.print(" gateway ");
  printIpBytes(storedGateway);
  Serial.print(" subnet ");
  printIpBytes(storedSubnet);
  Serial.println();
  return;
#endif

  if (prefs.isKey("staticIP")) {
    size_t ipLen = prefs.getBytes("staticIP", storedIP, 4);
    size_t gwLen = prefs.getBytes("gateway", storedGateway, 4);
    size_t snLen = prefs.getBytes("subnet", storedSubnet, 4);
    if (ipLen == 4 && gwLen == 4 && snLen == 4) {
      useStaticIP = true;
      Serial.print("Loaded static IP: ");
      printIpBytes(storedIP);
      Serial.println();
    }
  }
}

void printStartupConnectionData() {
  Serial.println("Startup connection data:");
  Serial.print("  Device name: ");
  Serial.println(hasCustomName ? customShortName : DEVICE_SHORT_NAME);
  Serial.print("  Board profile: ");
  Serial.println(BOARD_PROFILE_LABEL);
  Serial.print("  Firmware: ");
  Serial.print(FIRMWARE_NAME);
  Serial.print(" ");
  Serial.println(FIRMWARE_VERSION);
  Serial.print("  Target SSID: ");
  Serial.println(DEFAULT_WIFI_SSID);
  Serial.print("  Target password: ");
  Serial.println(DEFAULT_WIFI_PASSWORD);
  Serial.print("  IP mode: ");
  Serial.println(useStaticIP ? "Static" : "DHCP - no static IP assigned");
  if (useStaticIP) {
    Serial.print("  Static IP: ");
    printIpBytes(storedIP);
    Serial.println();
    Serial.print("  Gateway: ");
    printIpBytes(storedGateway);
    Serial.println();
    Serial.print("  Subnet: ");
    printIpBytes(storedSubnet);
    Serial.println();
  } else {
    Serial.println("  Static IP: none stored");
  }
  for (uint8_t i = 0; i < NUM_OUTPUTS; i++) {
    Serial.print("  Output ");
    Serial.print(i);
    Serial.print(": ");
    Serial.print(typeName(outputs[i].type));
    Serial.print(" on port ");
    Serial.print(outputs[i].pxl8Port);
    Serial.print(" universe ");
    Serial.println(outputs[i].universe);
  }
  Serial.print("  Receive mode: ");
  Serial.print(receiveModeLabel(currentReceiveMode));
  Serial.print(" base ");
  Serial.println(currentUniverseBase);
}

void printConnectedNetworkData() {
  Serial.println("Connected network data:");
  Serial.print("  Device name: ");
  Serial.println(hasCustomName ? customShortName : DEVICE_SHORT_NAME);
  Serial.print("  SSID: ");
  Serial.println(WiFi.SSID());
  Serial.print("  IP address: ");
  Serial.println(WiFi.localIP());
  Serial.print("  Gateway: ");
  Serial.println(WiFi.gatewayIP());
  Serial.print("  Subnet: ");
  Serial.println(WiFi.subnetMask());
  Serial.print("  MAC: ");
  Serial.println(WiFi.macAddress());
  Serial.print("  RSSI: ");
  Serial.print(WiFi.RSSI());
  Serial.println(" dBm");
  Serial.print("  Static IP assigned: ");
  Serial.println(activeStaticIP ? "yes" : "no");
  Serial.print("  Saved static IP settings: ");
  Serial.println(useStaticIP ? "yes" : "no");
}

// ── Timing / FPS ─────────────────────────────────────────────────────
unsigned long lastShowTime  = 0;
unsigned long showDuration  = 2000;   // measured leds->show() time in µs
unsigned long showInterval  = 3;      // adaptive: showDuration/1000 + 1 ms
unsigned long lastFpsTime   = 0;
unsigned long frameCount    = 0;
unsigned long packetCount   = 0;
float         currentFps    = 0;
bool          newDataSinceLastShow = false;

// ── Test mode ────────────────────────────────────────────────────────
bool     testModeActive = false;
uint8_t  testModeIndex  = 0;
#define  NUM_TEST_MODES 5
const char* testModeNames[NUM_TEST_MODES] =
  { "Off", "Color Wipe", "White", "Rainbow", "March" };

long     rainbowHue[NUM_OUTPUTS] = {};
uint16_t marchPos[NUM_OUTPUTS]   = {};
uint16_t wipePos[NUM_OUTPUTS]    = {};
bool     wipeDone[NUM_OUTPUTS]   = {};

// ── Screen cycling ───────────────────────────────────────────────────
uint8_t infoScreenIndex = 0;

// =====================================================================
//  LED Output Helpers
// =====================================================================

inline void setStripPixel(uint8_t port, uint16_t pixel, uint32_t color) {
#if BOARD_OUTPUT_DRIVER == PRIMUS_DRIVER_NEOPXL8
  leds->setPixelColor(port * MAX_LEDS_PER_PORT + pixel, color);
#else
  if (port < NUM_OUTPUTS && directLeds[port] && pixel < MAX_LEDS_PER_PORT) {
    directLeds[port]->setPixelColor(pixel, color);
  }
#endif
}

void clearPort(uint8_t port, uint16_t count) {
  for (uint16_t p = 0; p < count; p++) {
    setStripPixel(port, p, 0);
  }
}

void showOutputs() {
#if BOARD_OUTPUT_DRIVER == PRIMUS_DRIVER_NEOPXL8
  if (leds) leds->show();
#else
  for (uint8_t i = 0; i < NUM_OUTPUTS; i++) {
    if (directLeds[i]) directLeds[i]->show();
  }
#endif
}

void loadStoredOutputConfig() {
  for (uint8_t i = 0; i < NUM_OUTPUTS; i++) {
    String key = "otype" + String(i);
    if (!prefs.isKey(key.c_str())) continue;
    uint8_t storedType = prefs.getUChar(key.c_str(), outputs[i].type);
    if (storedType >= NUM_OUTPUT_TYPES) continue;
    OutputType candidate = (OutputType)storedType;
    if (!profileSupportsOutputType(candidate)) continue;
    outputs[i].type = candidate;
    deriveFromType(outputs[i]);
  }
}

void saveOutputConfig() {
  for (uint8_t i = 0; i < NUM_OUTPUTS; i++) {
    String key = "otype" + String(i);
    prefs.putUChar(key.c_str(), (uint8_t)outputs[i].type);
  }
}

// =====================================================================
//  WiFi
// =====================================================================

void writeConnectionIndicator(bool lit) {
  statusIndicatorLit = lit;

#if BOARD_HAS_STATUS_LED
  bool ledOn = lit ? BOARD_STATUS_LED_ACTIVE_HIGH : !BOARD_STATUS_LED_ACTIVE_HIGH;
  digitalWrite(BOARD_STATUS_LED_PIN, ledOn ? HIGH : LOW);
#endif

#if BOARD_HAS_STATUS_NEOPIXEL
  uint32_t color = lit
    ? statusPixel.Color(BOARD_STATUS_NEOPIXEL_BRIGHTNESS, 0, 0)
    : statusPixel.Color(0, 0, 0);
  statusPixel.setPixelColor(0, color);
  statusPixel.show();
#endif
}

void setConnectionIndicator(bool connected) {
  statusIndicatorConnected = connected;
  statusIndicatorStaticIP = activeStaticIP;
  lastStatusIndicatorBlink = millis();

  if (!connected) {
    writeConnectionIndicator(false);
    return;
  }

  writeConnectionIndicator(true);
}

void initConnectionIndicator() {
#if BOARD_HAS_STATUS_LED
  pinMode(BOARD_STATUS_LED_PIN, OUTPUT);
#endif

#if BOARD_HAS_STATUS_NEOPIXEL
  #if BOARD_STATUS_NEOPIXEL_POWER_PIN >= 0
    pinMode(BOARD_STATUS_NEOPIXEL_POWER_PIN, OUTPUT);
    digitalWrite(BOARD_STATUS_NEOPIXEL_POWER_PIN, HIGH);
  #endif
  statusPixel.begin();
  statusPixel.setBrightness(BOARD_STATUS_NEOPIXEL_BRIGHTNESS);
#endif

  setConnectionIndicator(false);
}

void syncConnectionIndicator() {
  bool connected = (WiFi.status() == WL_CONNECTED);
  wifiConnected = connected;
  if (connected != statusIndicatorConnected || activeStaticIP != statusIndicatorStaticIP) {
    setConnectionIndicator(connected);
    return;
  }
  if (connected && !activeStaticIP && millis() - lastStatusIndicatorBlink >= STATUS_INDICATOR_BLINK_INTERVAL) {
    lastStatusIndicatorBlink = millis();
    writeConnectionIndicator(!statusIndicatorLit);
  }
}

bool connectWifi() {
  WiFi.persistent(false);
  activeStaticIP = false;

#ifdef PRIMUSV3_FORCE_WIFI_CREDENTIAL_OVERRIDE
  static bool clearedStoredWifiCredentials = false;
  if (!clearedStoredWifiCredentials) {
    Serial.println("WiFi credential override active: clearing stored ESP32 station credentials.");
    WiFi.disconnect(true, true);
    delay(100);
    clearedStoredWifiCredentials = true;
  }
#endif

  WiFi.mode(WIFI_STA);

  if (useStaticIP) {
    IPAddress localIP(storedIP[0], storedIP[1], storedIP[2], storedIP[3]);
    IPAddress gateway(storedGateway[0], storedGateway[1], storedGateway[2], storedGateway[3]);
    IPAddress subnet(storedSubnet[0], storedSubnet[1], storedSubnet[2], storedSubnet[3]);
    activeStaticIP = WiFi.config(localIP, gateway, subnet);
    if (activeStaticIP) {
      Serial.print("Using static IP: ");
      Serial.println(localIP);
    } else {
      Serial.println("Static IP config failed; using DHCP");
    }
  } else {
    Serial.println("Using DHCP");
  }

  WiFi.setSleep(false);
  Serial.print("WiFi SSID: ");
  Serial.println(DEFAULT_WIFI_SSID);
  WiFi.begin(DEFAULT_WIFI_SSID, DEFAULT_WIFI_PASSWORD);

  Serial.print("Connecting to WiFi");
  int attempts = 0;
  while (WiFi.status() != WL_CONNECTED && attempts < 20) {
    delay(500);
    Serial.print(".");
    attempts++;
  }
  Serial.println();

  if (WiFi.status() == WL_CONNECTED) {
    Serial.print("Connected! IP: ");
    Serial.println(WiFi.localIP());
    printConnectedNetworkData();
    setConnectionIndicator(true);
    return true;
  }
  Serial.println("WiFi connection failed.");
  setConnectionIndicator(false);
  return false;
}

void checkWifiConnection() {
  unsigned long now = millis();

  unsigned long newest = 0;
  for (uint8_t i = 0; i < NUM_OUTPUTS; i++) {
    if (outputLastPacket[i] > newest) newest = outputLastPacket[i];
  }

  if (now - newest > CONNECTION_TIMEOUT && newest > 0) {
    if (WiFi.status() != WL_CONNECTED) {
      wifiConnected = false;
      setConnectionIndicator(false);
      if (now - lastReconnectAttempt > RECONNECT_INTERVAL) {
        Serial.println("Reconnecting WiFi...");
        lastReconnectAttempt = now;
        wifiConnected = connectWifi();
        if (wifiConnected) {
          setConnectionIndicator(true);
          udp.begin(ARTNET_PORT);
        }
      }
    }
  }

  syncConnectionIndicator();
}

// =====================================================================
//  Art-Net ArtPollReply — standard discovery response
// =====================================================================

void sendArtPollReply(IPAddress dest) {
  uint8_t reply[239];
  memset(reply, 0, sizeof(reply));

  // Header & opcode
  memcpy(reply, ARTNET_MAGIC, 8);
  reply[8] = (ARTNET_OPCODE_POLLREPLY)      & 0xFF;  // opcode LE
  reply[9] = (ARTNET_OPCODE_POLLREPLY >> 8)  & 0xFF;

  // IP address (bytes 10-13)
  IPAddress myIP = WiFi.localIP();
  reply[10] = myIP[0]; reply[11] = myIP[1];
  reply[12] = myIP[2]; reply[13] = myIP[3];

  // Port (bytes 14-15, little-endian)
  reply[14] = ARTNET_PORT & 0xFF;
  reply[15] = (ARTNET_PORT >> 8) & 0xFF;

  // Firmware version (bytes 16-17, big-endian)
  reply[16] = FIRMWARE_VERSION_H;
  reply[17] = FIRMWARE_VERSION_L;

  // NetSwitch (byte 18) and SubSwitch (byte 19) — both 0 for universe 0-15
  reply[18] = 0;
  reply[19] = 0;

  // OEM code (bytes 20-21, big-endian)
  reply[20] = (OEM_CODE >> 8) & 0xFF;
  reply[21] = OEM_CODE & 0xFF;

  // Ubea version (byte 22), Status1 (byte 23)
  reply[22] = 0;
  reply[23] = 0xD0;  // Normal mode, all diagnostics OK, indicators normal

  // ESTA Manufacturer (bytes 24-25, little-endian)
  reply[24] = ESTA_CODE & 0xFF;
  reply[25] = (ESTA_CODE >> 8) & 0xFF;

  // Short Name (bytes 26-43, max 18 chars)
  const char* nameToUse = hasCustomName ? customShortName : DEVICE_SHORT_NAME;
  strncpy((char*)&reply[26], nameToUse, 17);

  // Long Name (bytes 44-107, max 64 chars)
  // Keep this human-readable for generic Art-Net tooling.
  char longBuf[64];
  int pos = snprintf(longBuf, sizeof(longBuf), "%s | ", DEVICE_LONG_NAME);
  for (uint8_t i = 0; i < NUM_OUTPUTS && pos < 60; i++) {
    if (outputs[i].type == OUTPUT_OFF) continue;
    pos += snprintf(longBuf + pos, sizeof(longBuf) - pos,
                    "A%d:%s ", i, typeName(outputs[i].type));
  }
  strncpy((char*)&reply[44], longBuf, 63);

  // Node Report (bytes 108-171, max 64 chars)
  // Append a versioned capability tag so the sender can discover output
  // types and universe mapping without scraping the Long Name.
  char reportBuf[64];
  int reportPos = snprintf(reportBuf, sizeof(reportBuf), "#0001 [%04d] OK|%s",
                           (int)packetCount, NODE_CAPS_PREFIX);
  for (uint8_t i = 0; i < NUM_OUTPUTS && reportPos < (int)sizeof(reportBuf) - 1; i++) {
    if (outputs[i].type == OUTPUT_OFF) continue;
    reportPos += snprintf(reportBuf + reportPos, sizeof(reportBuf) - reportPos,
                          "|%u:%u:%u", i, (uint8_t)outputs[i].type, outputs[i].universe);
  }
  if (reportPos < (int)sizeof(reportBuf) - 1) {
    reportPos += snprintf(reportBuf + reportPos, sizeof(reportBuf) - reportPos,
                          "|B:%s", BOARD_PROFILE_CODE);
  }
  if (reportPos < (int)sizeof(reportBuf) - 1) {
    reportPos += snprintf(reportBuf + reportPos, sizeof(reportBuf) - reportPos,
                          "|IP:%c", useStaticIP ? 'S' : 'D');
  }
  reportPos = buildReceiveModeCapabilityToken(reportBuf, sizeof(reportBuf), reportPos);
  if (reportPos < (int)sizeof(reportBuf) - 1) {
    reportPos += snprintf(reportBuf + reportPos, sizeof(reportBuf) - reportPos,
                          "|F:%s", BOARD_BATTERY_FEATURES);
  }
  strncpy((char*)&reply[108], reportBuf, 63);

  // NumPorts (bytes 172-173, big-endian)
  reply[172] = 0;
  reply[173] = activeOutputCount;

  // PortTypes (bytes 174-177): 0x80 = Art-Net output, 0xC0 = DMX output
  for (uint8_t i = 0; i < NUM_OUTPUTS && i < 4; i++) {
    reply[174 + i] = (outputs[i].type != OUTPUT_OFF) ? 0xC0 : 0x00;
  }

  // GoodInput (bytes 178-181) — not used for output nodes
  // GoodOutputA (bytes 182-185)
  for (uint8_t i = 0; i < NUM_OUTPUTS && i < 4; i++) {
    if (outputs[i].type == OUTPUT_OFF) continue;
    uint8_t flags = 0x80;  // bit 7 = data is being transmitted
    if (outputActive[i]) flags |= 0x01;  // merge in progress / data received
    reply[182 + i] = flags;
  }

  // SwIn (bytes 186-189) — not used
  // SwOut (bytes 190-193) — output universe per port (low nibble)
  for (uint8_t i = 0; i < NUM_OUTPUTS && i < 4; i++) {
    reply[190 + i] = outputs[i].universe & 0x0F;
  }

  // SwVideo, SwMacro, SwRemote (bytes 194-196)
  // Spare1-3 (bytes 197-199)
  // Style (byte 200): 0x00 = StNode
  reply[200] = 0x00;

  // MAC address (bytes 201-206)
  uint8_t mac[6];
  WiFi.macAddress(mac);
  memcpy(&reply[201], mac, 6);

  // BindIp (bytes 207-210) — same as device IP
  reply[207] = myIP[0]; reply[208] = myIP[1];
  reply[209] = myIP[2]; reply[210] = myIP[3];

  // BindIndex (byte 211)
  reply[211] = 1;

  // Status2 (byte 212): supports 15-bit port address, DHCP capable
  reply[212] = 0x08;

  // GoodOutputB (bytes 213-216) — continuous output style
  for (uint8_t i = 0; i < NUM_OUTPUTS && i < 4; i++) {
    if (outputs[i].type != OUTPUT_OFF)
      reply[213 + i] = 0xC0;  // continuous output, RDM disabled
  }

  // Status3 (byte 217)
  reply[217] = 0x00;

  // Remaining bytes 218-238 are filler (already zeroed)

  // Send the reply
  udp.beginPacket(dest, ARTNET_PORT);
  udp.write(reply, sizeof(reply));
  udp.endPacket();

  Serial.print("ArtPollReply sent to ");
  Serial.println(dest);
}

void broadcastArtPollReply() {
  sendArtPollReply(IPAddress(255, 255, 255, 255));
}

// =====================================================================
//  Art-Net ArtAddress — remote naming (opcode 0x6000)
// =====================================================================

void handleArtAddress(uint8_t* data, uint16_t len) {
  if (len < 107) return;

  // Short name at bytes 14-31 (18 chars, null-terminated)
  char newName[18] = {0};
  memcpy(newName, data + 14, 17);
  newName[17] = '\0';

  if (newName[0] != '\0') {
    strncpy(customShortName, newName, 17);
    customShortName[17] = '\0';
    hasCustomName = true;
    prefs.putString("shortName", customShortName);
    Serial.print("ArtAddress: name set to \"");
    Serial.print(customShortName);
    Serial.println("\"");

    // Update TFT header to show new name
    setDisplayName(customShortName);
  }

  // Respond with ArtPollReply per spec
  broadcastArtPollReply();
}

// =====================================================================
//  ArtOutputConfig — remote output type assignment (opcode 0x8100)
// =====================================================================

void handleArtOutputConfig(uint8_t* data, uint16_t len) {
  // Packet layout: [Art-Net header 8][opcode 2][version 2][num_outputs 1][type0 1][type1 1]...
  if (len < 13) return;
  uint8_t numOut = data[12];
  if (numOut > NUM_OUTPUTS) numOut = NUM_OUTPUTS;
  if (len < (uint16_t)(13 + numOut)) return;

  bool changed = false;
  for (uint8_t i = 0; i < numOut; i++) {
    uint8_t typeId = data[13 + i];
    if (typeId >= NUM_OUTPUT_TYPES) continue;
    OutputType newType = (OutputType)typeId;
    if (!profileSupportsOutputType(newType)) continue;
    if (outputs[i].type != newType) {
      outputs[i].type = newType;
      deriveFromType(outputs[i]);
      // Clear the buffer for this output
      memset(outputBuffers[i], 0, MAX_BUFFER_SIZE);
      outputDataReady[i] = false;
      changed = true;
      Serial.print("Output ");
      Serial.print(i);
      Serial.print(" -> ");
      Serial.print(typeName(newType));
      Serial.print(" (");
      Serial.print(outputs[i].pixelCount);
      Serial.println("px)");
    }
  }

  if (changed) {
    activeOutputCount = countActiveOutputs(outputs);
    if (!validateReceiveMode(currentReceiveMode, outputs)) {
      applyReceiveMode(outputs, RECEIVE_MODE_SPLIT, currentUniverseBase);
      saveReceiveMode(prefs);
    } else {
      applyReceiveMode(outputs, currentReceiveMode, currentUniverseBase);
    }
    saveOutputConfig();
    // Broadcast updated ArtPollReply so sender sees new config
    broadcastArtPollReply();
  }
}

// =====================================================================
//  ArtIPConfig — remote static/DHCP IP assignment (opcode 0x8200)
// =====================================================================

void handleArtIPConfig(uint8_t* data, uint16_t len) {
  // Packet layout: [Art-Net header 8][opcode 2][version 2][mode 1][ip 4][gateway 4][subnet 4]
  // mode: 0 = DHCP, 1 = static
  if (len < 25) return;

  uint8_t mode = data[12];

  if (mode == 0) {
    // Revert to DHCP
    useStaticIP = false;
    prefs.remove("staticIP");
    prefs.remove("gateway");
    prefs.remove("subnet");
    Serial.println("ArtIPConfig: reverted to DHCP — rebooting...");
    broadcastArtPollReply();
    delay(200);
    ESP.restart();
  } else if (mode == 1) {
    // Set static IP
    memcpy(storedIP, data + 13, 4);
    memcpy(storedGateway, data + 17, 4);
    memcpy(storedSubnet, data + 21, 4);
    useStaticIP = true;

    prefs.putBytes("staticIP", storedIP, 4);
    prefs.putBytes("gateway", storedGateway, 4);
    prefs.putBytes("subnet", storedSubnet, 4);

    Serial.print("ArtIPConfig: static IP set to ");
    printIpBytes(storedIP);
    Serial.println();
    Serial.println("Rebooting...");
    broadcastArtPollReply();
    delay(200);
    ESP.restart();
  }
}

// =====================================================================
//  ArtShowInfo — character/performer names (opcode 0x8210)
// =====================================================================

void sendShowInfoReply(IPAddress dest) {
  uint8_t reply[SHOW_INFO_PACKET_LEN];
  memset(reply, 0, sizeof(reply));
  memcpy(reply, ARTNET_MAGIC, 8);
  reply[8] = (ARTNET_OPCODE_SHOW_INFO) & 0xFF;
  reply[9] = (ARTNET_OPCODE_SHOW_INFO >> 8) & 0xFF;
  reply[10] = 0;
  reply[11] = ARTNET_PROTOCOL_VER;
  reply[12] = SHOW_INFO_MODE_RESPONSE;
  uint8_t charLen = strnlen(showCharacterName, SHOW_INFO_FIELD_LEN);
  uint8_t perfLen = strnlen(showPerformerName, SHOW_INFO_FIELD_LEN);
  reply[13] = charLen;
  memcpy(reply + 14, showCharacterName, charLen);
  reply[78] = perfLen;
  memcpy(reply + 79, showPerformerName, perfLen);

  udp.beginPacket(dest, ARTNET_PORT);
  udp.write(reply, sizeof(reply));
  udp.endPacket();
}

void handleArtShowInfo(uint8_t* data, uint16_t len, IPAddress remoteAddr) {
  if (len < SHOW_INFO_PACKET_LEN) return;

  uint8_t mode = data[12];
  if (mode == SHOW_INFO_MODE_READ) {
    sendShowInfoReply(remoteAddr);
    return;
  }

  if (mode != SHOW_INFO_MODE_WRITE) return;

  char newCharacter[SHOW_INFO_FIELD_LEN + 1] = {0};
  char newPerformer[SHOW_INFO_FIELD_LEN + 1] = {0};
  uint8_t charLen = data[13];
  if (charLen > SHOW_INFO_FIELD_LEN) charLen = SHOW_INFO_FIELD_LEN;
  if (charLen > 0) {
    memcpy(newCharacter, data + 14, charLen);
    newCharacter[charLen] = '\0';
  }
  uint8_t perfLen = data[78];
  if (perfLen > SHOW_INFO_FIELD_LEN) perfLen = SHOW_INFO_FIELD_LEN;
  if (perfLen > 0) {
    memcpy(newPerformer, data + 79, perfLen);
    newPerformer[perfLen] = '\0';
  }

  strncpy(showCharacterName, newCharacter, SHOW_INFO_FIELD_LEN);
  showCharacterName[SHOW_INFO_FIELD_LEN] = '\0';
  strncpy(showPerformerName, newPerformer, SHOW_INFO_FIELD_LEN);
  showPerformerName[SHOW_INFO_FIELD_LEN] = '\0';
  prefs.putString("characterName", showCharacterName);
  prefs.putString("performerName", showPerformerName);

  Serial.print("ArtShowInfo write stored: character=\"");
  Serial.print(showCharacterName);
  Serial.print("\" performer=\"");
  Serial.print(showPerformerName);
  Serial.println("\"");

  sendShowInfoReply(remoteAddr);
}

// =====================================================================
//  Art-Net Packet Router — branch on opcode
// =====================================================================

void processArtNetPacket(uint8_t* data, uint16_t len, IPAddress remoteAddr) {
  if (len < 10) return;

  // Verify Art-Net magic
  if (memcmp(data, ARTNET_MAGIC, ARTNET_HEADER_LEN) != 0) return;

  // Read opcode (little-endian at bytes 8-9)
  uint16_t opcode = (uint16_t)data[8] | ((uint16_t)data[9] << 8);

  if (opcode == ARTNET_OPCODE_POLL) {
    // ArtPoll — respond with ArtPollReply
    sendArtPollReply(remoteAddr);
    return;
  }

  if (opcode == ARTNET_OPCODE_ADDRESS) {
    // ArtAddress — remote naming
    handleArtAddress(data, len);
    return;
  }

  if (opcode == ARTNET_OPCODE_OUTPUT_CONFIG) {
    // ArtOutputConfig — remote output type assignment
    handleArtOutputConfig(data, len);
    return;
  }

  if (opcode == ARTNET_OPCODE_IP_CONFIG) {
    // ArtIPConfig — remote static/DHCP IP assignment
    handleArtIPConfig(data, len);
    return;
  }

  if (opcode == ARTNET_OPCODE_SHOW_INFO) {
    // ArtShowInfo — character/performer names
    handleArtShowInfo(data, len, remoteAddr);
    return;
  }

  if (opcode == ARTNET_OPCODE_RECEIVE_CONFIG) {
    if (handleArtReceiveConfig(prefs, outputs, outputBuffers, outputDataReady, data, len)) {
      activeOutputCount = countActiveOutputs(outputs);
      broadcastArtPollReply();
    }
    return;
  }

  if (opcode != ARTNET_OPCODE_DMX) return;

  // ── ArtDmx handling (unchanged) ──────────────────────────────────
  if (len < ARTNET_DATA_OFFSET) return;

  // Extract sequence (byte 12)
  uint8_t seq = data[12];

  // Extract universe (little-endian at bytes 14-15)
  uint16_t universe = (uint16_t)data[14] | ((uint16_t)data[15] << 8);

  // Extract data length (big-endian at bytes 16-17)
  uint16_t dataLen = ((uint16_t)data[16] << 8) | data[17];
  if ((uint16_t)(ARTNET_DATA_OFFSET + dataLen) > len) {
    dataLen = len - ARTNET_DATA_OFFSET;
  }

  uint8_t* pixelData = data + ARTNET_DATA_OFFSET;
  unsigned long now = millis();
  packetCount++;

  handleArtDmxForReceiveMode(outputs, outputBuffers, outputDataReady, outputActive,
                             outputLastPacket, frameState, universe, seq,
                             pixelData, dataLen, now);

  newDataSinceLastShow = true;
}

// =====================================================================
//  LED Update — apply buffered data to NeoPXL8
// =====================================================================

void applyBufferedData() {
  for (uint8_t o = 0; o < NUM_OUTPUTS; o++) {
    if (!outputDataReady[o]) continue;

    uint8_t  port  = outputs[o].pxl8Port;
    uint16_t count = outputs[o].pixelCount;
    uint8_t  bpp   = outputs[o].bytesPerPixel;
    if (bpp != 3 && bpp != 4) {
      outputDataReady[o] = false;
      continue;
    }

    for (uint16_t p = 0; p < count; p++) {
      uint16_t base = p * bpp;
      if ((uint16_t)(base + bpp) > MAX_BUFFER_SIZE) break;
      if (bpp == 4) {
        setStripPixel(port, p, Adafruit_NeoPixel::Color(
          outputBuffers[o][base],     outputBuffers[o][base + 1],
          outputBuffers[o][base + 2], outputBuffers[o][base + 3]));
      } else {
        setStripPixel(port, p, Adafruit_NeoPixel::Color(
          outputBuffers[o][base],     outputBuffers[o][base + 1],
          outputBuffers[o][base + 2]));
      }
    }
    outputDataReady[o] = false;
  }
}

// =====================================================================
//  FPS Back-Channel — send telemetry to sender
// =====================================================================

static const uint8_t FPS_MAGIC[3] = { 'P', 'F', 'P' };

void sendFpsTelemetry(uint16_t measuredFps, uint16_t pktRate) {
  if (!FPS_BACKCHANNEL_ENABLED) return;
  if (!senderKnown || !wifiConnected) return;

  uint8_t buf[7];
  buf[0] = FPS_MAGIC[0];
  buf[1] = FPS_MAGIC[1];
  buf[2] = FPS_MAGIC[2];
  buf[3] = (measuredFps >> 8) & 0xFF;   // big-endian
  buf[4] =  measuredFps       & 0xFF;
  buf[5] = (pktRate >> 8)     & 0xFF;
  buf[6] =  pktRate           & 0xFF;

  udpFps.beginPacket(senderIP, FPS_REPORT_PORT);
  udpFps.write(buf, 7);
  udpFps.endPacket();
}

// =====================================================================
//  Test Animations
// =====================================================================

uint32_t testColor(uint8_t o) {
  switch (o) {
    case 0:  return Adafruit_NeoPixel::Color(255, 0, 0);
    case 1:  return Adafruit_NeoPixel::Color(0, 255, 0);
    case 2:  return Adafruit_NeoPixel::Color(0, 0, 255);
    default: return Adafruit_NeoPixel::Color(255, 255, 255);
  }
}

void runTestAnimations() {
  for (uint8_t o = 0; o < NUM_OUTPUTS; o++) {
    if (outputs[o].type == OUTPUT_OFF) continue;
    uint8_t  port  = outputs[o].pxl8Port;
    uint16_t count = outputs[o].pixelCount;

    switch (testModeIndex) {
      case 0:  clearPort(port, count); break;
      case 1:  // Color Wipe
        if (!wipeDone[o] && wipePos[o] < count) {
          setStripPixel(port, wipePos[o], testColor(o));
          wipePos[o]++;
        } else { wipeDone[o] = true; }
        break;
      case 2:  // White
        for (uint16_t p = 0; p < count; p++)
          setStripPixel(port, p, Adafruit_NeoPixel::Color(255, 255, 255));
        break;
      case 3:  // Rainbow
        for (uint16_t p = 0; p < count; p++) {
          uint16_t hue = rainbowHue[o] + (p * 65536L / count);
          setStripPixel(port, p, Adafruit_NeoPixel::ColorHSV(hue, 255, 255));
        }
        rainbowHue[o] += 512;
        if (rainbowHue[o] >= 65536) rainbowHue[o] -= 65536;
        break;
      case 4:  // March
        clearPort(port, count);
        setStripPixel(port, marchPos[o], testColor(o));
        marchPos[o] = (marchPos[o] + 1) % count;
        break;
    }
  }
  showOutputs();
}

void resetTestState() {
  for (uint8_t o = 0; o < NUM_OUTPUTS; o++) {
    rainbowHue[o] = 0;
    marchPos[o]   = 0;
    wipePos[o]    = 0;
    wipeDone[o]   = false;
    if (outputs[o].type != OUTPUT_OFF)
      clearPort(outputs[o].pxl8Port, outputs[o].pixelCount);
  }
  showOutputs();
}

// =====================================================================
//  Button Handlers
// =====================================================================

void handleScreenCycle() {
  infoScreenIndex = (infoScreenIndex + 1) % NUM_INFO_SCREENS;
  switch (infoScreenIndex) {
    case 0:
      displayConnection(DEFAULT_WIFI_SSID, WiFi.localIP(), wifiConnected,
                        wifiConnected ? WiFi.RSSI() : 0, activeStaticIP);
      break;
    case 1:
      displayStatus(outputs, currentFps, outputActive);
      break;
    case 2:
      if (!wifiConnected)
        displayError("WiFi Lost", "Attempting reconnection...");
      else
        displayError("No Errors", "System running normally");
      break;
#if BOARD_HAS_TFT_DISPLAY
    case 3:
      displayReceiveSettings(outputs, nullptr);
      break;
#endif
  }
}

#if BOARD_HAS_TFT_DISPLAY && BOARD_HAS_BUTTONS
void handleReceiveModeToggle() {
  ReceiveMode next = (currentReceiveMode == RECEIVE_MODE_SPLIT)
    ? RECEIVE_MODE_COMBINED : RECEIVE_MODE_SPLIT;
  if (!validateReceiveMode(next, outputs)) {
    displayReceiveSettings(outputs, "Combined limit exceeded");
    return;
  }
  if (setReceiveMode(prefs, outputs, outputBuffers, outputDataReady,
                      next, currentUniverseBase)) {
    broadcastArtPollReply();
    displayReceiveSettings(outputs, nullptr);
  }
}
#endif

void handleTestToggle() {
  if (!testModeActive) {
    testModeActive = true;
    testModeIndex = 1;
    resetTestState();
    displayTestMode(testModeIndex, testModeNames[testModeIndex]);
  } else {
    testModeIndex++;
    if (testModeIndex >= NUM_TEST_MODES) {
      testModeActive = false;
      testModeIndex = 0;
      resetTestState();
      handleScreenCycle();
    } else {
      resetTestState();
      displayTestMode(testModeIndex, testModeNames[testModeIndex]);
    }
  }
}

// =====================================================================
//  Output idle detection
// =====================================================================

void checkOutputTimeouts() {
  unsigned long now = millis();
  for (uint8_t o = 0; o < NUM_OUTPUTS; o++) {
    if (outputs[o].type == OUTPUT_OFF) continue;
    if (outputActive[o] && (now - outputLastPacket[o] > CONNECTION_TIMEOUT)) {
      outputActive[o] = false;
      displayUpdateOutputActive(o, false, outputs[o].type);
    }
  }
}

// =====================================================================
//  Setup
// =====================================================================

void setup() {
  Serial.begin(115200);
  delay(500);

  Serial.println("=============================");
  Serial.println(FIRMWARE_NAME);
  Serial.print("Firmware v"); Serial.println(FIRMWARE_VERSION);
  Serial.println("Art-Net only · Per-universe");
  Serial.print("Board profile: "); Serial.println(BOARD_PROFILE_LABEL);
  Serial.println("=============================");

  prefs.begin(PERSISTENCE_NAMESPACE, false);

  // Load output config
  loadDefaultConfig(outputs);
  loadStoredOutputConfig();
  loadStoredReceiveMode(prefs, outputs);
  activeOutputCount = countActiveOutputs(outputs);

  Serial.println("Output configuration:");
  for (uint8_t i = 0; i < NUM_OUTPUTS; i++) {
    Serial.print("  Port ");
    Serial.print(outputs[i].pxl8Port);
    Serial.print(": ");
    Serial.print(typeName(outputs[i].type));
    Serial.print(", ");
    Serial.print(outputs[i].pixelCount);
    Serial.print("px, Universe ");
    Serial.println(outputs[i].universe);
  }
  Serial.print("Active outputs: ");
  Serial.println(activeOutputCount);

  // Init buttons + display adapter
  buttonsInit();
  displayInit();
  displayStartup();
  initConnectionIndicator();

  // Init LED output driver
#if BOARD_OUTPUT_DRIVER == PRIMUS_DRIVER_NEOPXL8
  bool needsRGBW = false;
  for (uint8_t i = 0; i < NUM_OUTPUTS; i++) {
    if (outputs[i].bytesPerPixel == 4) { needsRGBW = true; break; }
  }
  neoPixelType pixelType = needsRGBW
    ? (NEO_GRBW + NEO_KHZ800) : (NEO_GRB + NEO_KHZ800);
  leds = new Adafruit_NeoPXL8(MAX_LEDS_PER_PORT, pxl8Pins, pixelType);

  if (!leds->begin()) {
    Serial.println("ERROR: NeoPXL8 begin() failed!");
    displayError("PXL8 FAIL", "NeoPXL8 initialization failed");
    while (1) { delay(100); }
  }

  leds->setBrightness(255);  // locked to max; sender scales RGB for show brightness
  leds->fill(0);
  leds->show();
  Serial.println("NeoPXL8 OK — hardware brightness locked to 255");
#else
  for (uint8_t i = 0; i < NUM_OUTPUTS; i++) {
    uint8_t port = outputs[i].pxl8Port;
    directLeds[port] = new Adafruit_NeoPixel(MAX_LEDS_PER_PORT, outputs[i].dataPin, NEO_GRB + NEO_KHZ800);
    directLeds[port]->begin();
    directLeds[port]->setBrightness(255);  // locked to max; sender scales RGB
    directLeds[port]->clear();
    directLeds[port]->show();
    Serial.print("Direct NeoPixel output ");
    Serial.print(i);
    Serial.print(" on GPIO");
    Serial.println(outputs[i].dataPin);
  }
  Serial.println("Direct NeoPixel outputs OK — hardware brightness locked to 255");
#endif

  // Connect WiFi
  loadStoredDeviceName();
  loadStoredShowInfo();

  loadStoredNetworkConfig();

  printStartupConnectionData();

  // Set the TFT header to the custom name (or firmware default)
  setDisplayName(hasCustomName ? customShortName : DEVICE_SHORT_NAME);

  wifiConnected = connectWifi();
  if (wifiConnected) {
    displayConnection(DEFAULT_WIFI_SSID, WiFi.localIP(), true, WiFi.RSSI(), activeStaticIP);
  } else {
    displayError("WiFi Fail", "Could not connect. Retrying...");
  }

  // Init UDP sockets
  udp.begin(ARTNET_PORT);
  udpFps.begin(0);  // ephemeral port for outgoing FPS packets
  Serial.print("Art-Net listening on port ");
  Serial.println(ARTNET_PORT);

  // Broadcast ArtPollReply so discovery tools see us immediately
  if (wifiConnected) {
    broadcastArtPollReply();
  }

  lastFpsTime  = millis();
  lastShowTime = millis();

  Serial.println("Setup complete. D0=Screen D1=Test");
  Serial.println();
}

// =====================================================================
//  Main Loop
// =====================================================================

void loop() {
  unsigned long now = millis();

  // ── Buttons ──────────────────────────────────────────────────────
  buttonsPoll();

  if (btnScreenCycle) { btnScreenCycle = false; handleScreenCycle(); }
#if BOARD_HAS_TFT_DISPLAY && BOARD_HAS_BUTTONS
  if (btnTestToggle)  {
    btnTestToggle = false;
    if (infoScreenIndex == 3) handleReceiveModeToggle();
    else handleTestToggle();
  }
#elif BOARD_HAS_BUTTONS
  if (btnTestToggle)  { btnTestToggle  = false; handleTestToggle();  }
#endif

  if (testModeActive) {
    runTestAnimations();
    delay(33);
    return;
  }

  // ── WiFi health ──────────────────────────────────────────────────
  checkWifiConnection();

  // ── Drain all pending Art-Net packets ────────────────────────────
  int pktSize;
  while ((pktSize = udp.parsePacket()) > 0) {
    if (pktSize > MAX_UDP_PACKET) {
      while (udp.available()) udp.read();
      continue;
    }
    int bytesRead = udp.read(udpBuf, pktSize);
    if (bytesRead > 0) {
      IPAddress remoteAddr = udp.remoteIP();
      // Track sender IP for UDP 6455 telemetry (ignore broadcast/multicast)
      if (remoteAddr[0] != 0 && remoteAddr[0] < 224) {
        senderIP = remoteAddr;
        senderKnown = true;
      }
      processArtNetPacket(udpBuf, bytesRead, remoteAddr);
    }
  }

  // ── Frame assembly timeout ───────────────────────────────────────
  if (!frameState.ready && frameState.univCount > 0 &&
      (now - frameState.firstArrival >= FRAME_ASSEMBLY_TIMEOUT)) {
    frameState.ready = true;  // partial frame — show what we have
  }

  // ── Apply data + adaptive-rate show ──────────────────────────────
  if (newDataSinceLastShow && frameState.ready &&
      (now - lastShowTime >= showInterval)) {
    applyBufferedData();

    unsigned long t0 = micros();
    showOutputs();
    unsigned long t1 = micros();
    showDuration = t1 - t0;
    showInterval = (showDuration / 1000) + 1;  // ms: show time + 1ms margin

    lastShowTime = now;
    newDataSinceLastShow = false;
    frameState.ready = false;
    frameState.univCount = 0;
    frameCount++;
  }

  // ── Output idle detection ────────────────────────────────────────
  checkOutputTimeouts();

#if BOARD_BATTERY_MONITOR
  batteryTelemetryTick(udpFps, senderIP, senderKnown, wifiConnected);
#endif

  // ── FPS reporting (once per second) ──────────────────────────────
  if (now - lastFpsTime >= FPS_INTERVAL) {
    unsigned long elapsed = now - lastFpsTime;
    currentFps = frameCount * 1000.0f / elapsed;
    float packetFps = packetCount * 1000.0f / elapsed;

    Serial.print("FPS: ");
    Serial.print(currentFps, 1);
    Serial.print("  Pkts/s: ");
    Serial.print(packetFps, 1);
    Serial.print("  Show: ");
    Serial.print(showDuration);
    Serial.print("us  Heap: ");
    Serial.print(ESP.getFreeHeap());
    Serial.print("B  RSSI: ");
    Serial.print(WiFi.RSSI());
    Serial.println("dBm");

    // Send FPS telemetry back to sender
    sendFpsTelemetry((uint16_t)currentFps, (uint16_t)packetFps);

    displayUpdateFooter(currentFps, senderKnown ? senderIP : IPAddress(0,0,0,0));

    frameCount  = 0;
    packetCount = 0;
    lastFpsTime = now;
  }
}
