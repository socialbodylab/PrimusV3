/*
 * audio.h — PrimusV3 Audio Playback
 * ====================================================
 * Unified audio API behind a compile-time board switch:
 *   AUDIO_BOARD_MUSIC_MAKER  — VS1053B via Adafruit VS1053 Library
 *   AUDIO_BOARD_BFF          — MAX98357 I2S via ESP8266Audio
 *
 * SD card access uses the ESP32 built-in SD.h (Arduino FS interface).
 * This is the same interface used by AudioFileSourceSD and VS1053's
 * file player internally, and is what dplasa's FTPClientServer expects.
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
//  Internal state (shared across both implementations)
// =====================================================================
char    _audioCurrentFile[33] = {0};
uint8_t _audioVolume           = 80;
bool    _audioLooping          = false;
bool    _audioSdReady          = false;
bool    _audioHwReady          = false;

// =====================================================================
//  Music Maker FeatherWing (VS1053B) — SPI hardware codec
// =====================================================================
#if AUDIO_BOARD == AUDIO_BOARD_MUSIC_MAKER

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

bool audioPlay(const char* filename, uint8_t volume) {
  if (sdBusy) {
    Serial.println("[Audio] SD busy (FTP running) — play ignored");
    return false;
  }

  char trackPath[34];
  snprintf(trackPath, sizeof(trackPath), "%s%s", filename[0] == '/' ? "" : "/", filename);

  // Verify RIFF/WAVE header before committing SD bus
  {
    File f = SD.open(trackPath);
    if (!f) {
      Serial.print("[Audio] ERROR: file not found: "); Serial.println(trackPath);
      return false;
    }
    uint8_t magic[12] = {0};
    f.read(magic, 12);
    f.close();
    if (memcmp(magic, "RIFF", 4) != 0 || memcmp(magic + 8, "WAVE", 4) != 0) {
      Serial.print("[Audio] ERROR: not a WAV file: "); Serial.println(trackPath);
      return false;
    }
  }

  if (_musicMaker.playingMusic) _musicMaker.stopPlaying();

  strncpy(_audioCurrentFile, filename, 32);
  _audioCurrentFile[32] = '\0';
  _audioVolume  = volume;
  _audioLooping = false;
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
  _audioLooping = false;
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
  Serial.println("[Audio] Test tone complete");
}

void audioBootTest() {
  Serial.println("[Boot] Sine test (1kHz, 500ms)...");
  _musicMaker.sineTest(0x44, 500);
  Serial.println("[Boot] Sine test complete");

  if (!_audioSdReady) {
    Serial.println("[Boot] SD not ready — skipping file playback");
    return;
  }

  char filename[33] = {0};
  File root = SD.open("/");
  if (!root) { Serial.println("[Boot] Failed to open SD root"); return; }
  while (true) {
    File entry = root.openNextFile();
    if (!entry) { Serial.println("[Boot] No files found on SD"); break; }
    if (!entry.isDirectory()) {
      strncpy(filename, entry.name(), 32);
      entry.close();
      root.close();
      Serial.print("[Boot] Playing: "); Serial.println(filename);
      audioPlay(filename, 80);
      return;
    }
    entry.close();
  }
  root.close();
}

void audioLoop(const char* filename, uint8_t volume) {
  _audioLooping = true;
  audioPlay(filename, volume);
}

void audioUpdate() {
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
//  Audio BFF (MAX98357 I2S) — software WAV decode
// =====================================================================
#elif AUDIO_BOARD == AUDIO_BOARD_BFF

#include <AudioFileSourceSD.h>
#include <AudioFileSourceFunction.h>
#include <AudioGeneratorWAV.h>
#include <AudioOutputI2S.h>

AudioFileSourceSD*       _audioSource = nullptr;
AudioGeneratorWAV*       _audioGen    = nullptr;
AudioOutputI2S*          _audioOut    = nullptr;
AudioFileSourceFunction* _testSrc     = nullptr;
AudioGeneratorWAV*       _testGen     = nullptr;

void audioInit() {
  Serial.println("[Audio] Audio BFF (MAX98357 I2S)");

  // I2S output is independent of SD — create it first so test tone works without a card
  _audioOut = new AudioOutputI2S();
  _audioOut->SetPinout(BFF_BCK_PIN, BFF_WS_PIN, BFF_DATA_PIN);
#if BFF_SWAP_CLOCKS
  _audioOut->SwapClocks(true);
#endif
  _audioOut->SetBuffers(32, 2048);
  _audioOut->SetGain(0.5f);
  Serial.printf("[Audio] I2S pins — BCK:%d WS:%d DOUT:%d%s\n",
    BFF_BCK_PIN, BFF_WS_PIN, BFF_DATA_PIN, BFF_SWAP_CLOCKS ? " (clocks SWAPPED)" : "");
  Serial.println("[Audio] I2S output configured");

  if (!SD.begin(BFF_SDCS_PIN)) {
    Serial.println("[Audio] WARNING: SD card not found — file playback unavailable");
    return;
  }
  Serial.println("[Audio] SD OK");
  _audioSdReady = true;
}

bool audioPlay(const char* filename, uint8_t volume) {
  if (sdBusy) {
    Serial.println("[Audio] SD busy (FTP running) — play ignored");
    return false;
  }
  if (!_audioSdReady) {
    Serial.println("[Audio] SD not ready — play ignored");
    return false;
  }

  char trackPath[34];
  snprintf(trackPath, sizeof(trackPath), "%s%s", filename[0] == '/' ? "" : "/", filename);

  // Verify RIFF/WAVE header before committing SD bus
  {
    File f = SD.open(trackPath);
    if (!f) {
      Serial.print("[Audio] ERROR: file not found: "); Serial.println(trackPath);
      return false;
    }
    uint8_t magic[12] = {0};
    f.read(magic, 12);
    f.close();
    if (memcmp(magic, "RIFF", 4) != 0 || memcmp(magic + 8, "WAVE", 4) != 0) {
      Serial.print("[Audio] ERROR: not a WAV file: "); Serial.println(trackPath);
      return false;
    }
  }

  // Stop test tone or existing playback
  if (_testGen && _testGen->isRunning()) _testGen->stop();
  delete _testGen; _testGen = nullptr;
  delete _testSrc; _testSrc = nullptr;

  if (_audioGen && _audioGen->isRunning()) _audioGen->stop();
  delete _audioGen;    _audioGen    = nullptr;
  delete _audioSource; _audioSource = nullptr;

  strncpy(_audioCurrentFile, filename, 32);
  _audioCurrentFile[32] = '\0';
  _audioVolume  = volume;
  _audioLooping = false;
  sdBusy = true;

  _audioOut->SetGain(volume / 100.0f);

  _audioSource = new AudioFileSourceSD(trackPath);
  if (!_audioSource->isOpen()) {
    Serial.print("[Audio] ERROR: could not open ");
    Serial.println(trackPath);
    delete _audioSource; _audioSource = nullptr;
    sdBusy = false;
    _audioCurrentFile[0] = '\0';
    return false;
  }

  _audioGen = new AudioGeneratorWAV();
  bool ok = _audioGen->begin(_audioSource, _audioOut);
  if (!ok) {
    Serial.println("[Audio] ERROR: WAV begin() failed");
    delete _audioGen;    _audioGen    = nullptr;
    delete _audioSource; _audioSource = nullptr;
    sdBusy = false;
    _audioCurrentFile[0] = '\0';
    return false;
  }

  Serial.print("[Audio] Playing: ");
  Serial.println(filename);
  return true;
}

void audioStop() {
  if (_testGen && _testGen->isRunning()) _testGen->stop();
  delete _testGen; _testGen = nullptr;
  delete _testSrc; _testSrc = nullptr;

  if (_audioGen && _audioGen->isRunning()) _audioGen->stop();
  delete _audioGen;    _audioGen    = nullptr;
  delete _audioSource; _audioSource = nullptr;
  _audioCurrentFile[0] = '\0';
  _audioLooping = false;
  sdBusy = false;
  Serial.println("[Audio] Stopped");
}

void audioPause() {
  // ESP8266Audio has no native pause. On BFF hardware, pause = stop.
  // A subsequent play command will restart from the beginning of the file.
  audioStop();
  Serial.println("[Audio] Pause → Stop (BFF has no native pause)");
}

void audioSetVolume(uint8_t volume) {
  _audioVolume = volume;
  if (_audioOut) _audioOut->SetGain(volume / 100.0f);
}

void audioTestTone() {
  // Stop any regular playback
  if (_audioGen && _audioGen->isRunning()) _audioGen->stop();
  delete _audioGen;    _audioGen    = nullptr;
  delete _audioSource; _audioSource = nullptr;
  _audioCurrentFile[0] = '\0';
  _audioLooping = false;
  sdBusy = false;

  // Stop any previous test tone
  if (_testGen && _testGen->isRunning()) _testGen->stop();
  delete _testGen; _testGen = nullptr;
  delete _testSrc; _testSrc = nullptr;

  _testSrc = new AudioFileSourceFunction(2.0f, 1, 44100, 16);
  _testSrc->addAudioGenerators([](float t) -> float {
    return sinf(2.0f * M_PI * 440.0f * t);
  });
  _testGen = new AudioGeneratorWAV();
  _testGen->begin(_testSrc, _audioOut);
  Serial.print("[Audio] Test tone started — isRunning=");
  Serial.println(_testGen->isRunning() ? "YES" : "NO (generator failed to start)");
}

void audioLoop(const char* filename, uint8_t volume) {
  _audioLooping = true;
  audioPlay(filename, volume);
}

void audioUpdate() {
  // Test tone takes priority over regular playback
  if (_testGen && _testGen->isRunning()) {
    if (!_testGen->loop()) {
      _testGen->stop();
      delete _testGen; _testGen = nullptr;
      delete _testSrc; _testSrc = nullptr;
      Serial.println("[Audio] Test tone complete");
    }
    return;
  }

  if (_audioGen && _audioGen->isRunning()) {
    if (!_audioGen->loop()) {
      // Finished
      _audioGen->stop();
      if (_audioLooping && _audioCurrentFile[0] != '\0') {
        // Reopen and restart for loop
        delete _audioGen;    _audioGen    = nullptr;
        delete _audioSource; _audioSource = nullptr;

        _audioSource = new AudioFileSourceSD(_audioCurrentFile);
        _audioGen    = new AudioGeneratorWAV();
        _audioGen->begin(_audioSource, _audioOut);
      } else {
        delete _audioGen;    _audioGen    = nullptr;
        delete _audioSource; _audioSource = nullptr;
        _audioCurrentFile[0] = '\0';
        sdBusy = false;
      }
    }
  }
}

bool audioIsPlaying() {
  return (_testGen && _testGen->isRunning()) || (_audioGen && _audioGen->isRunning());
}

const char* audioCurrentFile() {
  if (_testGen && _testGen->isRunning()) return "TEST TONE";
  return _audioCurrentFile;
}

void audioBootTest() {
  Serial.println("[Boot] Test tone (A4, ~2s)...");
  audioTestTone();
  unsigned long start = millis();
  while (audioIsPlaying() && millis() - start < 5000) {
    audioUpdate();
    delay(5);
  }
  Serial.print("[Boot] Test tone complete (");
  Serial.print(millis() - start);
  Serial.println("ms)");

  if (!_audioSdReady) {
    Serial.println("[Boot] SD not ready — skipping file playback");
    return;
  }

  char filename[33] = {0};
  File root = SD.open("/");
  if (!root) { Serial.println("[Boot] Failed to open SD root"); return; }
  while (true) {
    File entry = root.openNextFile();
    if (!entry) { Serial.println("[Boot] No files found on SD"); break; }
    if (!entry.isDirectory()) {
      strncpy(filename, entry.name(), 32);
      entry.close();
      root.close();
      Serial.print("[Boot] Playing: "); Serial.println(filename);
      audioPlay(filename, 80);
      return;
    }
    entry.close();
  }
  root.close();
}

#else
  #error "AUDIO_BOARD must be AUDIO_BOARD_MUSIC_MAKER or AUDIO_BOARD_BFF"
#endif

// =====================================================================
//  SD helpers — board-agnostic
// =====================================================================

bool audioSdIsReady() { return _audioSdReady; }

bool audioSdInit() {
#if AUDIO_BOARD == AUDIO_BOARD_MUSIC_MAKER
  _audioSdReady = SD.begin(MM_SDCS_PIN);
#else
  _audioSdReady = SD.begin(BFF_SDCS_PIN);
#endif
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
