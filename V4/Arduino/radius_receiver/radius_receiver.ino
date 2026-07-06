/*
 * radius_receiver.ino — Radius Central V4 Audio Receiver
 * ======================================================
 * V1: Feather HUZZAH32 + Adafruit Music Maker FeatherWing (VS1053).
 *
 * Art-Net opcodes:
 *   0x6000  ArtAddress   — rename (NVS)
 *   0x8200  ArtIPConfig  — static IP / DHCP (NVS, reboot)
 *   0x8300  ArtAudioCmd  — play / loop / stop / pause / volume + filename
 *   0x8301  ArtFtpCmd    — start / stop FTP server
 *
 * Back-channel UDP 6455: PFP packet rate, PTR track name + playback state.
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

bool sdBusy = false;

#define MAX_UDP_PACKET 256
WiFiUDP udp;
WiFiUDP udpFps;
uint8_t udpBuf[MAX_UDP_PACKET];

#define ARTNET_HEADER_LEN  8
static const uint8_t ARTNET_MAGIC[ARTNET_HEADER_LEN] =
  { 'A', 'r', 't', '-', 'N', 'e', 't', '\0' };

bool wifiConnected  = false;
bool wifiConnecting = false;
unsigned long lastReconnectAttempt = 0;
unsigned long wifiConnectStart     = 0;
unsigned long lastWifiCheckMs      = 0;

IPAddress senderIP;
bool senderKnown = false;

Preferences prefs;
char customShortName[18] = {0};
bool hasCustomName = false;

bool useStaticIP = false;
bool activeStaticIP = false;
uint8_t storedIP[4]      = {0};
uint8_t storedGateway[4] = {0};
uint8_t storedSubnet[4]  = {0};

unsigned long lastFpsTime = 0;
unsigned long packetCount = 0;
uint8_t infoScreenIndex = 0;

// SD screen state
char sdSelectedFile[65] = {0};
uint16_t sdCachedFileCount = 0;

// ── Pending cue (non-blocking delay) ─────────────────────────────────
static struct {
  bool          active;
  unsigned long fireAt;  // millis() target
  AudioCue      cue;
} _pendingCue = { false, 0, {} };

#if RADIUS_DIAG
unsigned long diagLoopMaxUs = 0;
unsigned long diagWindowStartMs = 0;
#endif

static const uint8_t FPS_MAGIC[3] = { 'P', 'F', 'P' };
static const uint8_t TRACK_MAGIC[3] = { 'P', 'T', 'R' };

// ── NVS / network helpers ────────────────────────────────────────────

void printIpBytes(const uint8_t* bytes) {
  Serial.print(bytes[0]); Serial.print(".");
  Serial.print(bytes[1]); Serial.print(".");
  Serial.print(bytes[2]); Serial.print(".");
  Serial.print(bytes[3]);
}

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
    }
  }
}

void loadStoredNetworkConfig() {
#ifdef PRIMUSV3_FORCE_DHCP_OVERRIDE
  useStaticIP = false;
  prefs.remove("staticIP");
  prefs.remove("gateway");
  prefs.remove("subnet");
  Serial.println("Firmware DHCP override: cleared saved static IP.");
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
  Serial.println();
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
  int pos = snprintf(reportBuf, reportLen, "#0001 [%04d] %s|B:%s",
                     (int)packetCount, NODE_CAPS_PREFIX, NODE_CAPS_BOARD);
  if (pos < 0 || (size_t)pos >= reportLen) return;

  if (useStaticIP) {
    pos += snprintf(reportBuf + pos, reportLen - pos,
                    "|IP:S:%u.%u.%u.%u:%u.%u.%u.%u:%u.%u.%u.%u",
                    storedIP[0], storedIP[1], storedIP[2], storedIP[3],
                    storedGateway[0], storedGateway[1], storedGateway[2], storedGateway[3],
                    storedSubnet[0], storedSubnet[1], storedSubnet[2], storedSubnet[3]);
  } else {
    pos += snprintf(reportBuf + pos, reportLen - pos, "|IP:D");
  }
  if (pos >= 0 && (size_t)pos < reportLen) {
    snprintf(reportBuf + pos, reportLen - pos, "|F:%s", NODE_CAPS_FEATURES);
  }
}

// ── WiFi ─────────────────────────────────────────────────────────────

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
  Serial.println("WiFi connecting (non-blocking)...");
}

void checkWifiConnection() {
  unsigned long now = millis();
  if (now - lastWifiCheckMs < WIFI_CHECK_INTERVAL_MS) return;
  lastWifiCheckMs = now;

  if (WiFi.status() == WL_CONNECTED) {
    if (!wifiConnected) {
      wifiConnected = true;
      wifiConnecting = false;
      Serial.print("WiFi connected! IP: ");
      Serial.println(WiFi.localIP());
      udp.begin(ARTNET_PORT);
      broadcastArtPollReply();
      if (infoScreenIndex == 0)
        displayConnection(DEFAULT_WIFI_SSID, WiFi.localIP(), true, WiFi.RSSI());
    }
    return;
  }

  if (wifiConnected) {
    wifiConnected = false;
    Serial.println("WiFi lost.");
  }

  if (wifiConnecting) {
    if (now - wifiConnectStart > CONNECTION_TIMEOUT) {
      wifiConnecting = false;
      Serial.println("WiFi connection timed out.");
      if (infoScreenIndex == 0)
        displayConnection(DEFAULT_WIFI_SSID, IPAddress(0, 0, 0, 0), false, 0);
    }
    return;
  }

  if (now - lastReconnectAttempt > RECONNECT_INTERVAL) {
    Serial.println("Retrying WiFi...");
    startWifiConnect();
  }
}

// ── Art-Net ArtPollReply ─────────────────────────────────────────────

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

// ── ArtAddress (0x6000) ────────────────────────────────────────────

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
    Serial.print("ArtAddress: name set to \"");
    Serial.print(customShortName);
    Serial.println("\"");
    setDisplayName(customShortName);
  }

  broadcastArtPollReply();
}

// ── ArtIPConfig (0x8200) ─────────────────────────────────────────────

void handleArtIPConfig(uint8_t* data, uint16_t len) {
  if (len < 25) return;

  uint8_t mode = data[12];

  if (mode == 0) {
    useStaticIP = false;
    prefs.remove("staticIP");
    prefs.remove("gateway");
    prefs.remove("subnet");
    Serial.println("ArtIPConfig: reverted to DHCP — rebooting...");
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
    Serial.print("ArtIPConfig: static IP set to ");
    printIpBytes(storedIP);
    Serial.println(" — rebooting...");
    broadcastArtPollReply();
    delay(200);
    ESP.restart();
  }
}

// ── ArtFtpCmd (0x8301) ───────────────────────────────────────────────

void handleArtFtpCmd(uint8_t* data, uint16_t len) {
  if (len < 13) return;
  uint8_t cmd = data[12];

  if (cmd == 1) {
    if (audioIsPlaying()) {
      Serial.println("[ArtFTP] Stopping audio to start FTP");
      audioStop();
    }
    ftpStart();
  } else {
    ftpStop();
  }

  if (infoScreenIndex == 3)
    displayFtpStatus(ftpIsRunning(), WiFi.localIP(), sdFileCount());
}

// ── ArtAudioCmd (0x8300) ─────────────────────────────────────────────

void executeCue(const AudioCue* cue) {
  uint8_t vol = (cue->volume != CUE_VOLUME_UNSET) ? cue->volume : _audioVolume;
  switch (cue->cmd) {
    case AUDIO_CUE_CMD_PLAY:   audioPlay(cue->filename, vol, cue->duration); break;
    case AUDIO_CUE_CMD_LOOP:   audioLoop(cue->filename, vol, cue->duration); break;
    case AUDIO_CUE_CMD_STOP:   audioStop();              break;
    case AUDIO_CUE_CMD_VOLUME: audioSetVolume(vol);      break;
  }
  if (infoScreenIndex == 2)
    displayAudioStatus(audioCurrentFile(), _audioVolume, audioIsPlaying());
}

void dispatchCue(const AudioCue* cue) {
  if (cue->delay > 0) {
    _pendingCue.cue       = *cue;
    _pendingCue.cue.delay = 0;  // clear so executeCue doesn't re-schedule
    _pendingCue.fireAt    = millis() + (unsigned long)cue->delay;
    _pendingCue.active    = true;
    Serial.printf("[Cue] Scheduled in %dms\n", cue->delay);
    return;
  }
  executeCue(cue);
}

void handleArtAudioCmd(uint8_t* data, uint16_t len) {
  if (len < 15) return;

  uint8_t cmd = data[12];
  uint8_t volume = data[13];
  char filename[65] = {0};
  uint16_t fnLen = len - 14;
  if (fnLen > 64) fnLen = 64;
  memcpy(filename, data + 14, fnLen);

  uint16_t duration = 0;
  uint16_t delay_ms = 0;
  uint16_t nullPos = 14;
  while (nullPos < len && data[nullPos] != 0) nullPos++;
  if (len >= nullPos + 3) {
    duration = (uint16_t)data[nullPos + 1] | ((uint16_t)data[nullPos + 2] << 8);
  }
  if (len >= nullPos + 5) {
    delay_ms = (uint16_t)data[nullPos + 3] | ((uint16_t)data[nullPos + 4] << 8);
  }

  if (ftpIsRunning()) {
    ftpStop();
    if (infoScreenIndex == 3)
      displayFtpStatus(false, WiFi.localIP(), sdFileCount());
  }

  switch (cmd) {
    case 1:
    case 2: {
      if (delay_ms > 0) {
        AudioCue cue;
        cue.cmd      = (cmd == 2) ? AUDIO_CUE_CMD_LOOP : AUDIO_CUE_CMD_PLAY;
        strncpy(cue.filename, filename, 64); cue.filename[64] = '\0';
        cue.volume   = volume;
        cue.duration = duration;
        cue.delay    = delay_ms;
        dispatchCue(&cue);
      } else if (cmd == 1) {
        audioPlay(filename, volume, duration);
      } else {
        audioLoop(filename, volume, duration);
      }
      break;
    }
    case 3:  audioPause();                           break;
    case 4:  audioSetVolume(volume);                 break;
    case 5:  audioSetVolume(volume); audioTestTone(); break;
    case 6:
    case 7: {
      AudioCue cue;
      if (cueLookup(volume, &cue)) {
        if (cmd == 7) cue.cmd = AUDIO_CUE_CMD_LOOP;
        dispatchCue(&cue);
      } else {
        Serial.printf("[ArtAudio] Cue %d not found\n", volume);
      }
      break;
    }
    default: _pendingCue.active = false; audioStop(); break;
  }

  if (infoScreenIndex == 2)
    displayAudioStatus(audioCurrentFile(), _audioVolume, audioIsPlaying());
}

// ── Art-Net router ───────────────────────────────────────────────────

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
  if (opcode == ARTNET_OPCODE_AUDIO_CMD) {
    handleArtAudioCmd(data, len);
    return;
  }
  if (opcode == ARTNET_OPCODE_FTP_CMD) {
    handleArtFtpCmd(data, len);
    return;
  }
}

// ── Telemetry (UDP 6455) ─────────────────────────────────────────────

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
  if (nameLen > 0) {
    memcpy(buf + 5, track, nameLen);
  }

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

// ── SD screen helpers ────────────────────────────────────────────────

void sdScreenLoadFile() {
  // Advance sdSelectedFile to the next WAV file on the SD card.
  // entry.name() returns just the filename (no leading slash).
  File root = SD.open("/");
  if (!root) return;

  bool foundCurrent = (sdSelectedFile[0] == '\0');
  bool wrapped = false;

  while (true) {
    File entry = root.openNextFile();
    if (!entry) {
      if (!foundCurrent && !wrapped) {
        // Reached end without finding a next — wrap to beginning
        root.rewindDirectory();
        wrapped = true;
        continue;
      }
      break;
    }
    if (entry.isDirectory()) { entry.close(); continue; }
    const char* name = entry.name();
    if (!name) { entry.close(); continue; }
    entry.close();

    if (foundCurrent) {
      strncpy(sdSelectedFile, name, 64);
      sdSelectedFile[64] = '\0';
      break;
    }
    if (strcmp(name, sdSelectedFile) == 0) {
      foundCurrent = true;
    }
  }
  root.close();
}

// ── Buttons ──────────────────────────────────────────────────────────

void handleScreenCycle() {
  infoScreenIndex = (infoScreenIndex + 1) % NUM_INFO_SCREENS;
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
    case 4:
      sdCachedFileCount = sdFileCount();
      if (sdCachedFileCount > 0 && sdSelectedFile[0] == '\0') sdScreenLoadFile();
      displaySdStatus(sdCachedFileCount > 0 || audioIsPlaying(), sdCachedFileCount,
                      sdSelectedFile[0] ? sdSelectedFile : nullptr, audioIsPlaying());
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
      if (ftpIsRunning()) {
        ftpStop();
      } else {
        if (audioIsPlaying()) audioStop();
        ftpStart();
      }
      displayFtpStatus(ftpIsRunning(), WiFi.localIP(), sdFileCount());
      break;
    case 4:
      if (audioIsPlaying()) {
        audioStop();
        displaySdStatus(true, sdCachedFileCount, sdSelectedFile, false);
      } else if (sdSelectedFile[0] != '\0') {
        audioPlay(sdSelectedFile, _audioVolume);
        displaySdStatus(true, sdCachedFileCount, sdSelectedFile, true);
      } else {
        // Retry SD / load first file
        sdCachedFileCount = sdFileCount();
        if (sdCachedFileCount > 0) sdScreenLoadFile();
        displaySdStatus(sdCachedFileCount > 0, sdCachedFileCount,
                        sdSelectedFile[0] ? sdSelectedFile : nullptr, false);
      }
      break;
    default:
      break;
  }
}

void handleD2Press() {
  if (infoScreenIndex != 4) return;
  if (audioIsPlaying()) audioStop();
  sdScreenLoadFile();
  displaySdStatus(true, sdCachedFileCount,
                  sdSelectedFile[0] ? sdSelectedFile : nullptr, false);
}

// ── Setup / loop ─────────────────────────────────────────────────────

void setup() {
  Serial.begin(115200);
  delay(500);

  Serial.println("=============================");
  Serial.println(FIRMWARE_NAME);
  Serial.print("Firmware v"); Serial.println(FIRMWARE_VERSION);
  Serial.println("Radius Central V4 — Art-Net + Audio + FTP");
  Serial.println("=============================");

  buttonsInit();
  displayInit();
  displayStartup();

  prefs.begin("artnet", false);
  loadStoredDeviceName();
  loadStoredNetworkConfig();
  setDisplayName(hasCustomName ? customShortName : DEVICE_SHORT_NAME);

  startWifiConnect();
  displayConnection(DEFAULT_WIFI_SSID, IPAddress(0, 0, 0, 0), false, 0);

  udp.begin(ARTNET_PORT);
  udpFps.begin(0);

  audioInit();
  cuesLoad();
  audioBootTest();
  ftpInit();
  if (audioSdIsReady()) ftpStart();

  lastFpsTime = millis();
#if RADIUS_DIAG
  diagWindowStartMs = millis();
#endif

  Serial.println("Setup complete.");
}

void loop() {
#if RADIUS_DIAG
  unsigned long loopStartUs = micros();
#endif

  // Priority 1: keep VS1053 fed
  audioUpdate();

  // Pending cue delay
  if (_pendingCue.active && millis() >= _pendingCue.fireAt) {
    _pendingCue.active = false;
    executeCue(&_pendingCue.cue);
  }

  // Priority 2: FTP when active
  ftpUpdate();

  // Priority 3: Art-Net (bounded drain)
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

  // Throttled WiFi health
  checkWifiConnection();

  // Buttons
  buttonsPoll();
  if (btnScreenCycle) { btnScreenCycle = false; handleScreenCycle(); }
  if (btnD1)          { btnD1 = false; handleD1Press(); }
  if (btnD2)          { btnD2 = false; handleD2Press(); }

  // Periodic PFP + optional diag
  unsigned long now = millis();
  if (now - lastFpsTime >= FPS_INTERVAL) {
    unsigned long elapsed = now - lastFpsTime;
    float pktRate = packetCount * 1000.0f / (elapsed > 0 ? elapsed : 1);

    sendFpsTelemetry((uint16_t)pktRate);
    displayUpdateFooter(pktRate, senderKnown ? senderIP : IPAddress(0, 0, 0, 0));

#if RADIUS_DIAG
    Serial.print("diag,loop_us_max,heap,min_heap,playing,ftp,pkt_rate:");
    Serial.print(diagLoopMaxUs);
    Serial.print(",");
    Serial.print(ESP.getFreeHeap());
    Serial.print(",");
    Serial.print(ESP.getMinFreeHeap());
    Serial.print(",");
    Serial.print(audioIsPlaying() ? 1 : 0);
    Serial.print(",");
    Serial.print(ftpIsRunning() ? 1 : 0);
    Serial.print(",");
    Serial.println(pktRate, 1);
    diagLoopMaxUs = 0;
    diagWindowStartMs = now;
#endif

    packetCount = 0;
    lastFpsTime = now;
  }

#if RADIUS_DIAG
  unsigned long loopUs = micros() - loopStartUs;
  if (loopUs > diagLoopMaxUs) diagLoopMaxUs = loopUs;
#endif
}
