/*
 * cues.h — Audio Cue Map (/cues.json on SD card)
 */

#ifndef CUES_H
#define CUES_H

#include "config.h"
#include <SD.h>
#include <ArduinoJson.h>

#define CUES_MAX 64

struct AudioCue {
  char     filename[33];
  uint16_t duration;
};

static AudioCue _cueMap[CUES_MAX];
static uint8_t  _cueNumbers[CUES_MAX];
static uint8_t  _cueCount = 0;

void cuesLoad() {
  _cueCount = 0;

  File f = SD.open("/cues.json");
  if (!f) {
    Serial.println("[Cues] No /cues.json found — cue commands disabled");
    return;
  }

  JsonDocument doc;
  DeserializationError err = deserializeJson(doc, f);
  f.close();

  if (err) {
    Serial.print("[Cues] Parse error: ");
    Serial.println(err.c_str());
    return;
  }

  for (JsonPair kv : doc.as<JsonObject>()) {
    if (_cueCount >= CUES_MAX) break;

    uint8_t num = (uint8_t)atoi(kv.key().c_str());
    AudioCue& cue = _cueMap[_cueCount];
    cue.duration = 0;
    cue.filename[0] = '\0';

    if (kv.value().is<const char*>()) {
      strncpy(cue.filename, kv.value().as<const char*>(), 32);
      cue.filename[32] = '\0';
    } else if (kv.value().is<JsonObject>()) {
      JsonObject obj = kv.value().as<JsonObject>();
      const char* fn = obj["file"] | "";
      strncpy(cue.filename, fn, 32);
      cue.filename[32] = '\0';
      cue.duration = obj["duration"] | 0;
    } else {
      continue;
    }

    if (cue.filename[0] == '\0') continue;

    _cueNumbers[_cueCount] = num;
    _cueCount++;

    Serial.printf("[Cues] %d -> %s", num, cue.filename);
    if (cue.duration > 0) Serial.printf(" (%ds)", cue.duration);
    Serial.println();
  }

  Serial.printf("[Cues] Loaded %d cue(s)\n", _cueCount);
}

bool cueLookup(uint8_t num, AudioCue* out) {
  for (uint8_t i = 0; i < _cueCount; i++) {
    if (_cueNumbers[i] == num) {
      *out = _cueMap[i];
      return true;
    }
  }
  return false;
}

#endif // CUES_H
