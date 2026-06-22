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
 *   4 — SD card status
 */

#ifndef DISPLAY_H
#define DISPLAY_H

#include <WiFi.h>
#include "config.h"

// =====================================================================
//  NO_DISPLAY stubs — headless builds (HUZZAH32, no TFT)
// =====================================================================
#ifdef NO_DISPLAY

#define NUM_INFO_SCREENS 5

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
inline void displayAudioUpdate(const char*, uint8_t, bool)       {}
inline void displayFtpStatus(bool, IPAddress, uint16_t)          {}
inline void displaySdStatus(bool, uint16_t, const char* = nullptr, bool = false) {}
inline void displayUpdateFooter(float) {}

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
  SCREEN_FTP        = 4,
  SCREEN_SD         = 5
};

#define NUM_INFO_SCREENS 5

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
  tft.println("Audio: Music Maker (VS1053)");
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
  tft.print("Board: Music Maker (VS1053)");

  tft.setCursor(4, 124);
  tft.setTextColor(0x4208);
  tft.print("D1: Test Tone");
}

// =====================================================================
//  Audio Status — partial update (call every loop; skips redraws when
//  state is unchanged, avoiding the SPI blocking that causes DMA glitches)
// =====================================================================
void displayAudioUpdate(const char* filename, uint8_t volume, bool playing) {
  if (currentScreen != SCREEN_AUDIO) return;

  static bool    lastPlaying = false;
  static char    lastFile[17] = {0};
  static uint8_t lastVolume   = 255;

  const char* safeFile = (filename && filename[0]) ? filename : "";

  bool stateChanged = (playing != lastPlaying);
  bool fileChanged  = strncmp(lastFile, safeFile, 16) != 0;
  bool volChanged   = (volume != lastVolume);

  if (stateChanged) {
    displayAudioStatus(filename, volume, playing);
    lastPlaying = playing;
    strncpy(lastFile, safeFile, 16);
    lastFile[16] = '\0';
    lastVolume = volume;
    return;
  }

  if (fileChanged && playing) {
    tft.fillRect(4, 40, 232, 18, ST77XX_BLACK);
    tft.setCursor(4, 40);
    tft.setTextSize(2);
    tft.setTextColor(ST77XX_CYAN);
    char truncName[17];
    strncpy(truncName, safeFile, 16);
    truncName[16] = '\0';
    tft.print(truncName);
    strncpy(lastFile, truncName, 16);
    lastFile[16] = '\0';
  }

  if (volChanged && playing) {
    // "Volume: " is 8 chars × 6px = 48px; number starts at x=52
    tft.fillRect(52, 70, 80, 8, ST77XX_BLACK);
    tft.setCursor(52, 70);
    tft.setTextSize(1);
    tft.setTextColor(ST77XX_WHITE);
    tft.print(volume);
    tft.print("%");
    lastVolume = volume;
  }
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
//  SD Card Status Screen (screen index 4)
//  selectedFile: currently highlighted WAV file (nullptr = none)
//  playing:      true if selectedFile is currently playing
// =====================================================================
void displaySdStatus(bool ready, uint16_t fileCount,
                     const char* selectedFile = nullptr, bool playing = false) {
  currentScreen = SCREEN_SD;
  tft.fillScreen(ST77XX_BLACK);

  tft.setCursor(4, 4);
  tft.setTextSize(1);
  tft.setTextColor(ST77XX_WHITE);
  tft.print(headerName());
  tft.print(" | SD Card");
  tft.drawFastHLine(0, 14, 240, ready ? ST77XX_GREEN : ST77XX_RED);

  if (ready) {
    tft.setCursor(4, 22);
    tft.setTextSize(1);
    tft.setTextColor(ST77XX_GREEN);
    tft.print("SD OK");
    tft.setTextColor(0x7BEF);
    tft.print("  Files: ");
    tft.setTextColor(ST77XX_WHITE);
    tft.print(fileCount);

    if (selectedFile && selectedFile[0] != '\0') {
      // Filename — truncate to 14 chars at size 2 (168 px)
      tft.setCursor(4, 36);
      tft.setTextSize(2);
      tft.setTextColor(playing ? ST77XX_CYAN : ST77XX_WHITE);
      char truncName[15];
      strncpy(truncName, selectedFile, 14);
      truncName[14] = '\0';
      tft.print(truncName);

      // Play status
      tft.setCursor(4, 68);
      tft.setTextSize(1);
      if (playing) {
        tft.setTextColor(ST77XX_GREEN);
        tft.print("PLAYING");
      } else {
        tft.setTextColor(0x7BEF);
        tft.print("Idle");
      }
    } else if (fileCount == 0) {
      tft.setCursor(4, 45);
      tft.setTextSize(1);
      tft.setTextColor(0x7BEF);
      tft.print("No WAV files on SD");
    }
  } else {
    tft.setCursor(4, 25);
    tft.setTextSize(2);
    tft.setTextColor(ST77XX_RED);
    tft.print("NOT FOUND");

    tft.setCursor(4, 55);
    tft.setTextSize(1);
    tft.setTextColor(ST77XX_YELLOW);
    tft.print("Insert card, press D1");
    tft.setCursor(4, 68);
    tft.setTextColor(0x7BEF);
    tft.print("to retry");
  }

  tft.drawFastHLine(0, 100, 240, 0x4208);
  tft.setCursor(4, 106);
  tft.setTextSize(1);
  tft.setTextColor(0x7BEF);
  if (!ready) {
    tft.print("D1: Retry");
  } else if (selectedFile && selectedFile[0] != '\0') {
    tft.setTextColor(playing ? ST77XX_RED : ST77XX_GREEN);
    tft.print(playing ? "D1:Stop" : "D1:Play");
    tft.setTextColor(0x7BEF);
    tft.print("  D2:Next");
  } else {
    tft.print("D2: Next file");
  }
}

// =====================================================================
//  Quick footer update — connection screen packet-rate counter
// =====================================================================
void displayUpdateFooter(float pktRate) {
  if (currentScreen != SCREEN_CONNECTION) return;

  // "P/s: " is 5 chars × 6px = 30px; number starts at x=4+30=34
  tft.fillRect(34, 96, 70, 10, ST77XX_BLACK);
  tft.setCursor(34, 96);
  tft.setTextSize(1);
  tft.setTextColor(ST77XX_CYAN);
  if (pktRate > 0) tft.print(pktRate, 1); else tft.print("--");
}

#endif // NO_DISPLAY
#endif // DISPLAY_H
