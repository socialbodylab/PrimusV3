/*
 * primusV3_audio_receiver.ino — PrimusV3 Audio Receiver
 * =====================================================
 * Dedicated audio node — ESP32-S3 Reverse TFT Feather or HUZZAH32
 * + Music Maker FeatherWing. No LED / NeoPXL8 output — LED nodes are
 * separate V3.1 hardware.
 *
 * Receives Art-Net audio commands (opcode 0x8300) and FTP commands
 * (opcode 0x8301). Responds to ArtPoll and ArtAddress.
 *
 * Audio command packet (opcode 0x8300):
 *   [0-7]  "Art-Net\0"
 *   [8-9]  0x00, 0x83      — opcode LE
 *   [10-11] 0x00, 0x0E     — protocol version 14
 *   [12]   command         — 0=stop, 1=play, 2=loop, 3=pause, 4=volume, 6=play cue, 7=loop cue
 *   [13]   volume (0–100) or cue number (cmd 6/7)
 *   [14..N] filename       — null-terminated, max 32 chars (cmd 1/2 only)
 *   [N+1..N+2] duration   — uint16_t LE, seconds, 0=full file (cmd 1/2, optional)
 *
 * Libraries: Adafruit_ST7789, Adafruit_GFX,
 *            Adafruit VS1053 Library (Music Maker),
 *            ArduinoJson (cue map parsing),
 *            SimpleFTPServer (xreef/Mischianti) [Library Manager: "SimpleFTPServer"]
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
#include "marius.h"

// =====================================================================
//  Shared globals (referenced by audio.h and ftp.h via extern)
// =====================================================================
bool sdBusy = false;

// =====================================================================
//  Globals
// =====================================================================

// ── Art-Net ──────────────────────────────────────────────────────────
#define MAX_UDP_PACKET 600
WiFiUDP udp;
WiFiUDP udpReport;
WiFiUDP udpOsc;
uint8_t udpBuf[MAX_UDP_PACKET];

// ── OSC ──────────────────────────────────────────────────────────────
#define MAX_OSC_PACKET 512
uint8_t oscBuf[MAX_OSC_PACKET];

#define ARTNET_HEADER_LEN  8

static const uint8_t ARTNET_MAGIC[ARTNET_HEADER_LEN] =
  { 'A', 'r', 't', '-', 'N', 'e', 't', '\0' };

// ── WiFi ─────────────────────────────────────────────────────────────
bool wifiConnected  = false;
bool wifiConnecting = false;
unsigned long lastReconnectAttempt = 0;
unsigned long wifiConnectStart     = 0;

// ── Sender address ────────────────────────────────────────────────────
IPAddress senderIP;
bool      senderKnown = false;

// ── Custom device name ────────────────────────────────────────────────
Preferences prefs;
char customShortName[18] = {0};
bool hasCustomName = false;

// ── Static IP config (stored in NVS) ─────────────────────────────────
bool    useStaticIP      = false;
uint8_t storedIP[4]      = {0};
uint8_t storedGateway[4] = {0};
uint8_t storedSubnet[4]  = {0};

// ── Packet telemetry ─────────────────────────────────────────────────
unsigned long lastStatusTime = 0;
unsigned long packetCount    = 0;

// ── Screen cycling ───────────────────────────────────────────────────
uint8_t infoScreenIndex = 0;

// ── SD screen file selection ─────────────────────────────────────────
char     sdSelectedFile[33] = {0};
uint16_t sdCachedFileCount  = 0;

// ── Pending cue (non-blocking delay) ─────────────────────────────────
static struct {
  bool          active;
  unsigned long fireAt;  // millis() target
  AudioCue      cue;
} _pendingCue = { false, 0, {} };

// =====================================================================
//  NVS helpers
// =====================================================================

void printIpBytes(const uint8_t* bytes) {
  Serial.print(bytes[0]); Serial.print(".");
  Serial.print(bytes[1]); Serial.print(".");
  Serial.print(bytes[2]); Serial.print(".");
  Serial.print(bytes[3]);
}

void loadStoredNetworkConfig() {
  if (prefs.isKey("staticIP")) {
    size_t ipLen = prefs.getBytes("staticIP", storedIP, 4);
    size_t gwLen = prefs.getBytes("gateway",  storedGateway, 4);
    size_t snLen = prefs.getBytes("subnet",   storedSubnet, 4);
    if (ipLen == 4 && gwLen == 4 && snLen == 4) {
      useStaticIP = true;
      Serial.print("Loaded static IP: ");
      printIpBytes(storedIP);
      Serial.println();
    }
  }
}

// =====================================================================
//  WiFi
// =====================================================================

void startWifiConnect() {
  if (useStaticIP) {
    IPAddress localIP(storedIP[0],      storedIP[1],      storedIP[2],      storedIP[3]);
    IPAddress gateway(storedGateway[0], storedGateway[1], storedGateway[2], storedGateway[3]);
    IPAddress subnet (storedSubnet[0],  storedSubnet[1],  storedSubnet[2],  storedSubnet[3]);
    WiFi.config(localIP, gateway, subnet);
  } else {
    IPAddress localIP(DEFAULT_STATIC_IP);
    IPAddress gateway(DEFAULT_GATEWAY);
    IPAddress subnet(DEFAULT_SUBNET);
    WiFi.config(localIP, gateway, subnet);
  }
  WiFi.begin(DEFAULT_WIFI_SSID, DEFAULT_WIFI_PASSWORD);
  WiFi.setSleep(false);
  wifiConnecting    = true;
  wifiConnectStart  = millis();
  lastReconnectAttempt = millis();
  Serial.println("WiFi connecting (non-blocking)...");
}

void checkWifiConnection() {
  if (WiFi.status() == WL_CONNECTED) {
    if (!wifiConnected) {
      wifiConnected  = true;
      wifiConnecting = false;
      WiFi.setSleep(false);  // must be set after connect — connection process resets it
      Serial.print("WiFi connected! IP: ");
      Serial.println(WiFi.localIP());
      udp.begin(ARTNET_PORT);
      udpOsc.begin(OSC_PORT);
      broadcastArtPollReply();
      if (infoScreenIndex == 0)
        displayConnection(DEFAULT_WIFI_SSID, WiFi.localIP(), true, WiFi.RSSI());
    }
    return;
  }

  // Not connected
  if (wifiConnected) {
    wifiConnected = false;
    Serial.println("WiFi lost.");
  }

  if (wifiConnecting) {
    if (millis() - wifiConnectStart > CONNECTION_TIMEOUT) {
      wifiConnecting = false;
      Serial.println("WiFi connection timed out.");
      if (infoScreenIndex == 0)
        displayConnection(DEFAULT_WIFI_SSID, IPAddress(0,0,0,0), false, 0);
    }
    return;
  }

  if (millis() - lastReconnectAttempt > RECONNECT_INTERVAL) {
    Serial.println("Retrying WiFi...");
    startWifiConnect();
  }
}

// =====================================================================
//  Art-Net ArtPollReply
// =====================================================================

void sendArtPollReply(IPAddress dest) {
  uint8_t reply[239];
  memset(reply, 0, sizeof(reply));

  memcpy(reply, ARTNET_MAGIC, 8);
  reply[8] = (ARTNET_OPCODE_POLLREPLY)       & 0xFF;
  reply[9] = (ARTNET_OPCODE_POLLREPLY >> 8)  & 0xFF;

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

  char reportBuf[128];
  if (mariusIsConfigured() && mariusIsConnected()) {
    snprintf(reportBuf, sizeof(reportBuf),
             "#0001 [%04d] OK|PV3CAP1|F:RIH|IP:%c|MC:1|MP:%s",
             (int)packetCount, useStaticIP ? 'S' : 'D', mariusPuckName());
  } else if (mariusIsConfigured()) {
    snprintf(reportBuf, sizeof(reportBuf),
             "#0001 [%04d] OK|PV3CAP1|F:RIH|IP:%c|MC:0",
             (int)packetCount, useStaticIP ? 'S' : 'D');
  } else {
    snprintf(reportBuf, sizeof(reportBuf),
             "#0001 [%04d] OK|PV3CAP1|F:RIH|IP:%c",
             (int)packetCount, useStaticIP ? 'S' : 'D');
  }
  strncpy((char*)&reply[108], reportBuf, 63);
  reply[171] = '\0';

  // reply[173] = 0  (no LED outputs — already zeroed by memset)

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

// =====================================================================
//  Art-Net ArtAddress (opcode 0x6000)
// =====================================================================

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

// =====================================================================
//  ArtFtpCmd (opcode 0x8301)
// =====================================================================

void handleArtFtpCmd(uint8_t* data, uint16_t len) {
  if (len < 13) return;
  uint8_t cmd = data[12];
  Serial.print("[ArtFTP] cmd=");
  Serial.println(cmd);

  if (cmd == 1) {
    ftpStart();
  } else {
    ftpStop();
  }

  if (infoScreenIndex == 3)
    displayFtpStatus(ftpIsRunning(), WiFi.localIP(), sdFileCount());
}

// =====================================================================
//  ArtAudioCmd (opcode 0x8300)
// =====================================================================

void handleArtAudioCmd(uint8_t* data, uint16_t len) {
  if (len < 15) return;

  uint8_t cmd    = data[12];
  uint8_t volume = data[13];
  char filename[33] = {0};
  uint16_t fnLen = len - 14;
  if (fnLen > 32) fnLen = 32;
  memcpy(filename, data + 14, fnLen);

  // Optional duration: uint16_t LE in the 2 bytes after the filename null terminator
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
    Serial.print(" file="); Serial.print(filename);
    if (duration > 0) { Serial.print(" dur="); Serial.print(duration); Serial.print("s"); }
  }
  if (cmd == 6 || cmd == 7) { Serial.print(" cue="); Serial.print(volume); }
  Serial.println();

  switch (cmd) {
    case 1:  audioPlay(filename, volume, duration); break;
    case 2:  audioLoop(filename, volume, duration); break;
    case 3:  audioPause();                          break;
    case 4:  audioSetVolume(volume);                break;
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
    displayAudioUpdate(audioCurrentFile(), _audioVolume, audioIsPlaying());

  // Report status back to sender for UI update
  sendAudioStatus(audioIsPlaying() ? 1 : 0, audioCurrentFile());
}

// =====================================================================
//  ArtIPConfig — remote static/DHCP IP assignment (opcode 0x8200)
// =====================================================================

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
    memcpy(storedIP,      data + 13, 4);
    memcpy(storedGateway, data + 17, 4);
    memcpy(storedSubnet,  data + 21, 4);
    useStaticIP = true;
    prefs.putBytes("staticIP", storedIP,      4);
    prefs.putBytes("gateway",  storedGateway, 4);
    prefs.putBytes("subnet",   storedSubnet,  4);
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
//  OSC /cue/N, /stop, /hello
// =====================================================================

void executeCue(const AudioCue* cue) {
  uint8_t vol = (cue->volume != CUE_VOLUME_UNSET) ? cue->volume : _audioVolume;
  switch (cue->cmd) {
    case AUDIO_CUE_CMD_PLAY:   audioPlay(cue->filename, vol, cue->duration); break;
    case AUDIO_CUE_CMD_LOOP:   audioLoop(cue->filename, vol, cue->duration); break;
    case AUDIO_CUE_CMD_STOP:   audioStop();              break;
    case AUDIO_CUE_CMD_VOLUME: audioSetVolume(vol);      break;
  }
  if (infoScreenIndex == 2)
    displayAudioUpdate(audioCurrentFile(), _audioVolume, audioIsPlaying());
  sendAudioStatus(audioIsPlaying() ? 1 : 0, audioCurrentFile());
}

void dispatchCue(const AudioCue* cue) {
  if (cue->delay > 0) {
    _pendingCue.cue    = *cue;
    _pendingCue.cue.delay = 0;  // clear so executeCue doesn't re-schedule
    _pendingCue.fireAt = millis() + (unsigned long)cue->delay;
    _pendingCue.active = true;
    Serial.printf("[Cue] Scheduled in %dms\n", cue->delay);
    return;
  }
  executeCue(cue);
}

void handleOscPacket() {
  int len = udpOsc.parsePacket();
  if (len <= 0) return;
  if (len > MAX_OSC_PACKET) { udpOsc.flush(); return; }
  int n = udpOsc.readBytes((char*)oscBuf, len);
  if (n < 2 || oscBuf[0] != '/') return;
  oscBuf[n < MAX_OSC_PACKET ? n : MAX_OSC_PACKET - 1] = '\0';
  const char* addr = (const char*)oscBuf;

  Serial.print("[OSC] "); Serial.println(addr);

  if (strcmp(addr, "/stop") == 0) {
    _pendingCue.active = false;
    audioStop();
    if (infoScreenIndex == 2)
      displayAudioUpdate(audioCurrentFile(), _audioVolume, audioIsPlaying());
    sendAudioStatus(0, "");
    return;
  }

  if (strcmp(addr, "/hello") == 0 || strcmp(addr, "/radius/hello") == 0
      || strcmp(addr, "/primus/hello") == 0) {
    Serial.println("[OSC] Hello — playing test tone");
    audioTestTone();
    if (infoScreenIndex == 2)
      displayAudioUpdate(audioCurrentFile(), _audioVolume, audioIsPlaying());
    return;
  }

  if (strncmp(addr, "/cue/", 5) == 0) {
    int cueNum = atoi(addr + 5);
    if (cueNum <= 0 || cueNum > 255) {
      Serial.printf("[OSC] Invalid cue number: %s\n", addr);
      return;
    }
    AudioCue cue;
    if (!cueLookup((uint8_t)cueNum, &cue)) {
      Serial.printf("[OSC] Cue %d not found — dismissed\n", cueNum);
      return;
    }
    dispatchCue(&cue);
    return;
  }

  Serial.printf("[OSC] Unknown address — dismissed: %s\n", addr);
}

// =====================================================================
//  Art-Net Packet Router
// =====================================================================

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

// =====================================================================
//  SD screen file navigation
// =====================================================================

void sdScreenLoadFile(bool advance) {
  if (!audioSdIsReady()) return;

  char firstFile[33] = {0};
  char afterFile[33] = {0};
  bool seenCurrent   = false;

  File root = SD.open("/");
  if (!root) return;
  while (true) {
    File entry = root.openNextFile();
    if (!entry) break;
    if (!entry.isDirectory()) {
      const char* ext = strrchr(entry.name(), '.');
      if (ext && strcasecmp(ext, ".wav") == 0) {
        const char* n = entry.name();
        if (firstFile[0] == '\0') strncpy(firstFile, n, 32);
        if (advance && seenCurrent && afterFile[0] == '\0') strncpy(afterFile, n, 32);
        if (strcasecmp(n, sdSelectedFile) == 0) seenCurrent = true;
      }
    }
    entry.close();
  }
  root.close();

  if (!advance || sdSelectedFile[0] == '\0') {
    strncpy(sdSelectedFile, firstFile, 32);
  } else if (afterFile[0] != '\0') {
    strncpy(sdSelectedFile, afterFile, 32);
  } else {
    strncpy(sdSelectedFile, firstFile, 32);  // wrap around
  }
  sdSelectedFile[32] = '\0';
}

// =====================================================================
//  ArtAudioStatus — unsolicited playback status to sender (opcode 0x8302)
// =====================================================================

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
  udpReport.beginPacket(senderIP, AUDIO_REPORT_PORT);
  udpReport.write(buf, 46);
  udpReport.endPacket();
}

// =====================================================================
//  Button Handlers
// =====================================================================

void handleScreenCycle() {
  uint8_t maxScreens = mariusIsConfigured() ? NUM_INFO_SCREENS : NUM_INFO_SCREENS - 1;
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
    case 4:
      if (audioSdIsReady() && sdSelectedFile[0] == '\0') {
        sdCachedFileCount = sdFileCount();
        sdScreenLoadFile(false);
      }
      displaySdStatus(audioSdIsReady(), sdCachedFileCount, sdSelectedFile,
                      audioIsPlaying() && sdSelectedFile[0] != '\0' &&
                      strcasecmp(audioCurrentFile(), sdSelectedFile) == 0);
      break;
    case 5: {
      uint8_t ds = mariusIsActive() ? (uint8_t)mariusGetState() : MARIUS_DISPLAY_REVERTED;
      displayMariusStatus(ds, mariusPuckName(), mariusLastEvent());
      break;
    }
  }
}

void handleD1Press() {
  switch (infoScreenIndex) {
    case 2:  // Audio screen — play test tone
      displayAudioStatus("test_tone", _audioVolume, true);  // show playing before blocking call
      audioTestTone();
      displayAudioUpdate(audioCurrentFile(), _audioVolume, audioIsPlaying());
      break;
    case 3:  // FTP screen — toggle FTP server
      if (ftpIsRunning()) ftpStop(); else ftpStart();
      displayFtpStatus(ftpIsRunning(), WiFi.localIP(), sdFileCount());
      break;
    case 4:  // SD screen — play/stop selected file (or retry init if SD missing)
      if (!audioSdIsReady()) {
        audioSdInit();
        if (audioSdIsReady()) {
          sdCachedFileCount = sdFileCount();
          sdScreenLoadFile(false);
          if (!ftpIsRunning()) ftpStart();
        }
      } else if (sdSelectedFile[0] != '\0') {
        bool selectedPlaying = audioIsPlaying() &&
                               strcasecmp(audioCurrentFile(), sdSelectedFile) == 0;
        if (selectedPlaying) {
          audioStop();
          sendAudioStatus(0, "");
        } else {
          audioPlay(sdSelectedFile, _audioVolume);
          sendAudioStatus(audioIsPlaying() ? 1 : 0, audioCurrentFile());
        }
      }
      displaySdStatus(audioSdIsReady(), sdCachedFileCount, sdSelectedFile,
                      audioIsPlaying() && sdSelectedFile[0] != '\0' &&
                      strcasecmp(audioCurrentFile(), sdSelectedFile) == 0);
      break;
    case 5:  // Marius screen — D1 simulates PRESS
      mariusSimulateEvent(MARIUS_EVENT_PRESS);
      break;
    default:
      break;
  }
}

void handleD1Release() {
  switch (infoScreenIndex) {
    case 5:  // Marius screen — D1 release simulates RELEASE
      mariusSimulateEvent(MARIUS_EVENT_RELEASE);
      break;
    default:
      break;
  }
}

void handleD2Press() {
  switch (infoScreenIndex) {
    case 4:  // SD screen — advance to next file
      if (audioSdIsReady() && sdCachedFileCount > 0) {
        sdScreenLoadFile(true);
        displaySdStatus(audioSdIsReady(), sdCachedFileCount, sdSelectedFile,
                        audioIsPlaying() && sdSelectedFile[0] != '\0' &&
                        strcasecmp(audioCurrentFile(), sdSelectedFile) == 0);
      }
      break;
    case 5:  // Marius screen — D2 reverts BLE for this session
      if (mariusIsActive()) mariusRevert();
      displayMariusStatus(MARIUS_DISPLAY_REVERTED, mariusPuckName(), mariusLastEvent());
      break;
    default:
      break;
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
  Serial.println("Art-Net + Audio + FTP");
  Serial.println("=============================");

  buttonsInit();
  displayInit();
  displayStartup();

  // NVS / custom name + network config
  prefs.begin("artnet", false);
  if (prefs.isKey("shortName")) {
    String stored = prefs.getString("shortName", "");
    if (stored.length() > 0) {
      stored.toCharArray(customShortName, sizeof(customShortName));
      hasCustomName = true;
    }
  }
  loadStoredNetworkConfig();
  setDisplayName(hasCustomName ? customShortName : DEVICE_SHORT_NAME);

  // WiFi — non-blocking: kick off connect and continue setup immediately
  startWifiConnect();
  displayConnection(DEFAULT_WIFI_SSID, IPAddress(0,0,0,0), false, 0);

  udp.begin(ARTNET_PORT);
  udpReport.begin(0);

  // Audio
  audioInit();
  cuesLoad();
  audioBootTest();

  // If SD is missing, show the SD error screen immediately so it's obvious
  if (!audioSdIsReady()) displaySdStatus(false, 0);

  // FTP — only start if SD is ready (nothing to serve without it)
  ftpInit();
  if (audioSdIsReady()) ftpStart();

  // Marius BLE — activate if /marius.json is on the SD card
  mariusLoad();
  if (mariusIsConfigured()) mariusInit();

  lastStatusTime = millis();

#if TARGET_BOARD == BOARD_FEATHER_ESP32
  Serial.println("Setup complete. (rv1 — no buttons, no display)");
#else
  Serial.println("Setup complete. D0=Screen D1=Action(screen-dependent)");
#endif
  Serial.println();
}

// =====================================================================
//  Main Loop
// =====================================================================

void loop() {
  // ── Buttons ──────────────────────────────────────────────────────
  buttonsPoll();
  if (btnScreenCycle) { btnScreenCycle = false; handleScreenCycle(); }
  if (btnD1)          { btnD1          = false; handleD1Press();     }
  if (btnD1Release)   { btnD1Release   = false; handleD1Release();   }
  if (btnD2)          { btnD2          = false; handleD2Press();     }

  // ── FTP update ───────────────────────────────────────────────────
  ftpUpdate();

  // ── Marius BLE update ────────────────────────────────────────────
  mariusUpdate();

  // ── Audio update ─────────────────────────────────────────────────
  audioUpdate();

  // ── Pending cue timer ────────────────────────────────────────────
  if (_pendingCue.active && millis() >= _pendingCue.fireAt) {
    _pendingCue.active = false;
    executeCue(&_pendingCue.cue);
  }

  // ── Detect natural end-of-file: report stopped status to sender ──
  {
    static bool wasAudioActive = false;
    bool isAudioActive = (audioCurrentFile()[0] != '\0');
    if (wasAudioActive && !isAudioActive) {
      sendAudioStatus(0, "");
      if (infoScreenIndex == 2)
        displayAudioUpdate(audioCurrentFile(), _audioVolume, audioIsPlaying());
      if (infoScreenIndex == 4)
        displaySdStatus(audioSdIsReady(), sdCachedFileCount, sdSelectedFile, false);
    }
    wasAudioActive = isAudioActive;
  }

  // ── Audio screen live refresh ─────────────────────────────────────
  static unsigned long lastAudioDisplay = 0;
  if (infoScreenIndex == 2 && millis() - lastAudioDisplay > 500) {
    lastAudioDisplay = millis();
    displayAudioUpdate(audioCurrentFile(), _audioVolume, audioIsPlaying());
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
      if (!senderKnown) {
        senderIP    = remoteAddr;
        senderKnown = true;
      }
      processArtNetPacket(udpBuf, bytesRead, remoteAddr);
    }
  }

  // ── OSC packets ──────────────────────────────────────────────────
  handleOscPacket();

  // ── Periodic status / serial diagnostic ──────────────────────────
  unsigned long now = millis();
  if (now - lastStatusTime >= STATUS_INTERVAL) {
    unsigned long elapsed = now - lastStatusTime;
    float pktRate = packetCount * 1000.0f / elapsed;

    Serial.print("P/s: ");
    Serial.print(pktRate, 1);
    Serial.print("  Audio: ");
    Serial.print(audioIsPlaying() ? audioCurrentFile() : "idle");
    Serial.print("  FTP: ");
    Serial.print(ftpIsRunning() ? "ON" : "off");
    if (mariusIsConfigured()) {
      Serial.print("  Marius: ");
      Serial.print(mariusIsConnected() ? mariusPuckName() : (mariusIsActive() ? "scanning" : "reverted"));
    }
    Serial.print("  Heap: ");
    Serial.print(ESP.getFreeHeap());
    Serial.print("B  RSSI: ");
    Serial.print(WiFi.RSSI());
    Serial.println("dBm");

    displayUpdateFooter(pktRate);

    packetCount = 0;
    lastStatusTime = now;
  }
}
