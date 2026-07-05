/*
 * audio.h — PrimusV3 Audio Playback
 * ====================================================
 * Music Maker FeatherWing (VS1053B) via Adafruit VS1053 Library.
 *
 * SD card access uses the ESP32 built-in SD.h (Arduino FS interface),
 * which is what dplasa's FTPClientServer expects.
 *
 * IMPORTANT: The FTP server and audio share the same SD bus.
 *   Stop FTP before starting audio, and vice versa.
 *   The shared mutex is 'sdBusy' — set true when audio or FTP is active.
 */

#ifndef AUDIO_H
#define AUDIO_H

#include "config.h"
#include <SD.h>

// =====================================================================
//  Shared SD bus mutex  (also used by ftp.h)
// =====================================================================
extern bool sdBusy;   // defined in the .ino

// =====================================================================
//  Internal state
// =====================================================================
char     _audioCurrentFile[65] = {0};
uint8_t  _audioVolume           = 80;
bool     _audioLooping          = false;
bool     _audioSdReady          = false;
bool     _audioHwReady          = false;
uint16_t _audioDuration         = 0;    // seconds, 0 = play full file
uint32_t _audioStartMillis      = 0;
uint32_t _audioSampleRate       = 0;

// =====================================================================
//  Music Maker FeatherWing (VS1053B) — SPI hardware codec
// =====================================================================

#include <Adafruit_VS1053.h>

Adafruit_VS1053_FilePlayer _musicMaker(
  MM_CS_PIN, MM_DCS_PIN, MM_DREQ_PIN, MM_SDCS_PIN);

void audioInit() {
  Serial.println("[Audio] Music Maker FeatherWing (VS1053)");

  if (!_musicMaker.begin()) {
    Serial.println("[Audio] ERROR: VS1053 begin() failed");
    return;
  }

  _musicMaker.setVolume(254, 254);  // start muted — unmuted when playback begins
  // No interrupt on ESP32 — SPI uses semaphores, can't be called from ISR.
  // feedBuffer() is called from audioUpdate() in the main loop instead.
  _audioHwReady = true;
  Serial.println("[Audio] VS1053 OK");

  if (!SD.begin(MM_SDCS_PIN)) {
    Serial.println("[Audio] WARNING: SD card not found — file playback unavailable");
    return;
  }
  Serial.println("[Audio] SD OK");
  _audioSdReady = true;
}

bool audioPlay(const char* filename, uint8_t volume, uint16_t duration = 0) {
  // Note: sdBusy is not checked here — audio can always interrupt itself or
  // start fresh. FTP is protected in the other direction: ftpUpdate() skips
  // handleFTP() while sdBusy is true, so audio always holds the SD bus.

  char trackPath[66];
  snprintf(trackPath, sizeof(trackPath), "%s%s", filename[0] == '/' ? "" : "/", filename);

  // Read WAV header: verify RIFF/WAVE magic and extract sample rate (offset 24)
  uint32_t incomingSampleRate = 0;
  {
    File f = SD.open(trackPath);
    if (!f) {
      Serial.print("[Audio] ERROR: file not found: "); Serial.println(trackPath);
      return false;
    }
    uint8_t header[28] = {0};
    f.read(header, 28);
    f.close();
    if (memcmp(header, "RIFF", 4) != 0 || memcmp(header + 8, "WAVE", 4) != 0) {
      Serial.print("[Audio] ERROR: not a WAV file: "); Serial.println(trackPath);
      return false;
    }
    if (memcmp(header + 12, "fmt ", 4) == 0) {
      memcpy(&incomingSampleRate, header + 24, 4);
    }
  }

  if (_musicMaker.playingMusic) {
    _musicMaker.stopPlaying();
    delay(20);  // let VS1053 fully flush before feeding new file header
  }

  // VS1053 holds internal sample-rate state across tracks. A soft reset clears
  // the decoder's PLL so the next stream header is parsed cleanly. Without this
  // the chip plays the new file at the wrong pitch or fails to start.
  if (incomingSampleRate != 0 && incomingSampleRate != _audioSampleRate) {
    Serial.printf("[Audio] Sample rate change %lu→%lu Hz — soft reset\n",
                  _audioSampleRate, incomingSampleRate);
    _musicMaker.softReset();  // resets DSP state; built-in 200ms settle time
  }
  _audioSampleRate = incomingSampleRate;

  strncpy(_audioCurrentFile, filename, 64);
  _audioCurrentFile[64] = '\0';
  _audioVolume    = volume;
  _audioLooping   = false;
  _audioDuration  = duration;
  _audioStartMillis = millis();
  sdBusy = true;

  // VS1053 volume: 0=max, 254=silent. Map 0-100 → 100-0 (scale to 0-100 range)
  uint8_t vs1053vol = (uint8_t)((100 - volume) * 254 / 100);
  _musicMaker.setVolume(vs1053vol, vs1053vol);

  bool ok = _musicMaker.startPlayingFile(trackPath);
  if (!ok) {
    Serial.print("[Audio] ERROR: could not open ");
    Serial.println(trackPath);
    sdBusy = false;
    _audioCurrentFile[0] = '\0';
  } else {
    Serial.print("[Audio] Playing: ");
    Serial.println(filename);
  }
  return ok;
}

void audioStop() {
  if (_musicMaker.playingMusic) _musicMaker.stopPlaying();
  _musicMaker.setVolume(254, 254);
  _audioCurrentFile[0] = '\0';
  _audioLooping     = false;
  _audioDuration    = 0;
  _audioStartMillis = 0;
  _audioSampleRate  = 0;
  sdBusy = false;
  Serial.println("[Audio] Stopped");
}

void audioPause() {
  _musicMaker.pausePlaying(true);
  _musicMaker.setVolume(254, 254);
  Serial.println("[Audio] Paused");
}

void audioSetVolume(uint8_t volume) {
  _audioVolume = volume;
  uint8_t vs1053vol = (uint8_t)((100 - volume) * 254 / 100);
  _musicMaker.setVolume(vs1053vol, vs1053vol);
}

void audioTestTone() {
  if (_musicMaker.playingMusic) _musicMaker.stopPlaying();
  Serial.println("[Audio] Test tone: 1kHz, 500ms");
  _musicMaker.sineTest(0x44, 500);
  // Do NOT call setVolume() here. sineTest() calls reset() internally which
  // can leave DREQ low briefly; sciWrite() does not check DREQ, so any SCI
  // write immediately after sineTest() may be dropped and corrupt VS1053 state.
  Serial.println("[Audio] Test tone complete");
}

void audioBootTest() {
  if (!_audioHwReady) return;
  Serial.println("[Boot] Sine test (1kHz, 500ms)...");
  _musicMaker.setVolume(40, 40);
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

void audioLoop(const char* filename, uint8_t volume, uint16_t duration = 0) {
  audioPlay(filename, volume, duration);
  _audioLooping = true;  // must be set after audioPlay() — audioPlay() resets it to false
}

void audioUpdate() {
  // Duration cutoff — takes priority over looping
  if (_audioDuration > 0 && _audioCurrentFile[0] != '\0') {
    if ((millis() - _audioStartMillis) >= (uint32_t)_audioDuration * 1000) {
      audioStop();
      return;
    }
  }

  if (_musicMaker.playingMusic) {
    _musicMaker.feedBuffer();
  } else {
    if (_audioLooping && _audioCurrentFile[0] != '\0') {
      _musicMaker.startPlayingFile(_audioCurrentFile);
    } else if (_audioCurrentFile[0] != '\0') {
      _musicMaker.setVolume(254, 254);
      _audioCurrentFile[0] = '\0';
      sdBusy = false;
    }
  }
}

bool audioIsPlaying() {
  return _musicMaker.playingMusic;
}

const char* audioCurrentFile() {
  return _audioCurrentFile;
}

// =====================================================================
//  SD helpers
// =====================================================================

bool audioSdIsReady() { return _audioSdReady; }

bool audioSdInit() {
  _audioSdReady = SD.begin(MM_SDCS_PIN);
  if (_audioSdReady) Serial.println("[SD] Init OK");
  else               Serial.println("[SD] Init failed — no card?");
  return _audioSdReady;
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
