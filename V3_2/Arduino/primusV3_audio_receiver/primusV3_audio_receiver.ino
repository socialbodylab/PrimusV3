/*
 * primusV3_audio_receiver.ino — PrimusV3 Art-Net LED + Audio Receiver
 * =====================================================================
 * Extends V3.1 with:
 *   - WAV audio playback via custom Art-Net opcode 0x8200
 *   - FTP server for SD card file management (toggle via TFT + D1)
 *   - Two audio board options: Music Maker FeatherWing (VS1053) or
 *     Audio BFF (MAX98357 I2S) — selected in config.h
 *
 * Audio command packet (opcode 0x8200):
 *   [0-7]  "Art-Net\0"     — magic header
 *   [8-9]  0x00, 0x82      — opcode LE
 *   [10-11] 0x00, 0x0E     — protocol version 14
 *   [12]   command         — 0=stop, 1=play, 2=loop, 3=pause
 *   [13]   volume          — 0–100
 *   [14..N] filename       — null-terminated, max 32 chars (e.g. "cue01.wav")
 *
 * Hardware:
 *   - Adafruit ESP32-S3 Reverse TFT Feather
 *   - Adafruit NeoPXL8 Friend (3.3V → 5V level shift)
 *   - Music Maker FeatherWing (VS1053) OR Audio BFF (MAX98357)
 *
 * Libraries: Adafruit_NeoPXL8, Adafruit_ST7789, Adafruit_GFX,
 *            Adafruit VS1053 Library (MM) or ESP8266Audio (BFF),
 *            SimpleFTPServer (xreef/Mischianti) [Library Manager: "SimpleFTPServer"]
 */

#include <WiFi.h>
#include <WiFiUdp.h>
#include <Preferences.h>
#include <Adafruit_NeoPXL8.h>
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

OutputConfig outputs[NUM_OUTPUTS];

int8_t pxl8Pins[8] = {
  PIN_PORT_0, PIN_PORT_1, PIN_PORT_2,
  -1, -1, -1, -1, -1
};

Adafruit_NeoPXL8* leds = nullptr;

// ── Art-Net ──────────────────────────────────────────────────────────
#define MAX_UDP_PACKET 600
WiFiUDP udp;
WiFiUDP udpFps;
uint8_t udpBuf[MAX_UDP_PACKET];

#define ARTNET_HEADER_LEN  8
#define ARTNET_DATA_OFFSET 18

static const uint8_t ARTNET_MAGIC[ARTNET_HEADER_LEN] =
  { 'A', 'r', 't', '-', 'N', 'e', 't', '\0' };

// ── Per-output buffers ───────────────────────────────────────────────
#define MAX_BUFFER_SIZE (MAX_LEDS_PER_PORT * 4)
uint8_t outputBuffers[NUM_OUTPUTS][MAX_BUFFER_SIZE];
bool    outputDataReady[NUM_OUTPUTS]  = {};
bool    outputActive[NUM_OUTPUTS]     = {};
unsigned long outputLastPacket[NUM_OUTPUTS] = {};

// ── Frame assembly ───────────────────────────────────────────────────
uint8_t  frameSequence    = 0;
uint8_t  frameUnivCount   = 0;
uint8_t  activeOutputCount = 0;
unsigned long frameFirstArrival = 0;
bool     frameReady       = false;

// ── WiFi ─────────────────────────────────────────────────────────────
bool wifiConnected = false;
unsigned long lastReconnectAttempt = 0;

// ── Sender address ────────────────────────────────────────────────────
IPAddress senderIP;
bool      senderKnown = false;

// ── Custom device name ────────────────────────────────────────────────
Preferences prefs;
char customShortName[18] = {0};
bool hasCustomName = false;

// ── Timing / FPS ─────────────────────────────────────────────────────
unsigned long lastShowTime  = 0;
unsigned long showDuration  = 2000;
unsigned long showInterval  = 3;
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
//  NeoPXL8 Helpers
// =====================================================================

inline void setStripPixel(uint8_t port, uint16_t pixel, uint32_t color) {
  leds->setPixelColor(port * MAX_LEDS_PER_PORT + pixel, color);
}

void clearPort(uint8_t port, uint16_t count) {
  for (uint16_t p = 0; p < count; p++) setStripPixel(port, p, 0);
}

// =====================================================================
//  WiFi
// =====================================================================

bool connectWifi() {
  IPAddress localIP(DEFAULT_STATIC_IP);
  IPAddress gateway(DEFAULT_GATEWAY);
  IPAddress subnet(DEFAULT_SUBNET);

  WiFi.begin(DEFAULT_WIFI_SSID, DEFAULT_WIFI_PASSWORD);
  WiFi.config(localIP, gateway, subnet);
  WiFi.setSleep(false);

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
    return true;
  }
  Serial.println("WiFi connection failed.");
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
      if (now - lastReconnectAttempt > RECONNECT_INTERVAL) {
        Serial.println("Reconnecting WiFi...");
        lastReconnectAttempt = now;
        wifiConnected = connectWifi();
        if (wifiConnected) udp.begin(ARTNET_PORT);
      }
    }
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

  reply[18] = 0;
  reply[19] = 0;

  reply[20] = (OEM_CODE >> 8) & 0xFF;
  reply[21] = OEM_CODE & 0xFF;

  reply[22] = 0;
  reply[23] = 0xD0;

  reply[24] = ESTA_CODE & 0xFF;
  reply[25] = (ESTA_CODE >> 8) & 0xFF;

  const char* nameToUse = hasCustomName ? customShortName : DEVICE_SHORT_NAME;
  strncpy((char*)&reply[26], nameToUse, 17);

  char longBuf[64];
  int pos = snprintf(longBuf, sizeof(longBuf), "%s | ", DEVICE_LONG_NAME);
  for (uint8_t i = 0; i < NUM_OUTPUTS && pos < 60; i++) {
    if (outputs[i].type == OUTPUT_OFF) continue;
    pos += snprintf(longBuf + pos, sizeof(longBuf) - pos,
                    "A%d:%s ", i, typeName(outputs[i].type));
  }
  strncpy((char*)&reply[44], longBuf, 63);

  char reportBuf[64];
  snprintf(reportBuf, sizeof(reportBuf), "#0001 [%04d] PrimusV3-Audio OK — %.0f fps",
           (int)packetCount, currentFps);
  strncpy((char*)&reply[108], reportBuf, 63);

  reply[172] = 0;
  reply[173] = activeOutputCount;

  for (uint8_t i = 0; i < NUM_OUTPUTS && i < 4; i++) {
    reply[174 + i] = (outputs[i].type != OUTPUT_OFF) ? 0xC0 : 0x00;
  }

  for (uint8_t i = 0; i < NUM_OUTPUTS && i < 4; i++) {
    if (outputs[i].type == OUTPUT_OFF) continue;
    uint8_t flags = 0x80;
    if (outputActive[i]) flags |= 0x01;
    reply[182 + i] = flags;
  }

  for (uint8_t i = 0; i < NUM_OUTPUTS && i < 4; i++) {
    reply[190 + i] = outputs[i].universe & 0x0F;
  }

  reply[200] = 0x00;

  uint8_t mac[6];
  WiFi.macAddress(mac);
  memcpy(&reply[201], mac, 6);

  reply[207] = myIP[0]; reply[208] = myIP[1];
  reply[209] = myIP[2]; reply[210] = myIP[3];

  reply[211] = 1;
  reply[212] = 0x08;

  for (uint8_t i = 0; i < NUM_OUTPUTS && i < 4; i++) {
    if (outputs[i].type != OUTPUT_OFF)
      reply[213 + i] = 0xC0;
  }

  reply[217] = 0x00;

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
//  ArtOutputConfig (opcode 0x8100)
// =====================================================================

void handleArtOutputConfig(uint8_t* data, uint16_t len) {
  if (len < 13) return;
  uint8_t numOut = data[12];
  if (numOut > NUM_OUTPUTS) numOut = NUM_OUTPUTS;
  if (len < (uint16_t)(13 + numOut)) return;

  bool changed = false;
  for (uint8_t i = 0; i < numOut; i++) {
    uint8_t typeId = data[13 + i];
    if (typeId >= NUM_OUTPUT_TYPES) continue;
    OutputType newType = (OutputType)typeId;
    if (outputs[i].type != newType) {
      outputs[i].type = newType;
      deriveFromType(outputs[i]);
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
    broadcastArtPollReply();
  }
}

// =====================================================================
//  ArtAudioCmd (opcode 0x8200)
// =====================================================================

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

  if (infoScreenIndex == 4)
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

  // Stop FTP before any audio operation so they don't share the SD bus
  if (ftpIsRunning()) {
    Serial.println("[ArtAudio] Stopping FTP to free SD bus");
    ftpStop();
    if (infoScreenIndex == 4)
      displayFtpStatus(false, WiFi.localIP(), sdFileCount());
  }

  switch (cmd) {
    case 1:  audioPlay(filename, volume);  break;
    case 2:  audioLoop(filename, volume);  break;
    case 3:  audioPause();                 break;
    case 4:  audioSetVolume(volume);       break;
    default: audioStop();                  break;
  }

  // Refresh audio screen if it's currently displayed
  if (infoScreenIndex == 3) {
    displayAudioStatus(audioCurrentFile(), _audioVolume, audioIsPlaying());
  }
}

// =====================================================================
//  Art-Net Packet Router
// =====================================================================

void processArtNetPacket(uint8_t* data, uint16_t len, IPAddress remoteAddr) {
  if (len < 10) return;
  if (memcmp(data, ARTNET_MAGIC, ARTNET_HEADER_LEN) != 0) return;

  uint16_t opcode = (uint16_t)data[8] | ((uint16_t)data[9] << 8);

  if (opcode == ARTNET_OPCODE_POLL) {
    sendArtPollReply(remoteAddr);
    return;
  }

  if (opcode == ARTNET_OPCODE_ADDRESS) {
    handleArtAddress(data, len);
    return;
  }

  if (opcode == ARTNET_OPCODE_OUTPUT_CONFIG) {
    handleArtOutputConfig(data, len);
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

  if (opcode != ARTNET_OPCODE_DMX) return;

  // ── ArtDmx ───────────────────────────────────────────────────────
  if (len < ARTNET_DATA_OFFSET) return;

  uint8_t  seq      = data[12];
  uint16_t universe = (uint16_t)data[14] | ((uint16_t)data[15] << 8);
  uint16_t dataLen  = ((uint16_t)data[16] << 8) | data[17];
  if ((uint16_t)(ARTNET_DATA_OFFSET + dataLen) > len) {
    dataLen = len - ARTNET_DATA_OFFSET;
  }

  uint8_t* pixelData = data + ARTNET_DATA_OFFSET;
  unsigned long now  = millis();
  packetCount++;

  for (uint8_t o = 0; o < NUM_OUTPUTS; o++) {
    if (outputs[o].type == OUTPUT_OFF) continue;
    if (outputs[o].universe != universe) continue;

    uint16_t needed = outputs[o].pixelCount * outputs[o].bytesPerPixel;
    uint16_t toCopy = (dataLen < needed) ? dataLen : needed;
    memcpy(outputBuffers[o], pixelData, toCopy);
    outputDataReady[o]  = true;
    outputActive[o]     = true;
    outputLastPacket[o] = now;

    if (seq != frameSequence || frameReady) {
      frameSequence    = seq;
      frameUnivCount   = 1;
      frameFirstArrival = now;
      frameReady       = false;
    } else {
      frameUnivCount++;
    }

    if (frameUnivCount >= activeOutputCount) frameReady = true;
    break;
  }

  newDataSinceLastShow = true;
}

// =====================================================================
//  LED Update
// =====================================================================

void applyBufferedData() {
  for (uint8_t o = 0; o < NUM_OUTPUTS; o++) {
    if (!outputDataReady[o]) continue;

    uint8_t  port  = outputs[o].pxl8Port;
    uint16_t count = outputs[o].pixelCount;
    uint8_t  bpp   = outputs[o].bytesPerPixel;

    for (uint16_t p = 0; p < count; p++) {
      uint16_t base = p * bpp;
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
//  FPS Back-Channel
// =====================================================================

static const uint8_t FPS_MAGIC[3] = { 'P', 'F', 'P' };

void sendFpsTelemetry(uint16_t measuredFps, uint16_t pktRate) {
  if (!FPS_BACKCHANNEL_ENABLED) return;
  if (!senderKnown || !wifiConnected) return;

  uint8_t buf[7];
  buf[0] = FPS_MAGIC[0];
  buf[1] = FPS_MAGIC[1];
  buf[2] = FPS_MAGIC[2];
  buf[3] = (measuredFps >> 8) & 0xFF;
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
      case 1:
        if (!wipeDone[o] && wipePos[o] < count) {
          setStripPixel(port, wipePos[o], testColor(o));
          wipePos[o]++;
        } else { wipeDone[o] = true; }
        break;
      case 2:
        for (uint16_t p = 0; p < count; p++)
          setStripPixel(port, p, Adafruit_NeoPixel::Color(255, 255, 255));
        break;
      case 3:
        for (uint16_t p = 0; p < count; p++) {
          uint16_t hue = rainbowHue[o] + (p * 65536L / count);
          setStripPixel(port, p, Adafruit_NeoPixel::ColorHSV(hue, 255, 255));
        }
        rainbowHue[o] += 512;
        if (rainbowHue[o] >= 65536) rainbowHue[o] -= 65536;
        break;
      case 4:
        clearPort(port, count);
        setStripPixel(port, marchPos[o], testColor(o));
        marchPos[o] = (marchPos[o] + 1) % count;
        break;
    }
  }
  leds->show();
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
  leds->show();
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
      displayStatus(outputs, currentFps, outputActive);
      break;
    case 2:
      if (!wifiConnected)
        displayError("WiFi Lost", "Attempting reconnection...");
      else
        displayError("No Errors", "System running normally");
      break;
    case 3:
      displayAudioStatus(audioCurrentFile(), _audioVolume, audioIsPlaying());
      break;
    case 4:
      displayFtpStatus(ftpIsRunning(), WiFi.localIP(), sdFileCount());
      break;
  }
}

void handleTestToggle() {
  // When FTP screen is active, D1 toggles the FTP server
  if (infoScreenIndex == 4) {
    if (ftpIsRunning()) {
      ftpStop();
    } else {
      ftpStart();
    }
    displayFtpStatus(ftpIsRunning(), WiFi.localIP(), sdFileCount());
    return;
  }

  // Normal test mode cycling
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
  Serial.println("Art-Net + Audio + FTP");
  Serial.println("=============================");

  loadDefaultConfig(outputs);
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

  buttonsInit();
  displayInit();
  displayStartup();

  // NeoPXL8
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

  leds->setBrightness(255);
  leds->fill(0);
  leds->show();
  Serial.println("NeoPXL8 OK");

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

  // WiFi
  wifiConnected = connectWifi();
  if (wifiConnected) {
    displayConnection(DEFAULT_WIFI_SSID, WiFi.localIP(), true, WiFi.RSSI());
  } else {
    displayError("WiFi Fail", "Could not connect. Retrying...");
  }

  udp.begin(ARTNET_PORT);
  udpFps.begin(0);

  if (wifiConnected) broadcastArtPollReply();

  // Audio
  audioInit();

  // FTP (init only — server starts on user request)
  ftpInit(SD);

  lastFpsTime  = millis();
  lastShowTime = millis();

  Serial.println("Setup complete. D0=Screen D1=Test/FTP");
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
  if (btnTestToggle)  { btnTestToggle  = false; handleTestToggle();  }

  if (testModeActive) {
    runTestAnimations();
    audioUpdate();
    ftpUpdate();
    delay(33);
    return;
  }

  // ── FTP update ───────────────────────────────────────────────────
  ftpUpdate();

  // ── Audio update ─────────────────────────────────────────────────
  audioUpdate();

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

  // ── Frame assembly timeout ───────────────────────────────────────
  if (!frameReady && frameUnivCount > 0 &&
      (now - frameFirstArrival >= FRAME_ASSEMBLY_TIMEOUT)) {
    frameReady = true;
  }

  // ── Apply data + adaptive-rate show ──────────────────────────────
  if (newDataSinceLastShow && frameReady &&
      (now - lastShowTime >= showInterval)) {
    applyBufferedData();

    unsigned long t0 = micros();
    leds->show();
    unsigned long t1 = micros();
    showDuration = t1 - t0;
    showInterval = (showDuration / 1000) + 1;

    lastShowTime = now;
    newDataSinceLastShow = false;
    frameReady   = false;
    frameUnivCount = 0;
    frameCount++;
  }

  // ── Output idle detection ────────────────────────────────────────
  checkOutputTimeouts();

  // ── FPS reporting ────────────────────────────────────────────────
  if (now - lastFpsTime >= FPS_INTERVAL) {
    unsigned long elapsed = now - lastFpsTime;
    currentFps = frameCount * 1000.0f / elapsed;
    float packetFps = packetCount * 1000.0f / elapsed;

    Serial.print("FPS: ");
    Serial.print(currentFps, 1);
    Serial.print("  Pkts/s: ");
    Serial.print(packetFps, 1);
    Serial.print("  Audio: ");
    Serial.print(audioIsPlaying() ? audioCurrentFile() : "idle");
    Serial.print("  FTP: ");
    Serial.print(ftpIsRunning() ? "ON" : "off");
    Serial.print("  Heap: ");
    Serial.print(ESP.getFreeHeap());
    Serial.print("B  RSSI: ");
    Serial.print(WiFi.RSSI());
    Serial.println("dBm");

    sendFpsTelemetry((uint16_t)currentFps, (uint16_t)packetFps);
    displayUpdateFooter(currentFps, senderKnown ? senderIP : IPAddress(0,0,0,0));

    frameCount  = 0;
    packetCount = 0;
    lastFpsTime = now;
  }
}
