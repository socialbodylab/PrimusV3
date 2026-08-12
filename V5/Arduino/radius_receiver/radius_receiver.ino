/*
 * radius_receiver.ino — Radius Central V4 Audio Receiver
 * ======================================================
 * V1: Feather HUZZAH32 + Music Maker FeatherWing (headless)
 * V2: ESP32-S3 Reverse TFT Feather + Music Maker FeatherWing
 *
 * Art-Net: 0x6000 rename, 0x8200 IP, 0x8210 show info, 0x8220 lane ports,
 *          0x8300 audio, 0x8301 FTP
 * Watch lane (UDP 6455): PFP packet rate, PTR track telemetry (frozen formats),
 *          PRS unified status (battery/flags, 1 Hz), optional 0x8302 audio status
 * OSC port 53001: /cue/N, /stop, /hello
 */

#include <WiFi.h>
#include <WiFiUdp.h>
#include <Preferences.h>
#include <SD.h>

#include "config.h"
#include "display.h"
#if RADIUS_HAS_BUTTONS
#include "buttons.h"
#endif
#include "audio.h"
#include "battery.h"
#include "cues.h"
#include "ftp.h"
#include "telemetry.h"
#include "marius.h"

#if BOARD_HAS_STATUS_NEOPIXEL
#include <Adafruit_NeoPixel.h>
Adafruit_NeoPixel statusPixel(1, BOARD_STATUS_NEOPIXEL_PIN, NEO_GRB + NEO_KHZ800);
#endif

bool sdBusy = false;

#define MAX_UDP_PACKET 600
WiFiUDP udp;      // Discovery lane (ArtPoll) — always 6454, plus dual-listen
WiFiUDP udpShow;  // Show lane (ArtAudioCmd)
WiFiUDP udpSetup; // Setup lane (identity/IP/show-info/FTP gate/lane ports)
WiFiUDP udpFps;
WiFiUDP udpOsc;
uint8_t udpBuf[MAX_UDP_PACKET];

// Discovery is intentionally not NVS-overridable — it is the well-known
// bootstrap port a misconfigured Show/Setup port can always recover through.
uint16_t portDiscovery = PORT_DISCOVERY_DEFAULT;
uint16_t portShow  = PORT_SHOW_DEFAULT;
uint16_t portSetup = PORT_SETUP_DEFAULT;
uint16_t portWatch = PORT_WATCH_DEFAULT;

enum ArtNetLane : uint8_t {
  LANE_DISCOVERY = 0,
  LANE_SHOW      = 1,
  LANE_SETUP     = 2,
};

#define MAX_OSC_PACKET 512
uint8_t oscBuf[MAX_OSC_PACKET];

#define ARTNET_HEADER_LEN  8
static const uint8_t ARTNET_MAGIC[ARTNET_HEADER_LEN] =
  { 'A', 'r', 't', '-', 'N', 'e', 't', '\0' };

bool wifiConnected  = false;
bool wifiConnecting = false;
unsigned long lastReconnectAttempt = 0;
unsigned long wifiConnectStart     = 0;
unsigned long lastWifiCheckMs      = 0;

bool statusIndicatorConnected = false;
bool statusIndicatorStaticIP = false;
bool statusIndicatorLit = false;
unsigned long lastStatusIndicatorBlink = 0;
static const unsigned long STATUS_INDICATOR_BLINK_INTERVAL = 500;

IPAddress senderIP;
bool senderKnown = false;

Preferences prefs;
char customShortName[18] = {0};
bool hasCustomName = false;

char showCharacterName[SHOW_INFO_FIELD_LEN + 1] = {0};
char showPerformerName[SHOW_INFO_FIELD_LEN + 1] = {0};

bool useStaticIP = false;
bool activeStaticIP = false;
uint8_t storedIP[4]      = {0};
uint8_t storedGateway[4] = {0};
uint8_t storedSubnet[4]  = {0};

unsigned long lastFpsTime = 0;
unsigned long lastTrackHeartbeatMs = 0;
unsigned long packetCount = 0;
uint8_t infoScreenIndex = 0;

// PRS unified status back-channel state
uint16_t statusSequence = 0;
unsigned long nextStatusReportMs = 0;
unsigned long lastTestToneMs = 0;

#if RADIUS_DIAG
unsigned long diagLoopMaxUs = 0;
unsigned long diagWindowStartMs = 0;
#endif

static const uint8_t FPS_MAGIC[3] = { 'P', 'F', 'P' };
static const uint8_t TRACK_MAGIC[3] = { 'P', 'T', 'R' };

void printIpBytes(const uint8_t* bytes) {
  Serial.print(bytes[0]); Serial.print(".");
  Serial.print(bytes[1]); Serial.print(".");
  Serial.print(bytes[2]); Serial.print(".");
  Serial.print(bytes[3]);
}

void loadStoredDeviceName() {
  bool applyOverrides = false;
#ifdef PRIMUSV3_OVERRIDE_BUILD_ID
  applyOverrides = prefs.getString("fwOvrBuild", "") != String(PRIMUSV3_OVERRIDE_BUILD_ID);
#endif

#ifdef PRIMUSV3_FORCE_DEVICE_NAME_OVERRIDE
  if (applyOverrides) {
    strncpy(customShortName, DEVICE_SHORT_NAME, sizeof(customShortName) - 1);
    customShortName[sizeof(customShortName) - 1] = '\0';
    hasCustomName = customShortName[0] != '\0';
    if (hasCustomName) {
      prefs.putString("shortName", customShortName);
    }
    Serial.print("Firmware name override seeded: \"");
    Serial.print(customShortName);
    Serial.println("\"");
    return;
  }
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
  bool applyOverrides = false;
#ifdef PRIMUSV3_OVERRIDE_BUILD_ID
  applyOverrides = prefs.getString("fwOvrBuild", "") != String(PRIMUSV3_OVERRIDE_BUILD_ID);
#endif

#ifdef PRIMUSV3_FORCE_CHARACTER_NAME_OVERRIDE
  if (applyOverrides) {
    strncpy(showCharacterName, DEFAULT_SHOW_CHARACTER_NAME, SHOW_INFO_FIELD_LEN);
    showCharacterName[SHOW_INFO_FIELD_LEN] = '\0';
    prefs.putString("characterName", showCharacterName);
    Serial.print("Firmware character name override seeded: \"");
    Serial.print(showCharacterName);
    Serial.println("\"");
  } else
#endif
  {
    if (prefs.isKey("characterName")) {
      String stored = prefs.getString("characterName", "");
      stored.toCharArray(showCharacterName, sizeof(showCharacterName));
    }
  }

#ifdef PRIMUSV3_FORCE_PERFORMER_NAME_OVERRIDE
  if (applyOverrides) {
    strncpy(showPerformerName, DEFAULT_SHOW_PERFORMER_NAME, SHOW_INFO_FIELD_LEN);
    showPerformerName[SHOW_INFO_FIELD_LEN] = '\0';
    prefs.putString("performerName", showPerformerName);
    Serial.print("Firmware performer name override seeded: \"");
    Serial.print(showPerformerName);
    Serial.println("\"");
  } else
#endif
  {
    if (prefs.isKey("performerName")) {
      String stored = prefs.getString("performerName", "");
      stored.toCharArray(showPerformerName, sizeof(showPerformerName));
    }
  }

  if (applyOverrides) {
#ifdef PRIMUSV3_OVERRIDE_BUILD_ID
    prefs.putString("fwOvrBuild", String(PRIMUSV3_OVERRIDE_BUILD_ID));
    Serial.println("Firmware overrides applied for this build.");
#endif
  } else {
    if (!prefs.isKey("characterName")) {
      showCharacterName[0] = '\0';
      prefs.putString("characterName", showCharacterName);
    }
    if (!prefs.isKey("performerName")) {
      strncpy(showPerformerName, DEFAULT_SHOW_PERFORMER_NAME, SHOW_INFO_FIELD_LEN);
      showPerformerName[SHOW_INFO_FIELD_LEN] = '\0';
      prefs.putString("performerName", showPerformerName);
    }
  }

  if (showCharacterName[0] != '\0' || showPerformerName[0] != '\0') {
    Serial.print("Loaded show info: character=\"");
    Serial.print(showCharacterName);
    Serial.print("\" performer=\"");
    Serial.print(showPerformerName);
    Serial.println("\"");
  }
}

void loadStoredNetworkConfig() {
#ifdef PRIMUSV3_FORCE_DHCP_OVERRIDE
  useStaticIP = false;
  prefs.remove("staticIP");
  prefs.remove("gateway");
  prefs.remove("subnet");
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
  return;
#endif

  if (prefs.isKey("staticIP")) {
    size_t ipLen = prefs.getBytes("staticIP", storedIP, 4);
    size_t gwLen = prefs.getBytes("gateway", storedGateway, 4);
    size_t snLen = prefs.getBytes("subnet", storedSubnet, 4);
    if (ipLen == 4 && gwLen == 4 && snLen == 4) {
      useStaticIP = true;
    }
  }
}

// ── UDP lane ports (Show / Setup / Watch) — stored in NVS ────────────
// Discovery is fixed at PORT_DISCOVERY_DEFAULT and is never part of this set.
bool validUdpLanePort(uint16_t port) {
  return port != 0 && port >= 1024;
}

bool validLanePortSet(uint16_t show, uint16_t setup, uint16_t watch) {
  return validUdpLanePort(show) && validUdpLanePort(setup) && validUdpLanePort(watch) &&
         show != setup && show != watch && setup != watch;
}

void loadStoredLanePorts() {
  uint16_t show  = prefs.getUShort("portShow", PORT_SHOW_DEFAULT);
  uint16_t setup = prefs.getUShort("portSetup", PORT_SETUP_DEFAULT);
  uint16_t watch = prefs.getUShort("portWatch", PORT_WATCH_DEFAULT);
  if (!validLanePortSet(show, setup, watch)) {
    show  = PORT_SHOW_DEFAULT;
    setup = PORT_SETUP_DEFAULT;
    watch = PORT_WATCH_DEFAULT;
  }
  portShow  = show;
  portSetup = setup;
  portWatch = watch;
}

bool saveLanePorts(uint16_t show, uint16_t setup, uint16_t watch) {
  if (!validLanePortSet(show, setup, watch)) return false;
  if (prefs.putUShort("portShow", show) != sizeof(uint16_t) ||
      prefs.putUShort("portSetup", setup) != sizeof(uint16_t) ||
      prefs.putUShort("portWatch", watch) != sizeof(uint16_t)) {
    return false;
  }
  portShow  = show;
  portSetup = setup;
  portWatch = watch;
  return true;
}

void resetLanePortsToDefaults() {
  saveLanePorts(PORT_SHOW_DEFAULT, PORT_SETUP_DEFAULT, PORT_WATCH_DEFAULT);
}

void buildNodeReport(char* reportBuf, size_t reportLen) {
  // Canonical token order (highest survival priority first):
  //   OK|PVRAD1|B:<board>|F:<features>|IP:<S/D>|<moved-lane tokens>|V:<ver>|MC:/MP:
  // The Node Report is a hard 64-byte Art-Net field. Each token below is
  // appended only when it fits whole — a truncated "|MGMT:645" still parses
  // as a plausible port and would black-hole all Setup traffic (guard pattern
  // copied from primusV3_receiver.ino buildNodeReport).
  int pos = snprintf(reportBuf, reportLen, "#0001 [%04d] OK|%s|B:%s|F:%s",
                     (int)packetCount, NODE_CAPS_PREFIX, NODE_CAPS_BOARD,
                     NODE_CAPS_FEATURES);
  if (pos < 0 || (size_t)pos >= (int)reportLen) return;

  {
    int tokenLen = snprintf(nullptr, 0, "|IP:%c", useStaticIP ? 'S' : 'D');
    if (pos + tokenLen < (int)reportLen) {
      pos += snprintf(reportBuf + pos, reportLen - pos, "|IP:%c",
                      useStaticIP ? 'S' : 'D');
    }
  }

  // Lane ports: advertise only a lane that has been moved off its compiled
  // default. The full triple alone is ~28 bytes and would crowd out every
  // token after it; the sender assumes the documented defaults (and falls
  // back to dual-listen on 6454) when a token is absent.
  {
    const struct { const char* tag; uint16_t value; uint16_t deflt; } laneTokens[] = {
      { "AUD",  portShow,  PORT_SHOW_DEFAULT  },
      { "MGMT", portSetup, PORT_SETUP_DEFAULT },
      { "TELE", portWatch, PORT_WATCH_DEFAULT },
    };
    for (uint8_t i = 0; i < 3 && pos < (int)reportLen - 1; i++) {
      if (laneTokens[i].value == laneTokens[i].deflt) continue;
      int tokenLen = snprintf(nullptr, 0, "|%s:%u", laneTokens[i].tag,
                              (unsigned)laneTokens[i].value);
      if (pos + tokenLen >= (int)reportLen) break;
      pos += snprintf(reportBuf + pos, reportLen - pos, "|%s:%u",
                      laneTokens[i].tag, (unsigned)laneTokens[i].value);
    }
  }

  {
    int tokenLen = snprintf(nullptr, 0, "|V:%s", FIRMWARE_VERSION);
    if (pos + tokenLen < (int)reportLen) {
      pos += snprintf(reportBuf + pos, reportLen - pos, "|V:%s", FIRMWARE_VERSION);
    }
  }

  // Marius tokens last — nothing operationally critical parses them, and the
  // puck name is the one unbounded field, so it must never displace the rest.
  if (mariusIsConfigured()) {
    bool connected = mariusIsConnected();
    int tokenLen = snprintf(nullptr, 0, "|MC:%c", connected ? '1' : '0');
    if (pos + tokenLen < (int)reportLen) {
      pos += snprintf(reportBuf + pos, reportLen - pos, "|MC:%c",
                      connected ? '1' : '0');
    }
    if (connected) {
      int mpLen = snprintf(nullptr, 0, "|MP:%s", mariusPuckName());
      if (pos + mpLen < (int)reportLen) {
        pos += snprintf(reportBuf + pos, reportLen - pos, "|MP:%s", mariusPuckName());
      }
    }
  }
}

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
  if (connected != statusIndicatorConnected || activeStaticIP != statusIndicatorStaticIP) {
    setConnectionIndicator(connected);
    return;
  }
  if (connected && !activeStaticIP && millis() - lastStatusIndicatorBlink >= STATUS_INDICATOR_BLINK_INTERVAL) {
    lastStatusIndicatorBlink = millis();
    writeConnectionIndicator(!statusIndicatorLit);
  }
}

void startWifiConnect() {
#ifdef PRIMUSV3_FORCE_WIFI_CREDENTIAL_OVERRIDE
  static bool clearedStoredWifiCredentials = false;
  if (!clearedStoredWifiCredentials) {
    WiFi.persistent(false);
    WiFi.disconnect(true, true);
    clearedStoredWifiCredentials = true;
  }
#endif

  WiFi.mode(WIFI_STA);
  activeStaticIP = false;

  if (useStaticIP) {
    IPAddress localIP(storedIP[0], storedIP[1], storedIP[2], storedIP[3]);
    IPAddress gateway(storedGateway[0], storedGateway[1], storedGateway[2], storedGateway[3]);
    IPAddress subnet(storedSubnet[0], storedSubnet[1], storedSubnet[2], storedSubnet[3]);
    activeStaticIP = WiFi.config(localIP, gateway, subnet);
  }

  WiFi.setSleep(false);
  WiFi.begin(DEFAULT_WIFI_SSID, DEFAULT_WIFI_PASSWORD);
  wifiConnecting = true;
  wifiConnectStart = millis();
  lastReconnectAttempt = millis();
}

void checkWifiConnection() {
  unsigned long now = millis();
  if (now - lastWifiCheckMs < WIFI_CHECK_INTERVAL_MS) return;
  lastWifiCheckMs = now;

  if (WiFi.status() == WL_CONNECTED) {
    if (!wifiConnected) {
      wifiConnected = true;
      wifiConnecting = false;
      WiFi.setSleep(false);
      udp.begin(portDiscovery);
      udpShow.begin(portShow);
      udpSetup.begin(portSetup);
      udpOsc.begin(OSC_PORT);
      broadcastArtPollReply();
      if (infoScreenIndex == 0)
        displayConnection(DEFAULT_WIFI_SSID, WiFi.localIP(), true, WiFi.RSSI());
    }
    return;
  }

  if (wifiConnected) {
    wifiConnected = false;
  }

  if (wifiConnecting) {
    if (now - wifiConnectStart > CONNECTION_TIMEOUT) {
      wifiConnecting = false;
      if (infoScreenIndex == 0)
        displayConnection(DEFAULT_WIFI_SSID, IPAddress(0, 0, 0, 0), false, 0);
    }
    return;
  }

  if (now - lastReconnectAttempt > RECONNECT_INTERVAL) {
    startWifiConnect();
  }
}

void sendArtPollReply(IPAddress dest) {
  uint8_t reply[239];
  memset(reply, 0, sizeof(reply));

  memcpy(reply, ARTNET_MAGIC, 8);
  reply[8] = (ARTNET_OPCODE_POLLREPLY) & 0xFF;
  reply[9] = (ARTNET_OPCODE_POLLREPLY >> 8) & 0xFF;

  IPAddress myIP = WiFi.localIP();
  reply[10] = myIP[0]; reply[11] = myIP[1];
  reply[12] = myIP[2]; reply[13] = myIP[3];

  reply[14] = portDiscovery & 0xFF;
  reply[15] = (portDiscovery >> 8) & 0xFF;

  reply[16] = FIRMWARE_VERSION_H;
  reply[17] = FIRMWARE_VERSION_L;

  reply[20] = (OEM_CODE >> 8) & 0xFF;
  reply[21] = OEM_CODE & 0xFF;
  reply[22] = 0;
  reply[23] = 0xD0;
  reply[24] = ESTA_CODE & 0xFF;
  reply[25] = (ESTA_CODE >> 8) & 0xFF;

  const char* nameToUse = hasCustomName ? customShortName : DEVICE_SHORT_NAME;
  strncpy((char*)&reply[26], nameToUse, 17);
  strncpy((char*)&reply[44], DEVICE_LONG_NAME, 63);

  char reportBuf[64];
  buildNodeReport(reportBuf, sizeof(reportBuf));
  strncpy((char*)&reply[108], reportBuf, 63);

  uint8_t mac[6];
  WiFi.macAddress(mac);
  memcpy(&reply[201], mac, 6);

  reply[207] = myIP[0]; reply[208] = myIP[1];
  reply[209] = myIP[2]; reply[210] = myIP[3];
  reply[211] = 1;
  reply[212] = 0x08;

  udp.beginPacket(dest, portDiscovery);
  udp.write(reply, sizeof(reply));
  udp.endPacket();
}

void broadcastArtPollReply() {
  sendArtPollReply(IPAddress(255, 255, 255, 255));
}

void handleArtAddress(uint8_t* data, uint16_t len) {
  if (len < 107) return;

  char newName[18] = {0};
  memcpy(newName, data + 14, 17);
  newName[17] = '\0';

  if (newName[0] != '\0') {
    strncpy(customShortName, newName, 17);
    customShortName[17] = '\0';
    hasCustomName = true;
    prefs.putString("shortName", customShortName);
    setDisplayName(customShortName);
    Serial.print("ArtAddress rename stored: \"");
    Serial.print(customShortName);
    Serial.println("\"");
  }

  broadcastArtPollReply();
}

void handleArtIPConfig(uint8_t* data, uint16_t len) {
  if (len < 25) return;

  uint8_t mode = data[12];

  if (mode == 0) {
    useStaticIP = false;
    prefs.remove("staticIP");
    prefs.remove("gateway");
    prefs.remove("subnet");
    broadcastArtPollReply();
    delay(200);
    ESP.restart();
  } else if (mode == 1) {
    memcpy(storedIP, data + 13, 4);
    memcpy(storedGateway, data + 17, 4);
    memcpy(storedSubnet, data + 21, 4);
    useStaticIP = true;
    prefs.putBytes("staticIP", storedIP, 4);
    prefs.putBytes("gateway", storedGateway, 4);
    prefs.putBytes("subnet", storedSubnet, 4);
    broadcastArtPollReply();
    delay(200);
    ESP.restart();
  }
}

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

  udp.beginPacket(dest, portDiscovery);
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
  broadcastArtPollReply();
}

void handleArtFtpCmd(uint8_t* data, uint16_t len) {
  if (len < 13) return;
  uint8_t cmd = data[12];

  if (cmd == 1) {
    if (audioIsPlaying()) audioStop();
    ftpStart();
  } else {
    ftpStop();
  }

  if (infoScreenIndex == 3)
    displayFtpStatus(ftpIsRunning(), WiFi.localIP(), sdFileCount());
}

// ArtLanePorts (0x8220) — vendor opcode to move the Show/Setup/Watch lane
// ports. Layout: Art-Net header + opcode LE + ProtVer BE, then three
// big-endian uint16 fields: portShow, portSetup, portWatch.
void handleArtLanePorts(uint8_t* data, uint16_t len) {
  if (len < 18) return;

  uint16_t newShow  = ((uint16_t)data[12] << 8) | data[13];
  uint16_t newSetup = ((uint16_t)data[14] << 8) | data[15];
  uint16_t newWatch = ((uint16_t)data[16] << 8) | data[17];

  if (!validLanePortSet(newShow, newSetup, newWatch)) {
    Serial.println("ArtLanePorts rejected: invalid port set");
    return;
  }

  bool showOrSetupChanged = newShow != portShow || newSetup != portSetup;
  if (!saveLanePorts(newShow, newSetup, newWatch)) {
    Serial.println("ArtLanePorts rejected: NVS save failed");
    return;
  }

  if (showOrSetupChanged) {
    udpShow.stop();
    udpShow.begin(portShow);
    udpSetup.stop();
    udpSetup.begin(portSetup);
  }

  Serial.print("Lane ports updated: show=");
  Serial.print(portShow);
  Serial.print(" setup=");
  Serial.print(portSetup);
  Serial.print(" watch=");
  Serial.println(portWatch);

  broadcastArtPollReply();
}

void sendAudioStatus(uint8_t status, const char* filename) {
  if (!senderKnown || !wifiConnected) return;
  uint8_t buf[46];
  memset(buf, 0, sizeof(buf));
  memcpy(buf, ARTNET_MAGIC, 8);
  buf[8]  = ARTNET_OPCODE_AUDIO_STATUS & 0xFF;
  buf[9]  = (ARTNET_OPCODE_AUDIO_STATUS >> 8) & 0xFF;
  buf[10] = 0x00;
  buf[11] = 0x0E;
  buf[12] = status;
  if (filename && filename[0]) strncpy((char*)&buf[13], filename, 32);
  udpFps.beginPacket(senderIP, portWatch);
  udpFps.write(buf, 46);
  udpFps.endPacket();
}

// Test tone wrapper — records the trigger time so the PRS status packet can
// flag "test tone active" (sineTest blocks ~700 ms, so the 1 Hz status tick
// can never observe it directly). Do NOT call audioSetVolume() immediately
// before this: sineTest() resets the VS1053 and an SCI write while DREQ is
// low can be dropped and corrupt chip state.
void runAudioTestTone() {
  lastTestToneMs = millis();
  audioTestTone();
}

bool testToneRecentlyActive() {
  return lastTestToneMs != 0 && (millis() - lastTestToneMs) < 2000UL;
}

void handleArtAudioCmd(uint8_t* data, uint16_t len) {
  if (len < 15) return;

  uint8_t cmd = data[12];
  uint8_t volume = data[13];
  char filename[33] = {0};
  uint16_t fnLen = len - 14;
  if (fnLen > 32) fnLen = 32;
  memcpy(filename, data + 14, fnLen);

  uint16_t duration = 0;
  uint16_t nullPos = 14;
  while (nullPos < len && data[nullPos] != 0) nullPos++;
  if (len >= nullPos + 3) {
    duration = (uint16_t)data[nullPos + 1] | ((uint16_t)data[nullPos + 2] << 8);
  }

  Serial.print("[ArtAudio] cmd=");
  Serial.print(cmd);
  Serial.print(" vol=");
  Serial.print(volume);
  if (cmd == 1 || cmd == 2) {
    Serial.print(" file=");
    Serial.print(filename);
    if (duration > 0) {
      Serial.print(" dur=");
      Serial.print(duration);
      Serial.print("s");
    }
  }
  if (cmd == 6 || cmd == 7) {
    Serial.print(" cue=");
    Serial.print(volume);
  }
  Serial.println();

  if (ftpIsRunning()) {
    ftpStop();
    if (infoScreenIndex == 3)
      displayFtpStatus(false, WiFi.localIP(), sdFileCount());
  }

  switch (cmd) {
    case 1:  audioPlay(filename, volume, duration); break;
    case 2:  audioLoop(filename, volume, duration); break;
    case 3:  audioPause(); break;
    case 4:  audioSetVolume(volume); break;
    case 5:
      // No audioSetVolume() before the tone — see runAudioTestTone(). Show the
      // TEST TONE screen before the blocking sineTest so the display sequences
      // correctly (active during, idle after).
      if (infoScreenIndex == 2)
        displayAudioStatus("TEST TONE", _audioVolume, true);
      runAudioTestTone();
      break;
    case 6:
    case 7: {
      AudioCue cue;
      if (cueLookup(volume, &cue)) {
        if (cmd == 6) audioPlay(cue.filename, _audioVolume, cue.duration);
        else          audioLoop(cue.filename, _audioVolume, cue.duration);
      } else {
        Serial.printf("[ArtAudio] Cue %d not found\n", volume);
      }
      break;
    }
    default: audioStop(); break;
  }

  sendAudioStatus(audioIsPlaying() ? 1 : 0, audioCurrentFile());
  if (infoScreenIndex == 2) {
    if (cmd == 5)
      displayAudioStatus("TEST TONE", _audioVolume, false);
    else
      displayAudioStatus(audioCurrentFile(), _audioVolume, audioIsPlaying());
  }
}

void dispatchOscCue(uint8_t cueNum) {
  AudioCue cue;
  if (!cueLookup(cueNum, &cue)) return;
  audioPlay(cue.filename, _audioVolume, cue.duration);
  sendAudioStatus(audioIsPlaying() ? 1 : 0, audioCurrentFile());
  if (infoScreenIndex == 2)
    displayAudioStatus(audioCurrentFile(), _audioVolume, audioIsPlaying());
}

void handleOscPacket() {
  int len = udpOsc.parsePacket();
  if (len <= 0) return;
  if (len > MAX_OSC_PACKET) { udpOsc.flush(); return; }
  int n = udpOsc.readBytes((char*)oscBuf, len);
  if (n < 2 || oscBuf[0] != '/') return;
  oscBuf[n < MAX_OSC_PACKET ? n : MAX_OSC_PACKET - 1] = '\0';
  const char* addr = (const char*)oscBuf;

  if (strcmp(addr, "/stop") == 0) {
    audioStop();
    sendAudioStatus(0, "");
    if (infoScreenIndex == 2)
      displayAudioStatus(audioCurrentFile(), _audioVolume, audioIsPlaying());
    return;
  }

  if (strcmp(addr, "/hello") == 0 || strcmp(addr, "/radius/hello") == 0
      || strcmp(addr, "/primus/hello") == 0) {
    runAudioTestTone();
    if (infoScreenIndex == 2)
      displayAudioStatus("TEST TONE", _audioVolume, true);
    return;
  }

  if (strncmp(addr, "/cue/", 5) == 0) {
    int cueNum = atoi(addr + 5);
    if (cueNum <= 0 || cueNum > 255) return;
    dispatchOscCue((uint8_t)cueNum);
    return;
  }
}

void processArtNetPacket(uint8_t* data, uint16_t len, IPAddress remoteAddr, uint8_t lane) {
  if (len < 10) return;
  if (memcmp(data, ARTNET_MAGIC, ARTNET_HEADER_LEN) != 0) return;

  uint16_t opcode = (uint16_t)data[8] | ((uint16_t)data[9] << 8);
  packetCount++;

  // Re-latch senderIP whenever a direct command opcode arrives from a new
  // address — these only ever come from the actual controlling sender, so
  // telemetry follows a Central whose IP changed instead of sticking to the
  // first packet ever seen. ArtPoll deliberately does NOT re-latch: WiFiUDP
  // cannot distinguish a unicast poll from a broadcast one (no destination-IP
  // API), and a broadcast discovery sweep from a passive tool must not steal
  // the telemetry stream. First-packet latching in the drain loops still
  // bootstraps senderIP before any command arrives.
  if (opcode == ARTNET_OPCODE_AUDIO_CMD || opcode == ARTNET_OPCODE_FTP_CMD) {
    if (!senderKnown || senderIP != remoteAddr) {
      senderIP = remoteAddr;
      senderKnown = true;
    }
  }

  // ArtPoll is Discovery-lane only. Radius must never accept ArtDmx on any
  // lane, so there is deliberately no opcode case for it anywhere below.
  if (opcode == ARTNET_OPCODE_POLL) {
    if (lane != LANE_DISCOVERY) return;
    sendArtPollReply(remoteAddr);
    return;
  }

  // ArtAudioCmd is the Show lane; dual-listen also accepts it on Discovery
  // (6454) while legacy V5 senders still target the bootstrap port.
  if (opcode == ARTNET_OPCODE_AUDIO_CMD) {
    if (lane != LANE_SHOW && !(PORT_DUAL_LISTEN && lane == LANE_DISCOVERY)) return;
    handleArtAudioCmd(data, len);
    return;
  }

  // Setup opcodes (identity, IP, show info, FTP gate, lane-port config) live
  // on the Setup lane; dual-listen also accepts them on Show or Discovery
  // while senders migrate to the dedicated Setup lane.
  bool isSetupOpcode = opcode == ARTNET_OPCODE_ADDRESS ||
                       opcode == ARTNET_OPCODE_IP_CONFIG ||
                       opcode == ARTNET_OPCODE_SHOW_INFO ||
                       opcode == ARTNET_OPCODE_FTP_CMD ||
                       opcode == ARTNET_OPCODE_LANE_PORTS;
  if (isSetupOpcode) {
    if (lane != LANE_SETUP && !PORT_DUAL_LISTEN) return;

    if (opcode == ARTNET_OPCODE_ADDRESS) {
      handleArtAddress(data, len);
    } else if (opcode == ARTNET_OPCODE_IP_CONFIG) {
      handleArtIPConfig(data, len);
    } else if (opcode == ARTNET_OPCODE_SHOW_INFO) {
      handleArtShowInfo(data, len, remoteAddr);
    } else if (opcode == ARTNET_OPCODE_FTP_CMD) {
      handleArtFtpCmd(data, len);
    } else if (opcode == ARTNET_OPCODE_LANE_PORTS) {
      handleArtLanePorts(data, len);
    }
    return;
  }
}

void sendTrackTelemetry(uint8_t state, const char* filename) {
  if (!TRACK_TELEMETRY_ENABLED) return;
  if (!senderKnown || !wifiConnected) return;

  const char* track = filename ? filename : "";
  size_t nameLen = strlen(track);
  if (nameLen > 64) nameLen = 64;

  uint8_t buf[5 + 64];
  buf[0] = TRACK_MAGIC[0];
  buf[1] = TRACK_MAGIC[1];
  buf[2] = TRACK_MAGIC[2];
  buf[3] = state;
  buf[4] = (uint8_t)nameLen;
  if (nameLen > 0) memcpy(buf + 5, track, nameLen);

  udpFps.beginPacket(senderIP, portWatch);
  udpFps.write(buf, 5 + nameLen);
  udpFps.endPacket();
}

void sendFpsTelemetry(uint16_t pktRate) {
  if (!FPS_BACKCHANNEL_ENABLED) return;
  if (!senderKnown || !wifiConnected) return;

  uint8_t buf[7];
  buf[0] = FPS_MAGIC[0];
  buf[1] = FPS_MAGIC[1];
  buf[2] = FPS_MAGIC[2];
  buf[3] = 0;
  buf[4] = 0;
  buf[5] = (pktRate >> 8) & 0xFF;
  buf[6] = pktRate & 0xFF;

  udpFps.beginPacket(senderIP, portWatch);
  udpFps.write(buf, 7);
  udpFps.endPacket();
}

// ── PRS unified status packet — Watch lane, 1 Hz ─────────────────────
// 17 bytes: 'P','R','S', version=1, seq u16 BE (wraps; reboot detection),
// uptime seconds u32 BE, flags u16 BE, RSSI int8, battery power mode u8,
// battery mV u16 BE, battery pct (255 = n/a).
// PTR and PFP stay byte-for-byte frozen; PRS is purely additive.
#define RADIUS_STATUS_PROTOCOL_VERSION 1
#define RADIUS_STATUS_PACKET_LEN       17
#define RSTATUS_WIFI_CONNECTED    0x0001
#define RSTATUS_STATIC_IP         0x0002
#define RSTATUS_TEST_TONE_ACTIVE  0x0008
#define RSTATUS_BATTERY_VALID     0x0080
#define RSTATUS_SD_READY          0x0100
#define RSTATUS_FTP_RUNNING       0x0200
#define RSTATUS_AUDIO_PLAYING     0x0400
#define RSTATUS_AUDIO_LOOPING     0x0800
#define RSTATUS_MARIUS_CONFIGURED 0x1000
#define RSTATUS_MARIUS_CONNECTED  0x2000

void sendRadiusStatus() {
  if (!senderKnown || !wifiConnected) return;

  uint16_t flags = 0;
  if (wifiConnected)            flags |= RSTATUS_WIFI_CONNECTED;
  if (activeStaticIP)           flags |= RSTATUS_STATIC_IP;
  if (testToneRecentlyActive()) flags |= RSTATUS_TEST_TONE_ACTIVE;
  if (radiusBatteryIsValid())   flags |= RSTATUS_BATTERY_VALID;
  if (audioSdIsReady())         flags |= RSTATUS_SD_READY;
  if (ftpIsRunning())           flags |= RSTATUS_FTP_RUNNING;
  if (audioIsPlaying())         flags |= RSTATUS_AUDIO_PLAYING;
  if (_audioLooping)            flags |= RSTATUS_AUDIO_LOOPING;
  if (mariusIsConfigured())     flags |= RSTATUS_MARIUS_CONFIGURED;
  if (mariusIsConnected())      flags |= RSTATUS_MARIUS_CONNECTED;

  uint32_t uptimeS = millis() / 1000UL;

  uint8_t buf[RADIUS_STATUS_PACKET_LEN] = {0};
  buf[0]  = 'P';
  buf[1]  = 'R';
  buf[2]  = 'S';
  buf[3]  = RADIUS_STATUS_PROTOCOL_VERSION;
  buf[4]  = (statusSequence >> 8) & 0xFF;
  buf[5]  = statusSequence & 0xFF;
  buf[6]  = (uptimeS >> 24) & 0xFF;
  buf[7]  = (uptimeS >> 16) & 0xFF;
  buf[8]  = (uptimeS >> 8) & 0xFF;
  buf[9]  = uptimeS & 0xFF;
  buf[10] = (flags >> 8) & 0xFF;
  buf[11] = flags & 0xFF;
  buf[12] = (uint8_t)(int8_t)WiFi.RSSI();
  buf[13] = radiusBatteryStatus.powerMode;
  buf[14] = (radiusBatteryStatus.batteryMv >> 8) & 0xFF;
  buf[15] = radiusBatteryStatus.batteryMv & 0xFF;
  buf[16] = radiusBatteryStatus.batteryPct;
  statusSequence++;  // u16 wraps by design

  udpFps.beginPacket(senderIP, portWatch);
  udpFps.write(buf, sizeof(buf));
  udpFps.endPacket();
}

void telemetryHeartbeat() {
  if (!TRACK_TELEMETRY_ENABLED) return;
  if (!audioIsPlaying()) return;

  unsigned long now = millis();
  if (now - lastTrackHeartbeatMs < TRACK_HEARTBEAT_MS) return;
  lastTrackHeartbeatMs = now;

  sendTrackTelemetry(audioPlaybackState(), audioCurrentFile());
}

#if RADIUS_HAS_BUTTONS
void handleScreenCycle() {
  uint8_t maxScreens = mariusIsConfigured() ? NUM_INFO_SCREENS + 1 : NUM_INFO_SCREENS;
  infoScreenIndex = (infoScreenIndex + 1) % maxScreens;
  switch (infoScreenIndex) {
    case 0:
      displayConnection(DEFAULT_WIFI_SSID, WiFi.localIP(), wifiConnected,
                        wifiConnected ? WiFi.RSSI() : 0);
      break;
    case 1:
      if (!wifiConnected)
        displayError("WiFi Lost", "Attempting reconnection...");
      else
        displayError("No Errors", "System running normally");
      break;
    case 2:
      displayAudioStatus(audioCurrentFile(), _audioVolume, audioIsPlaying());
      break;
    case 3:
      displayFtpStatus(ftpIsRunning(), WiFi.localIP(), sdFileCount());
      break;
    default:
      break;
  }
}

void handleD1Press() {
  switch (infoScreenIndex) {
    case 2:
      // Show TEST TONE before the blocking sineTest, revert to idle after.
      displayAudioStatus("TEST TONE", _audioVolume, true);
      runAudioTestTone();
      displayAudioStatus("TEST TONE", _audioVolume, false);
      break;
    case 3:
      if (ftpIsRunning()) ftpStop();
      else {
        if (audioIsPlaying()) audioStop();
        ftpStart();
      }
      displayFtpStatus(ftpIsRunning(), WiFi.localIP(), sdFileCount());
      break;
    default:
      break;
  }
}
#endif  // RADIUS_HAS_BUTTONS

void setup() {
  Serial.begin(115200);
  delay(500);

  Serial.println(FIRMWARE_NAME);
  Serial.print("Firmware v"); Serial.println(FIRMWARE_VERSION);

#if RADIUS_HAS_BUTTONS
  buttonsInit();
#endif
  initConnectionIndicator();
  displayInit();
  displayStartup();

  prefs.begin("artnet", false);
  loadStoredLanePorts();
  loadStoredDeviceName();
  loadStoredShowInfo();
  loadStoredNetworkConfig();
  setDisplayName(hasCustomName ? customShortName : DEVICE_SHORT_NAME);

  startWifiConnect();
  displayConnection(DEFAULT_WIFI_SSID, IPAddress(0, 0, 0, 0), false, 0);

  udp.begin(portDiscovery);
  udpShow.begin(portShow);
  udpSetup.begin(portSetup);
  udpFps.begin(0);
  Serial.print("Discovery lane listening on port "); Serial.println(portDiscovery);
  Serial.print("Show lane listening on port ");      Serial.println(portShow);
  Serial.print("Setup lane listening on port ");     Serial.println(portSetup);

  audioInit();
  cuesLoad();
  ftpInit(SD);

  mariusLoad();
  if (mariusIsConfigured()) mariusInit();

  lastFpsTime = millis();

  // PRS cadence: 1 Hz with MAC-derived boot jitter (so a rack of receivers
  // does not burst in phase) plus a +500 ms offset so the PRS tick lands
  // anti-phase to the PTR/PFP 1-second tick above.
  uint8_t statusMac[6];
  WiFi.macAddress(statusMac);
  uint16_t statusJitterMs =
    (((uint16_t)statusMac[4] << 8) | statusMac[5]) % 251;
  nextStatusReportMs = millis() + 500UL + statusJitterMs;
}

void loop() {
#if RADIUS_DIAG
  unsigned long diagLoopStartUs = micros();
#endif

  audioUpdate();
  ftpUpdate();
  mariusUpdate();
  // Refill the VS1053 FIFO right after Marius — BLE housekeeping can take
  // long enough that waiting for the next full loop pass risks a dropout.
  audioUpdate();

  {
    static bool wasAudioActive = false;
    bool isAudioActive = audioIsPlaying();
    if (wasAudioActive && !isAudioActive) {
      sendAudioStatus(0, "");
      sendTrackTelemetry(TRACK_STATE_STOPPED, "");
    }
    wasAudioActive = isAudioActive;
  }

  int pktSize;

  // ── Drain Discovery lane (ArtPoll, + dual-listen for legacy 6454) ────
  while ((pktSize = udp.parsePacket()) > 0) {
    if (pktSize > MAX_UDP_PACKET) {
      while (udp.available()) udp.read();
      continue;
    }
    int bytesRead = udp.read(udpBuf, pktSize);
    if (bytesRead > 0) {
      IPAddress remoteAddr = udp.remoteIP();
      if (!senderKnown) {
        senderIP = remoteAddr;
        senderKnown = true;
      }
      processArtNetPacket(udpBuf, bytesRead, remoteAddr, LANE_DISCOVERY);
    }
  }

  // ── Drain Show lane (ArtAudioCmd) ────────────────────────────────────
  while ((pktSize = udpShow.parsePacket()) > 0) {
    if (pktSize > MAX_UDP_PACKET) {
      while (udpShow.available()) udpShow.read();
      continue;
    }
    int bytesRead = udpShow.read(udpBuf, pktSize);
    if (bytesRead > 0) {
      IPAddress remoteAddr = udpShow.remoteIP();
      if (!senderKnown) {
        senderIP = remoteAddr;
        senderKnown = true;
      }
      processArtNetPacket(udpBuf, bytesRead, remoteAddr, LANE_SHOW);
    }
  }

  // ── Drain Setup lane (identity/IP/show-info/FTP gate/lane ports) ────
  while ((pktSize = udpSetup.parsePacket()) > 0) {
    if (pktSize > MAX_UDP_PACKET) {
      while (udpSetup.available()) udpSetup.read();
      continue;
    }
    int bytesRead = udpSetup.read(udpBuf, pktSize);
    if (bytesRead > 0) {
      IPAddress remoteAddr = udpSetup.remoteIP();
      if (!senderKnown) {
        senderIP = remoteAddr;
        senderKnown = true;
      }
      processArtNetPacket(udpBuf, bytesRead, remoteAddr, LANE_SETUP);
    }
  }

  handleOscPacket();
  // Refill the VS1053 FIFO again after the UDP drain loops — a burst of
  // packets (FTP gate, cue storm) can hold the loop long enough to matter.
  audioUpdate();
  checkWifiConnection();
  syncConnectionIndicator();

#if RADIUS_HAS_BUTTONS
  buttonsPoll();
  if (btnScreenCycle) { btnScreenCycle = false; handleScreenCycle(); }
  if (btnD1)          { btnD1 = false; handleD1Press(); }
#endif

  telemetryHeartbeat();

  unsigned long now = millis();
  if (now - lastFpsTime >= FPS_INTERVAL) {
    unsigned long elapsed = now - lastFpsTime;
    float pktRate = packetCount * 1000.0f / (elapsed > 0 ? elapsed : 1);

    sendFpsTelemetry((uint16_t)pktRate);
    displayUpdateFooter(pktRate, senderKnown ? senderIP : IPAddress(0, 0, 0, 0));

    packetCount = 0;
    lastFpsTime = now;
  }

  // PRS status tick — anti-phase to the PTR/PFP tick above (see setup()).
  // Battery sampling is exactly one ADC one-shot per second; it runs even
  // before a sender is known so the EMA is warm when telemetry starts.
  if ((long)(now - nextStatusReportMs) >= 0) {
    radiusBatterySample(wifiConnected);
    sendRadiusStatus();
    nextStatusReportMs += 1000UL;
    if ((long)(now - nextStatusReportMs) >= 1000L) {
      // Catch-up clamp: after a stall (sineTest, WiFi reconnect) resume the
      // cadence from now instead of bursting missed packets.
      nextStatusReportMs = now + 1000UL;
    }
  }

#if RADIUS_DIAG
  // Loop-time instrumentation: worst single loop() pass per 1 s window.
  // Verification target: loopMaxUs stays below ~8000 µs during playback
  // (VS1053 FIFO drains in ~11.6 ms; keep feed gaps under ~10 ms).
  {
    unsigned long diagLoopUs = micros() - diagLoopStartUs;
    if (diagLoopUs > diagLoopMaxUs) diagLoopMaxUs = diagLoopUs;
    if (now - diagWindowStartMs >= 1000) {
      Serial.printf("[Diag] loopMaxUs=%lu\n", diagLoopMaxUs);
      diagLoopMaxUs = 0;
      diagWindowStartMs = now;
    }
  }
#endif
}
