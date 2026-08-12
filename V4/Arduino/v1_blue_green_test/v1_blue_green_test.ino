/*
 * v1_blue_green_test — Standalone V1 Huzzah32 LED test
 * =====================================================
 * No WiFi, no Art-Net. Drives output 1 only (GPIO 12) with a moving
 * blue/green rainbow across 72 pixels. Output 0 (GPIO 32 / badge) is
 * left off.
 *
 * Upload (from V4/Arduino/):
 *   ./v1_blue_green_test_upload.sh --auto
 */

#include <Arduino.h>
#include <Adafruit_NeoPixel.h>

#ifndef LED_BUILTIN
  #define LED_BUILTIN 13
#endif

// V1 Huzzah32 output 1 — collar / long strip
static const uint8_t OUTPUT1_PIN = 12;
static const uint16_t PIXEL_COUNT = 72;

// Green (~21845) through cyan (~32768) to blue (~43690) on the 16-bit hue wheel
static const uint16_t HUE_MIN = 20000;
static const uint16_t HUE_MAX = 48000;
static const uint16_t HUE_BAND = HUE_MAX - HUE_MIN;

Adafruit_NeoPixel strip(PIXEL_COUNT, OUTPUT1_PIN, NEO_GRB + NEO_KHZ800);

uint16_t rainbowOffset = 0;

void setup() {
  pinMode(LED_BUILTIN, OUTPUT);
  digitalWrite(LED_BUILTIN, LOW);

  Serial.begin(115200);
  delay(300);
  Serial.println();
  Serial.println("V1 blue/green test firmware");
  Serial.printf("Output 1: pin %u, %u pixels, no WiFi\n", OUTPUT1_PIN, PIXEL_COUNT);

  strip.begin();
  strip.setBrightness(255);
  strip.clear();
  strip.show();
  Serial.println("LED strip ready — running blue/green rainbow");
}

void loop() {
  for (uint16_t p = 0; p < PIXEL_COUNT; p++) {
    uint16_t hue = HUE_MIN + (uint16_t)(((uint32_t)HUE_BAND * p / PIXEL_COUNT + rainbowOffset) % HUE_BAND);
    strip.setPixelColor(p, strip.ColorHSV(hue, 255, 255));
  }
  strip.show();

  rainbowOffset += 300;
  digitalWrite(LED_BUILTIN, (millis() / 400) & 1);

  delay(25);
}
