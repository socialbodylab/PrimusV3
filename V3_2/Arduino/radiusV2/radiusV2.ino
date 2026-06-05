/*
 * primusV3_audio_receiver.ino — PrimusV3 Audio Receiver
 * =====================================================
 * Dedicated audio node — ESP32-S3 Reverse TFT Feather + Audio BFF or
 * Music Maker FeatherWing. No LED / NeoPXL8 output — LED nodes are
 * separate V3.1 hardware.
 *
 * Receives Art-Net audio commands (opcode 0x8200) and FTP commands
 * (opcode 0x8201). Responds to ArtPoll and ArtAddress.
 *
 * Audio command packet (opcode 0x8200):
 *   [0-7]  "Art-Net\0"
 *   [8-9]  0x00, 0x82      — opcode LE
 *   [10-11] 0x00, 0x0E     — protocol version 14
 *   [12]   command         — 0=stop, 1=play, 2=loop, 3=pause, 4=volume
 *   [13]   volume          — 0–100
 *   [14..N] filename       — null-terminated, max 32 chars (e.g. "cue01.wav")
 *
 * Libraries: Adafruit_ST7789, Adafruit_GFX,
 *            Adafruit VS1053 Library (Music Maker) or ESP8266Audio (BFF),
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
#include "ftp.h"

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
WiFiUDP udpFps;
uint8_t udpBuf[MAX_UDP_PACKET];

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

// ── Packet telemetry ─────────────────────────────────────────────────
unsigned long lastFpsTime  = 0;
unsigned long packetCount  = 0;

// ── Screen cycling ───────────────────────────────────────────────────
uint8_t infoScreenIndex = 0;

// =====================================================================
//  WiFi
// =====================================================================

void startWifiConnect() {
  IPAddress localIP(DEFAULT_STATIC_IP);
  IPAddress gateway(DEFAULT_GATEWAY);
  IPAddress subnet(DEFAULT_SUBNET);
  WiFi.config(localIP, gateway, subnet);
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
      Serial.print("WiFi connected! IP: ");
      Serial.println(WiFi.localIP());
      udp.begin(ARTNET_PORT);
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

  char reportBuf[64];
  snprintf(reportBuf, sizeof(reportBuf), "#0001 [%04d] PrimusV3-Audio OK",
           (int)packetCount);
  strncpy((char*)&reply[108], reportBuf, 63);

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
//  ArtFtpCmd (opcode 0x8201)
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
//  ArtAudioCmd (opcode 0x8200)
// =====================================================================

void handleArtAudioCmd(uint8_t* data, uint16_t len) {
  if (len < 15) return;

  uint8_t cmd    = data[12];
  uint8_t volume = data[13];
  char filename[33] = {0};
  uint16_t fnLen = len - 14;
  if (fnLen > 32) fnLen = 32;
  memcpy(filename, data + 14, fnLen);

  Serial.print("[ArtAudio] cmd=");
  Serial.print(cmd);
  Serial.print(" vol=");
  Serial.print(volume);
  Serial.print(" file=");
  Serial.println(filename);

  switch (cmd) {
    case 1:  audioPlay(filename, volume);  break;
    case 2:  audioLoop(filename, volume);  break;
    case 3:  audioPause();                 break;
    case 4:  audioSetVolume(volume);       break;
    case 5:  audioSetVolume(volume); audioTestTone(); break;
    default: audioStop();                  break;
  }

  if (infoScreenIndex == 2)
    displayAudioStatus(audioCurrentFile(), _audioVolume, audioIsPlaying());
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
//  FPS Back-Channel
// =====================================================================

static const uint8_t FPS_MAGIC[3] = { 'P', 'F', 'P' };

void sendFpsTelemetry(uint16_t pktRate) {
  if (!FPS_BACKCHANNEL_ENABLED) return;
  if (!senderKnown || !wifiConnected) return;

  uint8_t buf[7];
  buf[0] = FPS_MAGIC[0];
  buf[1] = FPS_MAGIC[1];
  buf[2] = FPS_MAGIC[2];
  buf[3] = 0;              // measuredFps high byte (no frames on audio node)
  buf[4] = 0;              // measuredFps low byte
  buf[5] = (pktRate >> 8) & 0xFF;
  buf[6] =  pktRate       & 0xFF;

  udpFps.beginPacket(senderIP, FPS_REPORT_PORT);
  udpFps.write(buf, 7);
  udpFps.endPacket();
}

// =====================================================================
//  Button Handlers
// =====================================================================

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
      audioSdInit();
      displaySdStatus(audioSdIsReady(), sdFileCount());
      break;
  }
}

void handleD1Press() {
  switch (infoScreenIndex) {
    case 2:  // Audio screen — play test tone
      audioTestTone();
      displayAudioStatus("TEST TONE", _audioVolume, true);
      break;
    case 3:  // FTP screen — toggle FTP server
      if (ftpIsRunning()) ftpStop(); else ftpStart();
      displayFtpStatus(ftpIsRunning(), WiFi.localIP(), sdFileCount());
      break;
    case 4:  // SD screen — retry init
      audioSdInit();
      displaySdStatus(audioSdIsReady(), sdFileCount());
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

  // NVS / custom name
  prefs.begin("artnet", false);
  if (prefs.isKey("shortName")) {
    String stored = prefs.getString("shortName", "");
    if (stored.length() > 0) {
      stored.toCharArray(customShortName, sizeof(customShortName));
      hasCustomName = true;
    }
  }
  setDisplayName(hasCustomName ? customShortName : DEVICE_SHORT_NAME);

  // WiFi — non-blocking: kick off connect and continue setup immediately
  startWifiConnect();
  displayConnection(DEFAULT_WIFI_SSID, IPAddress(0,0,0,0), false, 0);

  udp.begin(ARTNET_PORT);
  udpFps.begin(0);

  // Audio
  audioInit();
  audioBootTest();

  // FTP — start immediately at boot; always available
  ftpInit(SD);
  ftpStart();

  lastFpsTime = millis();

  Serial.println("Setup complete. D0=Screen D1=Action(screen-dependent)");
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

  // ── FTP update ───────────────────────────────────────────────────
  ftpUpdate();

  // ── Audio update ─────────────────────────────────────────────────
  audioUpdate();

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

  // ── Packet-rate reporting ─────────────────────────────────────────
  unsigned long now = millis();
  if (now - lastFpsTime >= FPS_INTERVAL) {
    unsigned long elapsed = now - lastFpsTime;
    float pktRate = packetCount * 1000.0f / elapsed;

    Serial.print("P/s: ");
    Serial.print(pktRate, 1);
    Serial.print("  Audio: ");
    Serial.print(audioIsPlaying() ? audioCurrentFile() : "idle");
    Serial.print("  FTP: ");
    Serial.print(ftpIsRunning() ? "ON" : "off");
    Serial.print("  Heap: ");
    Serial.print(ESP.getFreeHeap());
    Serial.print("B  RSSI: ");
    Serial.print(WiFi.RSSI());
    Serial.println("dBm");

    sendFpsTelemetry((uint16_t)pktRate);
    displayUpdateFooter(pktRate, senderKnown ? senderIP : IPAddress(0,0,0,0));

    packetCount = 0;
    lastFpsTime = now;
  }
}
