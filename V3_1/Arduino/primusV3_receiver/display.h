/*
 * display.h — PrimusV3 TFT Display Manager
 * =================================================
 * Built-in ST7789 240×135 TFT on the ESP32-S3 Reverse TFT Feather.
 * Screen modes: startup, connection, running status, error, test.
 *
 * Brightness display removed — locked to 255.
 */

#ifndef DISPLAY_H
#define DISPLAY_H

#include <Adafruit_GFX.h>
#include <Adafruit_ST7789.h>
#include <SPI.h>
#include "config.h"

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
  SCREEN_STATUS     = 2,
  SCREEN_ERROR      = 3,
  SCREEN_TEST       = 4
};

#define NUM_INFO_SCREENS 3
ScreenMode currentScreen = SCREEN_STARTUP;

const uint16_t portColors[MAX_OUTPUTS] = { ST77XX_RED, ST77XX_GREEN };

// =====================================================================
//  Device name shown in headers (set from .ino after NVS load)
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
  tft.setRotation(3);  // Landscape, USB on the left
  tft.fillScreen(ST77XX_BLACK);
  tft.setTextWrap(false);
}

// =====================================================================
//  Startup Screen
// =====================================================================
void displayStartup() {
  currentScreen = SCREEN_STARTUP;
  tft.fillScreen(ST77XX_BLACK);

  tft.setCursor(10, 20);
  tft.setTextSize(3);
  tft.setTextColor(ST77XX_CYAN);
  tft.println(headerName());

  tft.setCursor(10, 55);
  tft.setTextSize(1);
  tft.setTextColor(ST77XX_WHITE);
  tft.print("Firmware v");
  tft.println(FIRMWARE_VERSION);

  tft.setCursor(10, 75);
  tft.setTextColor(ST77XX_YELLOW);
  tft.println("Initializing...");
}

// =====================================================================
//  Connection Screen  (main home screen)
// =====================================================================
void displayConnection(const char* ssid, IPAddress ip, bool connected, int rssi) {
  currentScreen = SCREEN_CONNECTION;
  tft.fillScreen(ST77XX_BLACK);

  // ── Large device name ──
  tft.setCursor(4, 6);
  tft.setTextSize(3);
  tft.setTextColor(ST77XX_CYAN);
  tft.println(headerName());

  tft.drawFastHLine(0, 34, 240, 0x4208);

  // ── Compact wifi status row ──
  tft.setCursor(4, 40);
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

  // ── IP address ──
  tft.setCursor(4, 56);
  tft.setTextSize(2);
  tft.setTextColor(ST77XX_WHITE);
  if (connected) {
    tft.print(ip[0]); tft.print(".");
    tft.print(ip[1]); tft.print(".");
    tft.print(ip[2]); tft.print(".");
    tft.print(ip[3]);
  } else {
    tft.print("---.---.---.---");
  }

  // ── SSID ──
  tft.setCursor(4, 78);
  tft.setTextSize(1);
  tft.setTextColor(0x7BEF);
  tft.print(ssid);

  // ── FPS + footer ──
  tft.drawFastHLine(0, 105, 240, 0x4208);
  tft.setCursor(4, 110);
  tft.setTextSize(1);
  tft.setTextColor(0x7BEF);
  tft.print("FPS: ");
  tft.setTextColor(ST77XX_CYAN);
  tft.print("--");

  tft.setCursor(140, 110);
  tft.setTextColor(0x7BEF);
  tft.print("D0:Screen D1:Test");

  tft.setCursor(4, 124);
  tft.setTextSize(1);
  tft.setTextColor(0x7BEF);
  tft.print("Heap:");
  tft.print(ESP.getFreeHeap() / 1024);
  tft.print("k");
}

// =====================================================================
//  Running Status Screen
// =====================================================================
void displayStatus(OutputConfig outputs[NUM_OUTPUTS], float fps,
                   bool outputActive[NUM_OUTPUTS]) {
  currentScreen = SCREEN_STATUS;
  tft.fillScreen(ST77XX_BLACK);

  tft.setCursor(4, 4);
  tft.setTextSize(1);
  tft.setTextColor(ST77XX_WHITE);
  tft.print(headerName());
  tft.print(" | Status");
  tft.drawFastHLine(0, 14, 240, ST77XX_WHITE);

  for (uint8_t i = 0; i < NUM_OUTPUTS; i++) {
    int16_t y = 18 + i * 28;

    tft.setCursor(4, y);
    tft.setTextSize(2);
    tft.setTextColor(portColors[i]);
    tft.print(i);

    tft.setTextSize(1);
    tft.setTextColor(ST77XX_WHITE);
    tft.setCursor(20, y);
    tft.print(typeName(outputs[i].type));
    tft.setCursor(20, y + 10);
    tft.print(outputs[i].pixelCount);
    tft.print("px");

    tft.setCursor(100, y);
    tft.print("U:");
    tft.print(outputs[i].universe);

    tft.setCursor(160, y);
    if (outputs[i].type == OUTPUT_OFF) {
      tft.setTextColor(0x7BEF);
      tft.print("OFF");
    } else if (outputActive[i]) {
      tft.setTextColor(ST77XX_GREEN);
      tft.print("RECV");
    } else {
      tft.setTextColor(ST77XX_RED);
      tft.print("IDLE");
    }
  }

  // Footer: FPS + source
  int16_t footerY = 105;
  tft.drawFastHLine(0, footerY, 240, ST77XX_WHITE);
  tft.setCursor(4, footerY + 4);
  tft.setTextSize(1);
  tft.setTextColor(ST77XX_WHITE);
  tft.print("FPS: ");
  tft.setTextColor(ST77XX_CYAN);
  tft.print(fps, 1);

  tft.setCursor(4, footerY + 16);
  tft.setTextColor(0x7BEF);
  tft.print("Art-Net Node · ArtPoll OK");
}

// =====================================================================
//  Error Screen
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
//  Test Mode Screen
// =====================================================================
void displayTestMode(uint8_t testModeIdx, const char* modeName) {
  currentScreen = SCREEN_TEST;
  tft.fillScreen(ST77XX_BLACK);

  tft.setCursor(4, 4);
  tft.setTextSize(1);
  tft.setTextColor(ST77XX_WHITE);
  tft.print(headerName());
  tft.print(" | Test Mode");
  tft.drawFastHLine(0, 14, 240, ST77XX_MAGENTA);

  tft.setCursor(10, 35);
  tft.setTextSize(3);
  tft.setTextColor(ST77XX_MAGENTA);
  tft.println(modeName);

  tft.setCursor(10, 80);
  tft.setTextSize(1);
  tft.setTextColor(ST77XX_WHITE);
  tft.println("ArtNet paused during test");

  tft.setCursor(10, 100);
  tft.setTextColor(ST77XX_YELLOW);
  tft.println("D1: next mode / exit");
}

// =====================================================================
//  Quick footer update (avoids full redraw flicker)
// =====================================================================
void displayUpdateFooter(float fps, IPAddress sourceIP = IPAddress(0,0,0,0)) {
  if (currentScreen == SCREEN_CONNECTION) {
    // Update just the FPS value on the connection/home screen
    tft.fillRect(34, 110, 50, 10, ST77XX_BLACK);
    tft.setCursor(34, 110);
    tft.setTextSize(1);
    tft.setTextColor(ST77XX_CYAN);
    if (fps > 0) tft.print(fps, 1); else tft.print("--");
    return;
  }

  if (currentScreen != SCREEN_STATUS) return;

  int16_t footerY = 105;
  tft.fillRect(0, footerY + 1, 240, 30, ST77XX_BLACK);
  tft.drawFastHLine(0, footerY, 240, ST77XX_WHITE);

  tft.setCursor(4, footerY + 4);
  tft.setTextSize(1);
  tft.setTextColor(ST77XX_WHITE);
  tft.print("FPS: ");
  tft.setTextColor(ST77XX_CYAN);
  tft.print(fps, 1);

  // Show source IP if known
  if (sourceIP != IPAddress(0,0,0,0)) {
    tft.setCursor(80, footerY + 4);
    tft.setTextColor(ST77XX_WHITE);
    tft.print("Src: ");
    tft.setTextColor(ST77XX_YELLOW);
    tft.print(sourceIP);
  }

  tft.setCursor(4, footerY + 16);
  tft.setTextColor(0x7BEF);
  tft.print("Heap:");
  tft.print(ESP.getFreeHeap() / 1024);
  tft.print("k");
}

// =====================================================================
//  Quick output active/idle indicator update
// =====================================================================
void displayUpdateOutputActive(uint8_t index, bool active, OutputType type) {
  if (currentScreen != SCREEN_STATUS) return;

  int16_t y = 18 + index * 28;
  tft.fillRect(160, y, 80, 10, ST77XX_BLACK);
  tft.setCursor(160, y);
  tft.setTextSize(1);
  if (type == OUTPUT_OFF) {
    tft.setTextColor(0x7BEF);
    tft.print("OFF");
  } else if (active) {
    tft.setTextColor(ST77XX_GREEN);
    tft.print("RECV");
  } else {
    tft.setTextColor(ST77XX_RED);
    tft.print("IDLE");
  }
}

#endif // DISPLAY_H
