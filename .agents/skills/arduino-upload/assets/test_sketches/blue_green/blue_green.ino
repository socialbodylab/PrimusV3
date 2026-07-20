/*
 * blue_green — AUS canonical "is the board alive?" test sketch.
 * =================================================================
 *
 * The smallest meaningful hardware test: drive an LED strip (or the built-in
 * LED) with a moving blue→green rainbow and print a startup banner to Serial.
 * No WiFi, no networking, no dependencies beyond Adafruit_NeoPixel.
 *
 * Designed to pair with an AUS-conforming uploader using `--expect`:
 *
 *   ./blue_green_upload.sh --auto --expect "blue_green ready"
 *
 * If the board boots and prints the banner, --expect matches and the script
 * exits 0. If anything in the hardware path is broken (power, strip wiring,
 * bad flash), the banner never appears and the script exits 11.
 *
 * Pin/pixel defaults target an ESP32 Feather with a NeoPixel strip on GPIO 12.
 * Override at compile time with -D AUS_BLUE_GREEN_PIN and -D AUS_BLUE_GREEN_PIXELS.
 */

#include <Arduino.h>
#include <Adafruit_NeoPixel.h>

#ifndef AUS_BLUE_GREEN_PIN
  #define AUS_BLUE_GREEN_PIN 12
#endif

#ifndef AUS_BLUE_GREEN_PIXELS
  #define AUS_BLUE_GREEN_PIXELS 16
#endif

#ifndef LED_BUILTIN
  #define LED_BUILTIN 13
#endif

Adafruit_NeoPixel strip(AUS_BLUE_GREEN_PIXELS, AUS_BLUE_GREEN_PIN, NEO_GRB + NEO_KHZ800);

// Green (~21845) through cyan (~32768) to blue (~43690) on the 16-bit hue wheel.
const uint16_t HUE_MIN = 20000;
const uint16_t HUE_MAX = 48000;
const uint16_t HUE_BAND = HUE_MAX - HUE_MIN;

uint16_t offset = 0;
uint32_t lastBanner = 0;

void setup() {
  pinMode(LED_BUILTIN, OUTPUT);
  digitalWrite(LED_BUILTIN, LOW);

  Serial.begin(115200);
  delay(300);
  Serial.println();
  Serial.println("blue_green ready");
  Serial.printf("pin=%u pixels=%u\n", AUS_BLUE_GREEN_PIN, AUS_BLUE_GREEN_PIXELS);

  strip.begin();
  strip.setBrightness(128);
  strip.clear();
  strip.show();
  Serial.println("strip initialized — running rainbow");
  lastBanner = millis();
}

void loop() {
  for (uint16_t p = 0; p < AUS_BLUE_GREEN_PIXELS; p++) {
    uint16_t hue = HUE_MIN + (uint16_t)(((uint32_t)HUE_BAND * p / AUS_BLUE_GREEN_PIXELS + offset) % HUE_BAND);
    strip.setPixelColor(p, strip.ColorHSV(hue, 255, 255));
  }
  strip.show();

  offset += 300;
  digitalWrite(LED_BUILTIN, (millis() / 400) & 1);

  // Re-print the banner every 2 seconds so a serial monitor that connects
  // after boot (or a test harness using --expect) can still catch it. The
  // first "blue_green ready" prints in setup(); this is a heartbeat.
  if (millis() - lastBanner > 2000) {
    Serial.println("blue_green ready");
    lastBanner = millis();
  }

  delay(25);
}
