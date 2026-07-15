/*
 * radius_receiver.ino — Radius Central V4 Audio Receiver
 * ======================================================
 * V1: Feather HUZZAH32 + Music Maker FeatherWing (headless)
 * V2: ESP32-S3 Reverse TFT Feather + Music Maker FeatherWing
 *
 * Art-Net: 0x6000 rename, 0x8200 IP, 0x8210 show info, 0x8300 audio, 0x8301 FTP
 * Back-channel UDP 6455: PFP packet rate, PTR track telemetry, optional 0x8302 audio status
 * OSC port 53001: /cue/N, /stop, /hello
 */

#include <WiFi.h>
#include <WiFiUdp.h>
#include <Preferences.h>
#include <SD.h>

#include "config.h"
#include "display.h"
#include "buttons.h"
#include "audio.h"
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
WiFiUDP udp;
WiFiUDP udpFps;
WiFiUDP udpOsc;
uint8_t udpBuf[MAX_UDP_PACKET];

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

void buildNodeReport(char* reportBuf, size_t reportLen) {
  int pos = snprintf(reportBuf, reportLen, "#0001 [%04d] OK|%s|B:%s",
                     (int)packetCount, NODE_CAPS_PREFIX, NODE_CAPS_BOARD);
  if (pos < 0 || (size_t)pos >= reportLen) return;

  if (useStaticIP) {
    pos += snprintf(reportBuf + pos, reportLen - pos, "|IP:S");
  } else {
    pos += snprintf(reportBuf + pos, reportLen - pos, "|IP:D");
  }
  if (pos < 0 || (size_t)pos >= reportLen) return;

  pos += snprintf(reportBuf + pos, reportLen - pos, "|F:%s", NODE_CAPS_FEATURES);
  if (pos < 0 || (size_t)pos >= reportLen) return;

  if (mariusIsConfigured()) {
    if (mariusIsConnected()) {
      snprintf(reportBuf + pos, reportLen - pos, "|MC:1|MP:%s", mariusPuckName());
    } else {
      snprintf(reportBuf + pos, reportLen - pos, "|MC:0");
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
      udp.begin(ARTNET_PORT);
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

  reply[14] = ARTNET_PORT & 0xFF;
  reply[15] = (ARTNET_PORT >> 8) & 0xFF;

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

  udp.beginPacket(dest, ARTNET_PORT);
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
  udpFps.beginPacket(senderIP, AUDIO_REPORT_PORT);
  udpFps.write(buf, 46);
  udpFps.endPacket();
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
    case 5:  audioSetVolume(volume); audioTestTone(); break;
    case 6:
    case 7: {
      AudioCue cue;
      if (cueLookup(volume, &cue)) {
        if (cmd == 6) audioPlay(cue.filename, _audioVolume, cue.duration);
        else          audioLoop(cue.filename, _audioVolume, cue.duration);
      }
      break;
    }
    default: audioStop(); break;
  }

  sendAudioStatus(audioIsPlaying() ? 1 : 0, audioCurrentFile());
  if (infoScreenIndex == 2)
    displayAudioStatus(audioCurrentFile(), _audioVolume, audioIsPlaying());
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
    audioTestTone();
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

void processArtNetPacket(uint8_t* data, uint16_t len, IPAddress remoteAddr) {
  if (len < 10) return;
  if (memcmp(data, ARTNET_MAGIC, ARTNET_HEADER_LEN) != 0) return;

  uint16_t opcode = (uint16_t)data[8] | ((uint16_t)data[9] << 8);
  packetCount++;

  if (opcode == ARTNET_OPCODE_POLL) {
    sendArtPollReply(remoteAddr);
    return;
  }
  if (opcode == ARTNET_OPCODE_ADDRESS) {
    handleArtAddress(data, len);
    return;
  }
  if (opcode == ARTNET_OPCODE_IP_CONFIG) {
    handleArtIPConfig(data, len);
    return;
  }
  if (opcode == ARTNET_OPCODE_SHOW_INFO) {
    handleArtShowInfo(data, len, remoteAddr);
    return;
  }
  if (opcode == ARTNET_OPCODE_AUDIO_CMD) {
    handleArtAudioCmd(data, len);
    return;
  }
  if (opcode == ARTNET_OPCODE_FTP_CMD) {
    handleArtFtpCmd(data, len);
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

  udpFps.beginPacket(senderIP, FPS_REPORT_PORT);
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

  udpFps.beginPacket(senderIP, FPS_REPORT_PORT);
  udpFps.write(buf, 7);
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
      audioTestTone();
      displayAudioStatus("TEST TONE", _audioVolume, true);
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

void setup() {
  Serial.begin(115200);
  delay(500);

  Serial.println(FIRMWARE_NAME);
  Serial.print("Firmware v"); Serial.println(FIRMWARE_VERSION);

  buttonsInit();
  initConnectionIndicator();
  displayInit();
  displayStartup();

  prefs.begin("artnet", false);
  loadStoredDeviceName();
  loadStoredShowInfo();
  loadStoredNetworkConfig();
  setDisplayName(hasCustomName ? customShortName : DEVICE_SHORT_NAME);

  startWifiConnect();
  displayConnection(DEFAULT_WIFI_SSID, IPAddress(0, 0, 0, 0), false, 0);

  udp.begin(ARTNET_PORT);
  udpFps.begin(0);

  audioInit();
  cuesLoad();
  ftpInit(SD);

  mariusLoad();
  if (mariusIsConfigured()) mariusInit();

  lastFpsTime = millis();
}

void loop() {
  audioUpdate();
  ftpUpdate();
  mariusUpdate();

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
      processArtNetPacket(udpBuf, bytesRead, remoteAddr);
    }
  }

  handleOscPacket();
  checkWifiConnection();
  syncConnectionIndicator();

  buttonsPoll();
  if (btnScreenCycle) { btnScreenCycle = false; handleScreenCycle(); }
  if (btnD1)          { btnD1 = false; handleD1Press(); }

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
}
