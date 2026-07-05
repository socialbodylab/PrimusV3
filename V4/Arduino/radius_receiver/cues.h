/*
 * cues.h — Audio Cue Map
 * ====================================================
 * Loads /cues.json from the SD card at boot and provides
 * cue-number → action lookups for Art-Net cmd 6/7 and OSC /cue/N.
 *
 * JSON format (all forms supported):
 *   { "1": "file.wav" }                              — play shorthand
 *   { "2": { "file": "file.wav", "duration": 30 } } — legacy object
 *   { "3": { "cmd": "loop", "file": "a.wav", "volume": 80 } }
 *   { "5": { "cmd": "stop" } }
 *   { "6": { "cmd": "volume", "volume": 70 } }
 *
 * Fields:
 *   cmd:      "play" (default), "loop", "stop", "volume"
 *   file:     WAV filename on SD (required for play/loop)
 *   volume:   0–100 (optional; omit to use device current volume)
 *   duration: seconds, 0 = play full file (optional)
 *   delay:    milliseconds before executing (optional; default 0)
 *
 * Cue numbers: 1–255. Max 64 cues loaded.
 */

#ifndef CUES_H
#define CUES_H

#include "config.h"
#include <SD.h>
#include <ArduinoJson.h>

// ── Cue command types ─────────────────────────────────────────────────
#define AUDIO_CUE_CMD_PLAY   0
#define AUDIO_CUE_CMD_LOOP   1
#define AUDIO_CUE_CMD_STOP   2
#define AUDIO_CUE_CMD_VOLUME 3

#define CUES_MAX 64
#define CUE_VOLUME_UNSET 255  // use device's current _audioVolume

struct AudioCue {
  uint8_t  cmd;           // AUDIO_CUE_CMD_*
  char     filename[65];  // empty for stop / volume
  uint8_t  volume;        // 0–100, or CUE_VOLUME_UNSET
  uint16_t duration;      // seconds; 0 = full file
  uint16_t delay;         // milliseconds before executing; 0 = immediate
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
    if (num == 0) continue;  // 0 is not a valid cue number

    AudioCue& cue  = _cueMap[_cueCount];
    cue.cmd        = AUDIO_CUE_CMD_PLAY;
    cue.filename[0] = '\0';
    cue.volume     = CUE_VOLUME_UNSET;
    cue.duration   = 0;
    cue.delay      = 0;

    if (kv.value().is<const char*>()) {
      // Shorthand: "1": "file.wav" → play with device default volume
      strncpy(cue.filename, kv.value().as<const char*>(), 64);
      cue.filename[64] = '\0';

    } else if (kv.value().is<JsonObject>()) {
      JsonObject obj = kv.value().as<JsonObject>();

      // cmd field — defaults to "play"
      const char* cmdStr = obj["cmd"] | "play";
      if      (strcmp(cmdStr, "loop")   == 0) cue.cmd = AUDIO_CUE_CMD_LOOP;
      else if (strcmp(cmdStr, "stop")   == 0) cue.cmd = AUDIO_CUE_CMD_STOP;
      else if (strcmp(cmdStr, "volume") == 0) cue.cmd = AUDIO_CUE_CMD_VOLUME;
      else                                    cue.cmd = AUDIO_CUE_CMD_PLAY;

      // file — required for play/loop
      if (cue.cmd == AUDIO_CUE_CMD_PLAY || cue.cmd == AUDIO_CUE_CMD_LOOP) {
        const char* fn = obj["file"] | "";
        strncpy(cue.filename, fn, 64);
        cue.filename[64] = '\0';
      }

      // volume — optional; CUE_VOLUME_UNSET means "use device current"
      if (obj["volume"].is<int>()) {
        int v = obj["volume"] | -1;
        cue.volume = (v >= 0 && v <= 100) ? (uint8_t)v : CUE_VOLUME_UNSET;
      }

      cue.duration = obj["duration"] | 0;
      cue.delay    = obj["delay"]    | 0;

    } else {
      continue;
    }

    // Skip play/loop with no filename
    if ((cue.cmd == AUDIO_CUE_CMD_PLAY || cue.cmd == AUDIO_CUE_CMD_LOOP)
        && cue.filename[0] == '\0') continue;

    _cueNumbers[_cueCount] = num;
    _cueCount++;

    static const char* _cmdNames[] = { "play", "loop", "stop", "volume" };
    Serial.printf("[Cues] %d -> %s", num, _cmdNames[cue.cmd < 4 ? cue.cmd : 0]);
    if (cue.filename[0])     { Serial.print(" \""); Serial.print(cue.filename); Serial.print("\""); }
    if (cue.volume != CUE_VOLUME_UNSET) Serial.printf(" vol=%d", cue.volume);
    if (cue.duration > 0)    Serial.printf(" dur=%ds", cue.duration);
    if (cue.delay > 0)       Serial.printf(" delay=%dms", cue.delay);
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
