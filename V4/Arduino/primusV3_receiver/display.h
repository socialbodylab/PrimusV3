/*
 * display.h — PrimusV3 TFT Display Manager
 * =================================================
 * Built-in ST7789 240×135 TFT on the ESP32-S3 Reverse TFT Feather.
 * Three info screens: dashboard (pg1), info (pg2), edit (pg3).
 */

#ifndef DISPLAY_H
#define DISPLAY_H

#include "config.h"

#if BOARD_HAS_TFT_DISPLAY

#include "receive_mode.h"

#if BOARD_BATTERY_MONITOR
#include "battery.h"
#endif

#include <Adafruit_GFX.h>
#include <Adafruit_ST7789.h>
#include <SPI.h>

Adafruit_ST7789 tft = Adafruit_ST7789(TFT_CS, TFT_DC, TFT_RST);

enum ScreenMode {
  SCREEN_STARTUP  = 0,
  SCREEN_DASHBOARD = 1,
  SCREEN_INFO     = 2,
  SCREEN_EDIT     = 3,
  SCREEN_TEST     = 4
};

#define NUM_INFO_SCREENS 3
ScreenMode currentScreen = SCREEN_STARTUP;

const uint16_t portColors[MAX_OUTPUTS] = { ST77XX_RED, ST77XX_GREEN };

char displayDeviceName[18] = {0};

// Layout constants for partial updates on dashboard
static const int16_t DASH_BANNER_Y = 2;
static const int16_t DASH_IP_Y = 34;
static const int16_t DASH_BATTERY_Y = 54;
static const int16_t DASH_NAME_Y = 68;
static const int16_t DASH_RECV_Y = 82;
static const int16_t DASH_OUT0_Y = 96;
static const int16_t DASH_OUT1_Y = 110;

void setDisplayName(const char* name) {
  strncpy(displayDeviceName, name, 17);
  displayDeviceName[17] = '\0';
}

static const char* headerName() {
  return displayDeviceName[0] ? displayDeviceName : DEVICE_SHORT_NAME;
}

static void drawConnectionBanner(bool connected, bool reconnecting) {
  tft.fillRect(0, DASH_BANNER_Y, 240, 22, ST77XX_BLACK);
  tft.setCursor(4, DASH_BANNER_Y + 4);
  tft.setTextSize(2);
  if (connected) {
    tft.setTextColor(ST77XX_GREEN);
    tft.print("CONNECTED");
  } else if (reconnecting) {
    tft.setTextColor(ST77XX_YELLOW);
    tft.print("RECONNECTING");
  } else {
    tft.setTextColor(ST77XX_RED);
    tft.print("DISCONNECTED");
  }
}

static void drawOutputPowerBadge(int16_t x, int16_t y, bool powerEnabled, OutputType type) {
  tft.setCursor(x, y);
  tft.setTextSize(1);
  if (!powerEnabled || type == OUTPUT_OFF) {
    tft.setTextColor(0x7BEF);
    tft.print("o OFF");
  } else {
    tft.setTextColor(ST77XX_GREEN);
    tft.print("* ON");
  }
}

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

void displayError(const char* errorMsg, const char* detail) {
  currentScreen = SCREEN_STARTUP;
  tft.fillScreen(ST77XX_BLACK);

  tft.setCursor(4, 4);
  tft.setTextSize(1);
  tft.setTextColor(ST77XX_WHITE);
  tft.print(headerName());
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
}

// pg1 — Dashboard (read-only)
void displayDashboard(const char* ssid, IPAddress ip, bool connected, bool reconnecting,
                      int rssi, bool staticIPActive, OutputConfig outputs[NUM_OUTPUTS],
                      bool outputsPowerEnabled) {
  (void)rssi;
  currentScreen = SCREEN_DASHBOARD;
  tft.fillScreen(ST77XX_BLACK);

  drawConnectionBanner(connected, reconnecting);

  if (!connected && !outputsPowerEnabled) {
    tft.setCursor(4, 24);
    tft.setTextSize(1);
    tft.setTextColor(ST77XX_YELLOW);
    tft.print("Outputs waiting for WiFi");
  }

  tft.setCursor(4, DASH_IP_Y);
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

#if BOARD_BATTERY_MONITOR
  tft.setCursor(4, DASH_BATTERY_Y);
  tft.setTextSize(1);
  tft.setTextColor(ST77XX_WHITE);
  tft.print("Batt: ");
  const BatteryStatus& batt = batteryLastDisplayStatus();
  if (batt.batteryPct == 255) {
    tft.setTextColor(0x7BEF);
    tft.print("---");
  } else {
    if (batt.batteryPct <= 15) tft.setTextColor(ST77XX_RED);
    else if (batt.batteryPct <= 30) tft.setTextColor(ST77XX_YELLOW);
    else tft.setTextColor(ST77XX_GREEN);
    tft.print(batt.batteryPct);
    tft.print("%");
    tft.setTextColor(0x7BEF);
    tft.print("  ");
    tft.print(batteryTimeRemainingLabel());
  }
#endif

  tft.setCursor(4, DASH_NAME_Y);
  tft.setTextSize(1);
  tft.setTextColor(ST77XX_CYAN);
  tft.println(headerName());

  tft.setCursor(4, DASH_RECV_Y);
  tft.setTextColor(ST77XX_YELLOW);
  tft.print(receiveModeLabel(currentReceiveMode));
  tft.print(" U");
  if (currentReceiveMode == RECEIVE_MODE_COMBINED) {
    tft.print(currentUniverseBase);
  } else {
    tft.print(currentUniverseBase);
    tft.print("/");
    tft.print(currentUniverseBase + 1);
  }

  for (uint8_t i = 0; i < NUM_OUTPUTS; i++) {
    int16_t y = (i == 0) ? DASH_OUT0_Y : DASH_OUT1_Y;
    tft.setCursor(4, y);
    tft.setTextSize(1);
    tft.setTextColor(portColors[i]);
    tft.print("Out");
    tft.print(i);
    tft.print(": ");
    tft.setTextColor(ST77XX_WHITE);
    tft.print(typeName(outputs[i].type));
    drawOutputPowerBadge(170, y, outputsPowerEnabled, outputs[i].type);
  }

  tft.drawFastHLine(0, 122, 240, 0x4208);
  tft.setCursor(4, 126);
  tft.setTextSize(1);
  tft.setTextColor(0x7BEF);
  tft.print("D0:Screen 1/3");
}

// pg2 — Info (read-only)
void displayInfo(const char* ssid, bool connected, int rssi, bool staticIPActive) {
  currentScreen = SCREEN_INFO;
  tft.fillScreen(ST77XX_BLACK);

  tft.setCursor(4, 4);
  tft.setTextSize(1);
  tft.setTextColor(ST77XX_WHITE);
  tft.print("Network Info");
  tft.drawFastHLine(0, 14, 240, ST77XX_WHITE);

  tft.setCursor(10, 28);
  tft.setTextSize(1);
  tft.setTextColor(ST77XX_CYAN);
  tft.print("SSID: ");
  tft.setTextColor(ST77XX_WHITE);
  tft.println(ssid);

  tft.setCursor(10, 44);
  tft.setTextColor(ST77XX_CYAN);
  tft.print("Mode: ");
  tft.setTextColor(ST77XX_WHITE);
  if (connected) {
    tft.print(staticIPActive ? "Static IP" : "DHCP");
  } else {
    tft.print("Not connected");
  }

  tft.setCursor(10, 60);
  tft.setTextColor(ST77XX_CYAN);
  tft.print("RSSI: ");
  tft.setTextColor(ST77XX_WHITE);
  if (connected) {
    if (rssi > -50)      tft.setTextColor(ST77XX_GREEN);
    else if (rssi > -70) tft.setTextColor(ST77XX_YELLOW);
    else                 tft.setTextColor(ST77XX_RED);
    tft.print(rssi);
    tft.print(" dBm");
  } else {
    tft.print("---");
  }

  tft.setCursor(10, 84);
  tft.setTextColor(ST77XX_CYAN);
  tft.print("Firmware: ");
  tft.setTextColor(ST77XX_WHITE);
  tft.println(FIRMWARE_VERSION);

  tft.setCursor(10, 108);
  tft.setTextColor(0x7BEF);
  tft.print("D0:Screen 2/3  D1:Test");
}

// pg3 — Edit
void displayEditSettings(OutputConfig outputs[NUM_OUTPUTS], uint8_t editFocus,
                         const char* errorMsg = nullptr) {
  currentScreen = SCREEN_EDIT;
  tft.fillScreen(ST77XX_BLACK);

  tft.setCursor(4, 4);
  tft.setTextSize(1);
  tft.setTextColor(ST77XX_WHITE);
  tft.print("Edit Settings");
  tft.drawFastHLine(0, 14, 240, ST77XX_CYAN);

  const char* focusLabels[] = { "Out0 Type", "Out1 Type", "Receive Mode" };
  for (uint8_t row = 0; row < 3; row++) {
    int16_t y = 28 + row * 24;
    bool focused = (editFocus == row);
    tft.setCursor(10, y);
    tft.setTextSize(1);
    tft.setTextColor(focused ? ST77XX_YELLOW : 0x7BEF);
    if (focused) tft.print("> ");
    else tft.print("  ");
    tft.print(focusLabels[row]);
    tft.print(": ");
    tft.setTextColor(ST77XX_WHITE);
    if (row == 0) tft.print(typeName(outputs[0].type));
    else if (row == 1) tft.print(typeName(outputs[1].type));
    else tft.print(receiveModeLabel(currentReceiveMode));
  }

  if (errorMsg && errorMsg[0]) {
    tft.setCursor(10, 88);
    tft.setTextColor(ST77XX_RED);
    tft.println(errorMsg);
  }

  tft.setCursor(10, 108);
  tft.setTextColor(0x7BEF);
  tft.print("D1:Change  Hold:Next  3/3");
}

void displayTestMode(uint8_t testModeIdx, const char* modeName) {
  currentScreen = SCREEN_TEST;
  tft.fillScreen(ST77XX_BLACK);

  tft.setCursor(4, 4);
  tft.setTextSize(1);
  tft.setTextColor(ST77XX_WHITE);
  tft.print(headerName());
  tft.print(" | Test");
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

void displayUpdateConnectionBanner(bool connected, bool reconnecting) {
  if (currentScreen != SCREEN_DASHBOARD) return;
  drawConnectionBanner(connected, reconnecting);
}

void displayUpdateBattery() {
#if BOARD_BATTERY_MONITOR
  if (currentScreen != SCREEN_DASHBOARD) return;
  tft.fillRect(40, DASH_BATTERY_Y, 200, 10, ST77XX_BLACK);
  tft.setCursor(4, DASH_BATTERY_Y);
  tft.setTextSize(1);
  tft.setTextColor(ST77XX_WHITE);
  tft.print("Batt: ");
  const BatteryStatus& batt = batteryLastDisplayStatus();
  if (batt.batteryPct == 255) {
    tft.setTextColor(0x7BEF);
    tft.print("---");
  } else {
    if (batt.batteryPct <= 15) tft.setTextColor(ST77XX_RED);
    else if (batt.batteryPct <= 30) tft.setTextColor(ST77XX_YELLOW);
    else tft.setTextColor(ST77XX_GREEN);
    tft.print(batt.batteryPct);
    tft.print("%");
    tft.setTextColor(0x7BEF);
    tft.print("  ");
    tft.print(batteryTimeRemainingLabel());
  }
#endif
}

void displayUpdateOutputPower(OutputConfig outputs[NUM_OUTPUTS], bool outputsPowerEnabled) {
  if (currentScreen != SCREEN_DASHBOARD) return;
  for (uint8_t i = 0; i < NUM_OUTPUTS; i++) {
    int16_t y = (i == 0) ? DASH_OUT0_Y : DASH_OUT1_Y;
    tft.fillRect(170, y, 70, 10, ST77XX_BLACK);
    drawOutputPowerBadge(170, y, outputsPowerEnabled, outputs[i].type);
  }
}

void displayUpdateFooter(float fps, IPAddress sourceIP = IPAddress(0,0,0,0)) {
  (void)fps;
  (void)sourceIP;
}

void displayUpdateOutputActive(uint8_t index, bool active, OutputType type) {
  (void)index;
  (void)active;
  (void)type;
}

#else

#define NUM_INFO_SCREENS 3

char displayDeviceName[18] = {0};

void setDisplayName(const char* name) {
  strncpy(displayDeviceName, name, 17);
  displayDeviceName[17] = '\0';
}

void displayInit() {}

void displayStartup() {
  Serial.print(FIRMWARE_NAME);
  Serial.print(" ");
  Serial.println(BOARD_PROFILE_LABEL);
}

void displayError(const char* errorMsg, const char* detail) {
  Serial.print("Display error: ");
  Serial.print(errorMsg);
  if (detail != NULL) {
    Serial.print(" - ");
    Serial.print(detail);
  }
  Serial.println();
}

void displayDashboard(const char* ssid, IPAddress ip, bool connected, bool reconnecting,
                      int rssi, bool staticIPActive, OutputConfig outputs[NUM_OUTPUTS],
                      bool outputsPowerEnabled) {
  (void)reconnecting;
  (void)outputsPowerEnabled;
  Serial.print("Dashboard: ");
  Serial.print(ssid);
  Serial.print(" ");
  Serial.println(ip);
}

void displayInfo(const char* ssid, bool connected, int rssi, bool staticIPActive) {
  (void)connected;
  (void)rssi;
  (void)staticIPActive;
  Serial.print("Info: ");
  Serial.println(ssid);
}

void displayEditSettings(OutputConfig outputs[NUM_OUTPUTS], uint8_t editFocus,
                         const char* errorMsg = nullptr) {
  (void)outputs;
  (void)editFocus;
  if (errorMsg && errorMsg[0]) {
    Serial.print("Edit error: ");
    Serial.println(errorMsg);
  }
}

void displayTestMode(uint8_t index, const char* name) {
  Serial.print("Test mode ");
  Serial.print(index);
  Serial.print(": ");
  Serial.println(name);
}

void displayUpdateConnectionBanner(bool connected, bool reconnecting) {
  (void)connected;
  (void)reconnecting;
}

void displayUpdateBattery() {}

void displayUpdateOutputPower(OutputConfig outputs[NUM_OUTPUTS], bool outputsPowerEnabled) {
  (void)outputs;
  (void)outputsPowerEnabled;
}

void displayUpdateFooter(float fps, IPAddress sourceIP = IPAddress(0,0,0,0)) {}

void displayUpdateOutputActive(uint8_t outputIndex, bool active, OutputType type) {
  Serial.print("Output ");
  Serial.print(outputIndex);
  Serial.print(" ");
  Serial.print(typeName(type));
  Serial.println(active ? " active" : " idle");
}

#endif

#endif // DISPLAY_H
