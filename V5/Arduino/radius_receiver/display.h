/*
 * display.h — PrimusV3 Audio TFT Display Manager
 * =================================================
 * Built-in ST7789 240×135 TFT on the ESP32-S3 Reverse TFT Feather.
 *
 * Screen index cycle (D0 button):
 *   0 — Connection / home
 *   1 — Error / system
 *   2 — Audio status
 *   3 — FTP status
 */

#ifndef DISPLAY_H
#define DISPLAY_H

#include <WiFi.h>
#include "config.h"

// =====================================================================
//  NO_DISPLAY stubs — headless builds (HUZZAH32, no TFT)
// =====================================================================
#ifdef NO_DISPLAY

#define NUM_INFO_SCREENS 4

char displayDeviceName[18] = {0};

inline void setDisplayName(const char* name) {
  strncpy(displayDeviceName, name, 17);
  displayDeviceName[17] = '\0';
}
inline void displayInit()       {}
inline void displayStartup()    {}
inline void displayConnection(const char*, IPAddress, bool, int) {}
inline void displayError(const char*, const char*)               {}
inline void displayAudioStatus(const char*, uint8_t, bool)       {}
inline void displayFtpStatus(bool, IPAddress, uint16_t)          {}
inline void displayUpdateFooter(float, IPAddress = IPAddress(0,0,0,0)) {}
#define MARIUS_DISPLAY_REVERTED 255
inline void displayMariusUpdate(uint8_t, const char*, const char*) {}

#else  // full TFT implementation below

#include <Adafruit_GFX.h>
#include <Adafruit_ST7789.h>
#include <SPI.h>

// =====================================================================
//  TFT Object
// =====================================================================
Adafruit_ST7789 tft = Adafruit_ST7789(TFT_CS, TFT_DC, TFT_RST);

// =====================================================================
//  Screen Modes
// =====================================================================
enum ScreenMode {
  SCREEN_STARTUP    = 0,
  SCREEN_CONNECTION = 1,
  SCREEN_ERROR      = 2,
  SCREEN_AUDIO      = 3,
  SCREEN_FTP        = 4
};

#define NUM_INFO_SCREENS 4

ScreenMode currentScreen = SCREEN_STARTUP;

// =====================================================================
//  Device name shown in headers
// =====================================================================
char displayDeviceName[18] = {0};

void setDisplayName(const char* name) {
  strncpy(displayDeviceName, name, 17);
  displayDeviceName[17] = '\0';
}

static const char* headerName() {
  return displayDeviceName[0] ? displayDeviceName : FIRMWARE_NAME;
}

// =====================================================================
//  Initialization
// =====================================================================
void displayInit() {
  pinMode(TFT_BACKLITE, OUTPUT);
  digitalWrite(TFT_BACKLITE, HIGH);

  #ifdef TFT_I2C_POWER
    pinMode(TFT_I2C_POWER, OUTPUT);
    digitalWrite(TFT_I2C_POWER, HIGH);
    delay(10);
  #endif

  tft.init(135, 240);
  tft.setRotation(3);
  tft.fillScreen(ST77XX_BLACK);
  tft.setTextWrap(false);
}

// =====================================================================
//  Startup Screen
// =====================================================================
void displayStartup() {
  currentScreen = SCREEN_STARTUP;
  tft.fillScreen(ST77XX_BLACK);

  tft.setCursor(10, 15);
  tft.setTextSize(2);
  tft.setTextColor(ST77XX_CYAN);
  tft.println(headerName());

  tft.setCursor(10, 45);
  tft.setTextSize(1);
  tft.setTextColor(ST77XX_WHITE);
  tft.print("Firmware v");
  tft.println(FIRMWARE_VERSION);

  tft.setCursor(10, 60);
  tft.setTextColor(ST77XX_YELLOW);
  tft.println("Initializing...");

  tft.setCursor(10, 80);
  tft.setTextColor(0x7BEF);
#if AUDIO_BOARD == AUDIO_BOARD_MUSIC_MAKER
  tft.println("Audio: Music Maker (VS1053)");
#else
  tft.println("Audio: BFF (MAX98357 I2S)");
#endif
}

// =====================================================================
//  Connection Screen (screen index 0)
// =====================================================================
void displayConnection(const char* ssid, IPAddress ip, bool connected, int rssi) {
  currentScreen = SCREEN_CONNECTION;
  tft.fillScreen(ST77XX_BLACK);

  tft.setCursor(4, 6);
  tft.setTextSize(2);
  tft.setTextColor(ST77XX_CYAN);
  tft.println(headerName());

  tft.drawFastHLine(0, 28, 240, 0x4208);

  tft.setCursor(4, 34);
  tft.setTextSize(1);
  if (connected) {
    tft.setTextColor(ST77XX_GREEN);
    tft.print("WiFi OK");
    tft.setTextColor(0x7BEF);
    tft.print("  RSSI:");
    if (rssi > -50)      tft.setTextColor(ST77XX_GREEN);
    else if (rssi > -70) tft.setTextColor(ST77XX_YELLOW);
    else                 tft.setTextColor(ST77XX_RED);
    tft.print(rssi);
    tft.print("dBm");
  } else {
    tft.setTextColor(ST77XX_RED);
    tft.print("No WiFi");
  }

  tft.setCursor(4, 50);
  tft.setTextSize(2);
  tft.setTextColor(ST77XX_WHITE);
  if (connected) {
    tft.print(ip[0]); tft.print(".");
    tft.print(ip[1]); tft.print(".");
    tft.print(ip[2]); tft.print(".");
    tft.print(ip[3]);
  } else {
    tft.print("---.---.---.-");
  }

  tft.setCursor(4, 72);
  tft.setTextSize(1);
  tft.setTextColor(0x7BEF);
  tft.print(ssid);

  tft.drawFastHLine(0, 90, 240, 0x4208);
  tft.setCursor(4, 96);
  tft.setTextSize(1);
  tft.setTextColor(0x7BEF);
  tft.print("P/s: ");
  tft.setTextColor(ST77XX_CYAN);
  tft.print("--");

  tft.setCursor(4, 110);
  tft.setTextColor(0x7BEF);
  tft.print("D0:Screen");

  tft.setCursor(4, 124);
  tft.setTextSize(1);
  tft.setTextColor(0x7BEF);
  tft.print("Heap:");
  tft.print(ESP.getFreeHeap() / 1024);
  tft.print("k");
}

// =====================================================================
//  Error Screen (screen index 1)
// =====================================================================
void displayError(const char* errorMsg, const char* detail) {
  currentScreen = SCREEN_ERROR;
  tft.fillScreen(ST77XX_BLACK);

  tft.setCursor(4, 4);
  tft.setTextSize(1);
  tft.setTextColor(ST77XX_WHITE);
  tft.print(headerName());
  tft.print(" | Error");
  tft.drawFastHLine(0, 14, 240, ST77XX_RED);

  tft.setCursor(10, 30);
  tft.setTextSize(2);
  tft.setTextColor(ST77XX_RED);
  tft.println(errorMsg);

  if (detail != NULL) {
    tft.setCursor(10, 60);
    tft.setTextSize(1);
    tft.setTextColor(ST77XX_YELLOW);
    tft.println(detail);
  }

  tft.setCursor(10, 100);
  tft.setTextSize(1);
  tft.setTextColor(ST77XX_WHITE);
  tft.println("Check serial for details");
}

// =====================================================================
//  Audio Status Screen (screen index 2)
// =====================================================================
void displayAudioStatus(const char* filename, uint8_t volume, bool playing) {
  currentScreen = SCREEN_AUDIO;
  tft.fillScreen(ST77XX_BLACK);

  tft.setCursor(4, 4);
  tft.setTextSize(1);
  tft.setTextColor(ST77XX_WHITE);
  tft.print(headerName());
  tft.print(" | Audio");
  tft.drawFastHLine(0, 14, 240, ST77XX_CYAN);

  if (playing && filename && filename[0] != '\0') {
    tft.setCursor(4, 25);
    tft.setTextSize(1);
    tft.setTextColor(0x7BEF);
    tft.print("Now Playing:");

    tft.setCursor(4, 40);
    tft.setTextSize(2);
    tft.setTextColor(ST77XX_CYAN);
    char truncName[17];
    strncpy(truncName, filename, 16);
    truncName[16] = '\0';
    tft.print(truncName);

    tft.setCursor(4, 70);
    tft.setTextSize(1);
    tft.setTextColor(ST77XX_WHITE);
    tft.print("Volume: ");
    tft.print(volume);
    tft.print("%");

    tft.setCursor(4, 85);
    tft.setTextColor(ST77XX_GREEN);
    tft.print("PLAYING");
  } else {
    tft.setCursor(4, 40);
    tft.setTextSize(2);
    tft.setTextColor(0x7BEF);
    tft.print("Audio: Idle");

    tft.setCursor(4, 70);
    tft.setTextSize(1);
    tft.setTextColor(0x7BEF);
    tft.print("Awaiting opcode 0x8300");
  }

  tft.drawFastHLine(0, 105, 240, 0x4208);
  tft.setCursor(4, 110);
  tft.setTextSize(1);
  tft.setTextColor(0x7BEF);
#if AUDIO_BOARD == AUDIO_BOARD_MUSIC_MAKER
  tft.print("Board: Music Maker (VS1053)");
#else
  tft.print("Board: BFF (MAX98357 I2S)");
#endif

  tft.setCursor(4, 124);
  tft.setTextColor(0x4208);
  tft.print("D1: Test Tone");
}

// =====================================================================
//  FTP Status Screen (screen index 3)
// =====================================================================
void displayFtpStatus(bool running, IPAddress ip, uint16_t fileCount) {
  currentScreen = SCREEN_FTP;
  tft.fillScreen(ST77XX_BLACK);

  tft.setCursor(4, 4);
  tft.setTextSize(1);
  tft.setTextColor(ST77XX_WHITE);
  tft.print(headerName());
  tft.print(" | FTP");
  tft.drawFastHLine(0, 14, 240, running ? ST77XX_GREEN : 0x4208);

  if (running) {
    tft.setCursor(4, 22);
    tft.setTextSize(1);
    tft.setTextColor(ST77XX_GREEN);
    tft.print("FTP SERVER ON");

    tft.setCursor(4, 38);
    tft.setTextColor(0x7BEF);
    tft.print("IP:   ");
    tft.setTextColor(ST77XX_WHITE);
    tft.print(ip);

    tft.setCursor(4, 54);
    tft.setTextColor(0x7BEF);
    tft.print("User: ");
    tft.setTextColor(ST77XX_WHITE);
    tft.print(FTP_USER);

    tft.setCursor(4, 68);
    tft.setTextColor(0x7BEF);
    tft.print("Pass: ");
    tft.setTextColor(ST77XX_WHITE);
    tft.print(FTP_PASSWORD);

    tft.setCursor(4, 84);
    tft.setTextColor(0x7BEF);
    tft.print("Files on SD: ");
    tft.setTextColor(ST77XX_CYAN);
    tft.print(fileCount);
  } else {
    tft.setCursor(4, 30);
    tft.setTextSize(2);
    tft.setTextColor(0x7BEF);
    tft.print("FTP: OFF");

    tft.setCursor(4, 60);
    tft.setTextSize(1);
    tft.setTextColor(ST77XX_WHITE);
    tft.print("Press D1 to start FTP");
    tft.setCursor(4, 75);
    tft.setTextColor(0x7BEF);
    tft.print("Audio stops while FTP is on");
  }

  tft.drawFastHLine(0, 105, 240, 0x4208);
  tft.setCursor(4, 110);
  tft.setTextSize(1);
  tft.setTextColor(running ? ST77XX_YELLOW : 0x7BEF);
  tft.print(running ? "D1: Stop FTP" : "D1: Start FTP");
}

// =====================================================================
//  Quick footer update — connection screen packet-rate counter
// =====================================================================
void displayUpdateFooter(float pktRate, IPAddress sourceIP = IPAddress(0,0,0,0)) {
  if (currentScreen != SCREEN_CONNECTION) return;

  // "P/s: " is 5 chars × 6px = 30px; number starts at x=4+30=34
  tft.fillRect(34, 96, 70, 10, ST77XX_BLACK);
  tft.setCursor(34, 96);
  tft.setTextSize(1);
  tft.setTextColor(ST77XX_CYAN);
  if (pktRate > 0) tft.print(pktRate, 1); else tft.print("--");
}

#define MARIUS_DISPLAY_REVERTED 255

void displayMariusUpdate(uint8_t state, const char* puckName, const char* lastEvent) {
  (void)state;
  (void)puckName;
  (void)lastEvent;
}

#endif // NO_DISPLAY
#endif // DISPLAY_H
