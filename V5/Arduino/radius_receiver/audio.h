/*
 * audio.h — Radius V4 audio playback (Music Maker / VS1053 on HUZZAH32)
 *
 * SD bus is shared with FTP — use sdBusy mutex in the main sketch.
 */

#ifndef AUDIO_H
#define AUDIO_H

#include "config.h"
#include "telemetry.h"
#include <SD.h>
#include <Adafruit_VS1053.h>

extern bool sdBusy;

char     _audioCurrentFile[65] = {0};
uint32_t _audioSampleRate      = 0;
uint8_t  _audioVolume          = 80;
bool   _audioLooping = false;
bool   _audioHwReady = false;
bool   _audioSdReady = false;
uint8_t _audioPlaybackState = TRACK_STATE_STOPPED;
uint8_t _lastAppliedVolume = 255;
uint16_t _audioDuration = 0;
uint32_t _audioStartMillis = 0;

Adafruit_VS1053_FilePlayer _musicMaker(
  MM_CS_PIN, MM_DCS_PIN, MM_DREQ_PIN, MM_SDCS_PIN);

bool audioIsPlaying() {
  return _musicMaker.playingMusic;
}

static void _notifyTrack(uint8_t state) {
  _audioPlaybackState = state;
  const char* name = (state == TRACK_STATE_STOPPED) ? "" : _audioCurrentFile;
  sendAudioStatus(state, name);
}

// SCI_VOL attenuation of 0xFE per channel (setVolume(254, 254) and above)
// is the VS1053's ANALOG POWERDOWN command, not just "very quiet" — once
// the analog stage is down, output can stay dead until a full reset. The
// old boot beep's internal reset() was accidentally rescuing the chip from
// the powerdown that audioInit's mute put it in. Never write 254: clamp
// all attenuation to 250 (-125 dB, inaudible, analog stage stays alive).
#define VS1053_MAX_SAFE_ATTENUATION 250

static void _applyVolume(uint8_t volume) {
  if (volume == _lastAppliedVolume) return;
  _lastAppliedVolume = volume;
  _audioVolume = volume;
  uint8_t vs1053vol = (uint8_t)((100 - volume) * 254 / 100);
  if (vs1053vol > VS1053_MAX_SAFE_ATTENUATION) vs1053vol = VS1053_MAX_SAFE_ATTENUATION;
  _musicMaker.setVolume(vs1053vol, vs1053vol);
}

// The only allowed way to mute the chip directly. Invalidates the
// _lastAppliedVolume cache so the next _applyVolume() always writes —
// a bare mute leaves the cache claiming the old volume and
// _applyVolume() then skips the unmute (silent playback bug).
static void _muteChip() {
  _musicMaker.setVolume(VS1053_MAX_SAFE_ATTENUATION, VS1053_MAX_SAFE_ATTENUATION);
  _lastAppliedVolume = 255;
}

void audioInit() {
  Serial.println("[Audio] Music Maker FeatherWing (VS1053)");

  if (!_musicMaker.begin()) {
    Serial.println("[Audio] ERROR: VS1053 begin() failed");
    return;
  }
  _muteChip();  // start muted — unmuted when playback begins
  // No interrupt on ESP32 — SPI uses semaphores, can't be called from ISR.
  // feedBuffer() is called from audioUpdate() in the main loop instead.
  _audioHwReady = true;
  Serial.println("[Audio] VS1053 OK");

  if (!SD.begin(MM_SDCS_PIN)) {
    Serial.println("[Audio] WARNING: SD card not found — file playback unavailable");
    return;
  }
  _applyVolume(80);
  _audioSdReady = true;
  Serial.println("[Audio] SD OK");
}

bool audioPlay(const char* filename, uint8_t volume, uint16_t duration = 0) {
  if (_musicMaker.playingMusic) {
    _musicMaker.stopPlaying();
    delay(20);  // let VS1053 fully flush before feeding new file header
  }

  char trackPath[66];
  snprintf(trackPath, sizeof(trackPath), "%s%s", filename[0] == '/' ? "" : "/", filename);

  // Read WAV header: verify RIFF/WAVE magic and extract sample rate (offset 24).
  uint32_t incomingSampleRate = 0;
  File f = SD.open(trackPath);
  if (f) {
    uint8_t header[28] = {0};
    f.read(header, 28);
    f.close();
    if (memcmp(header, "RIFF", 4) != 0 || memcmp(header + 8, "WAVE", 4) != 0) {
      Serial.print("[Audio] ERROR: not a WAV file: ");
      Serial.println(trackPath);
      _notifyTrack(TRACK_STATE_STOPPED);
      return false;
    }
    if (memcmp(header + 12, "fmt ", 4) == 0) {
      memcpy(&incomingSampleRate, header + 24, 4);
    }
  }

  // VS1053 holds internal sample-rate state across tracks. A soft reset clears
  // the decoder's PLL so the next stream header is parsed cleanly. Without this
  // the chip plays the new file at the wrong pitch or fails to start.
  if (incomingSampleRate != 0 && incomingSampleRate != _audioSampleRate) {
    Serial.printf("[Audio] Sample rate change %lu→%lu Hz — reset\n",
                  _audioSampleRate, incomingSampleRate);
    // Use the library's full reset(), never a bare softReset(): a soft
    // reset clears SCI_CLOCKF (clock multiplier), and at 1.0x the chip
    // cannot decode — playback streams silently while playingMusic stays
    // true. reset() restores CLOCKF with the settle delays this hardware
    // is known to need (it is the same routine sineTest() runs). It also
    // sets chip volume to 40/40, so invalidate the cache to force the
    // _applyVolume() below to rewrite SCI_VOL.
    _musicMaker.reset();
    _lastAppliedVolume = 255;
    uint16_t clockf = _musicMaker.sciRead(VS1053_REG_CLOCKF);
    Serial.printf("[Audio] post-reset CLOCKF=0x%04X %s\n", clockf,
                  clockf == 0x6000 ? "(ok)" : "(BAD — decode will be silent)");
  }
  _audioSampleRate = incomingSampleRate;

  strncpy(_audioCurrentFile, trackPath, 64);
  _audioCurrentFile[64] = '\0';
  _audioLooping = false;
  _audioDuration = duration;
  _audioStartMillis = millis();
  sdBusy = true;
  _applyVolume(volume);

  bool ok = _musicMaker.startPlayingFile(trackPath);
  if (!ok) {
    Serial.print("[Audio] ERROR: could not open ");
    Serial.println(trackPath);
    sdBusy = false;
    _audioCurrentFile[0] = '\0';
    _audioDuration = 0;
    _notifyTrack(TRACK_STATE_STOPPED);
  } else {
    Serial.print("[Audio] Playing: ");
    Serial.println(filename);
    _notifyTrack(TRACK_STATE_PLAYING);
  }
  return ok;
}

void audioStop() {
  if (_musicMaker.playingMusic) _musicMaker.stopPlaying();
  _audioCurrentFile[0] = '\0';
  _audioLooping = false;
  _audioDuration = 0;
  _audioStartMillis = 0;
  _audioSampleRate = 0;
  sdBusy = false;
  _lastAppliedVolume = 255;
  _notifyTrack(TRACK_STATE_STOPPED);
  Serial.println("[Audio] Stopped");
}

void audioPause() {
  _musicMaker.pausePlaying(true);
  _notifyTrack(TRACK_STATE_PAUSED);
  Serial.println("[Audio] Paused");
}

void audioSetVolume(uint8_t volume) {
  _applyVolume(volume);
}

void audioTestTone() {
  if (_musicMaker.playingMusic) _musicMaker.stopPlaying();
  Serial.println("[Audio] Test tone: 1kHz, 500ms");
  _musicMaker.sineTest(0x44, 500);
  Serial.println("[Audio] Test tone complete");
}

void audioLoop(const char* filename, uint8_t volume, uint16_t duration = 0) {
  audioPlay(filename, volume, duration);
  _audioLooping = true;  // must be set after audioPlay() — audioPlay() resets it to false
}

void audioUpdate() {
  if (_audioDuration > 0 && _audioCurrentFile[0] != '\0') {
    if ((millis() - _audioStartMillis) >= (uint32_t)_audioDuration * 1000UL) {
      audioStop();
      return;
    }
  }

  if (_musicMaker.playingMusic) {
    _musicMaker.feedBuffer();
  } else {
    if (_audioLooping && _audioCurrentFile[0] != '\0') {
      if (_musicMaker.startPlayingFile(_audioCurrentFile)) {
        _notifyTrack(TRACK_STATE_PLAYING);
      }
    } else if (_audioCurrentFile[0] != '\0') {
      _muteChip();
      _audioCurrentFile[0] = '\0';
      _audioDuration = 0;
      sdBusy = false;
      _notifyTrack(TRACK_STATE_STOPPED);
    }
  }
}

const char* audioCurrentFile() {
  return _audioCurrentFile;
}

uint8_t audioPlaybackState() {
  return _audioPlaybackState;
}

bool audioSdIsReady() {
  return _audioSdReady;
}

void audioBootTest() {
  if (!_audioHwReady) return;
  Serial.println("[Boot] Sine test (1kHz, 500ms)...");
  _musicMaker.setVolume(40, 40);
  _lastAppliedVolume = 255;  // chip volume touched directly — invalidate cache
  _musicMaker.sineTest(0x44, 500);
  Serial.println("[Boot] Sine test complete");

  if (!_audioSdReady) {
    Serial.println("[Boot] SD not ready — skipping file playback");
    return;
  }

  char filename[65] = {0};
  File root = SD.open("/");
  if (!root) { Serial.println("[Boot] Failed to open SD root"); return; }
  while (true) {
    File entry = root.openNextFile();
    if (!entry) { Serial.println("[Boot] No WAV files found on SD"); break; }
    if (!entry.isDirectory()) {
      const char* ext = strrchr(entry.name(), '.');
      if (ext && strcasecmp(ext, ".wav") == 0) {
        strncpy(filename, entry.name(), 64);
        entry.close();
        root.close();
        Serial.print("[Boot] Playing: "); Serial.println(filename);
        audioPlay(filename, 60, 2);
        return;
      }
    }
    entry.close();
  }
  root.close();
}

uint16_t sdFileCount() {
  File root = SD.open("/");
  if (!root) return 0;
  uint16_t count = 0;
  while (true) {
    File entry = root.openNextFile();
    if (!entry) break;
    if (!entry.isDirectory()) count++;
    entry.close();
  }
  root.close();
  return count;
}

#endif // AUDIO_H
