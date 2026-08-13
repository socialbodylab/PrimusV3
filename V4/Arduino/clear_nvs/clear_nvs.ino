/*
 * clear_nvs — One-shot factory wipe for Primus / Radius receivers
 * ================================================================
 * Erases the entire ESP32 NVS partition, which clears:
 *   - Device short name (ArtAddress / Rename)
 *   - Character / performer show info
 *   - Static IP / gateway / subnet
 *   - Output types and virtual pixel counts (Primus)
 *   - Receive mode / universe base (Primus)
 *   - Upload override markers (fwOvrBuild)
 *   - ESP32 WiFi station credentials stored by the WiFi stack
 *
 * Covers both Preferences namespaces used by this project:
 *   "primus35"  — current Primus V3.5 / V3.6 / V4 firmware
 *   "artnet"    — Radius + older Primus V3.0 / V3.1 firmware
 *
 * After flashing, open the serial monitor at 115200 baud. You should see
 * "NVS CLEAR COMPLETE". Then re-flash normal Primus or Radius firmware.
 *
 * Upload (from V4/Arduino/):
 *   ./clear_nvs_upload.sh -v1 --auto
 *   ./clear_nvs_upload.sh -v2 --auto
 *   ./clear_nvs_upload.sh -v3 --auto
 *   ./clear_nvs_upload.sh --board radius_v1 --auto
 */

#include <Arduino.h>
#include <Preferences.h>
#include <nvs_flash.h>

// Known Preferences namespaces used by Primus / Radius firmware lines.
static const char* const KNOWN_NAMESPACES[] = {
  "primus35",
  "artnet",
};
static const size_t KNOWN_NAMESPACE_COUNT =
  sizeof(KNOWN_NAMESPACES) / sizeof(KNOWN_NAMESPACES[0]);

#ifndef LED_BUILTIN
  #define LED_BUILTIN 13
#endif

static bool clearComplete = false;
static bool clearSucceeded = false;

static void blinkForever(bool success) {
  // Fast blink = success; slow blink = failure.
  const unsigned long onMs = success ? 80 : 400;
  const unsigned long offMs = success ? 80 : 400;
  while (true) {
    digitalWrite(LED_BUILTIN, HIGH);
    delay(onMs);
    digitalWrite(LED_BUILTIN, LOW);
    delay(offMs);
  }
}

static void clearKnownNamespaces() {
  Preferences prefs;
  for (size_t i = 0; i < KNOWN_NAMESPACE_COUNT; i++) {
    const char* ns = KNOWN_NAMESPACES[i];
    if (!prefs.begin(ns, false)) {
      Serial.printf("[clear_nvs] Namespace '%s' not present (ok)\n", ns);
      continue;
    }
    bool cleared = prefs.clear();
    prefs.end();
    Serial.printf("[clear_nvs] Namespace '%s' clear: %s\n",
                  ns, cleared ? "ok" : "failed");
  }
}

static bool eraseEntireNvs() {
  Serial.println("[clear_nvs] Erasing entire NVS flash partition...");

  // Arduino initializes NVS before setup(); deinit first or erase fails.
  esp_err_t err = nvs_flash_deinit();
  if (err != ESP_OK && err != ESP_ERR_NVS_NOT_INITIALIZED) {
    Serial.printf("[clear_nvs] nvs_flash_deinit failed: %s (%d)\n",
                  esp_err_to_name(err), (int)err);
    return false;
  }

  err = nvs_flash_erase();
  if (err != ESP_OK) {
    Serial.printf("[clear_nvs] nvs_flash_erase failed: %s (%d)\n",
                  esp_err_to_name(err), (int)err);
    return false;
  }

  err = nvs_flash_init();
  if (err != ESP_OK) {
    Serial.printf("[clear_nvs] nvs_flash_init failed after erase: %s (%d)\n",
                  esp_err_to_name(err), (int)err);
    return false;
  }

  Serial.println("[clear_nvs] NVS partition erased and re-initialized.");
  return true;
}

void setup() {
  pinMode(LED_BUILTIN, OUTPUT);
  digitalWrite(LED_BUILTIN, HIGH);

  Serial.begin(115200);
  delay(500);
  Serial.println();
  Serial.println("========================================");
  Serial.println(" Primus / Radius NVS factory clear");
  Serial.println("========================================");

  // Best-effort namespace clears first (useful log output even if the
  // partition erase below is what actually guarantees a clean slate).
  clearKnownNamespaces();

  clearSucceeded = eraseEntireNvs();
  clearComplete = true;

  if (clearSucceeded) {
    Serial.println();
    Serial.println("NVS CLEAR COMPLETE");
    Serial.println("Re-flash normal Primus or Radius firmware next.");
    Serial.println();
  } else {
    Serial.println();
    Serial.println("NVS CLEAR FAILED — see errors above.");
    Serial.println();
  }
}

void loop() {
  if (!clearComplete) {
    return;
  }
  // Stay here blinking so a USB-connected board visibly confirms the wipe.
  blinkForever(clearSucceeded);
}
