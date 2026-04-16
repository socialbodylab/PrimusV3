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
static char   _audioCurrentFile[33] = {0};
static uint8_t _audioVolume = 80;
static bool   _audioLooping = false;

// =====================================================================
//  Music Maker FeatherWing (VS1053B) — SPI hardware codec
// =====================================================================
#if AUDIO_BOARD == AUDIO_BOARD_MUSIC_MAKER

#include <Adafruit_VS1053.h>

static Adafruit_VS1053_FilePlayer _musicMaker(
  MM_CS_PIN, MM_DCS_PIN, MM_DREQ_PIN, MM_SDCS_PIN);

void audioInit() {
  Serial.println("[Audio] Music Maker FeatherWing (VS1053)");

  // VS1053 begin() initialises both the codec and the onboard SD card
  if (!_musicMaker.begin()) {
    Serial.println("[Audio] ERROR: VS1053 begin() failed");
    displayError("VS1053 Fail", "Music Maker not detected");
    return;
  }

  if (!SD.begin(MM_SDCS_PIN)) {
    Serial.println("[Audio] ERROR: SD card init failed (Music Maker)");
    displayError("SD Fail", "SD card not found (MM)");
    return;
  }
  Serial.println("[Audio] SD OK");

  _musicMaker.setVolume(20, 20);  // VS1053: lower = louder; 20 ≈ 80% volume
  _musicMaker.useInterrupt(VS1053_FILEPLAYER_PIN_INT);
  Serial.println("[Audio] VS1053 OK");
}

bool audioPlay(const char* filename, uint8_t volume) {
  if (sdBusy) {
    Serial.println("[Audio] SD busy (FTP running) — play ignored");
    return false;
  }
  if (_musicMaker.playingMusic) _musicMaker.stopPlaying();

  strncpy(_audioCurrentFile, filename, 32);
  _audioCurrentFile[32] = '\0';
  _audioVolume  = volume;
  _audioLooping = false;
  sdBusy = true;

  // VS1053 volume: 0=max, 254=silent. Map 0-100 → 100-0 (scale to 0-100 range)
  uint8_t vs1053vol = (uint8_t)((100 - volume) * 100 / 100);
  _musicMaker.setVolume(vs1053vol, vs1053vol);

  bool ok = _musicMaker.startPlayingFile(filename);
  if (!ok) {
    Serial.print("[Audio] ERROR: could not open ");
    Serial.println(filename);
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
  _audioCurrentFile[0] = '\0';
  _audioLooping = false;
  sdBusy = false;
  Serial.println("[Audio] Stopped");
}

void audioPause() {
  _musicMaker.pausePlaying(true);
  Serial.println("[Audio] Paused");
}

void audioLoop(const char* filename, uint8_t volume) {
  _audioLooping = true;
  audioPlay(filename, volume);
}

void audioUpdate() {
  if (!_musicMaker.playingMusic) {
    if (_audioLooping && _audioCurrentFile[0] != '\0') {
      // Restart the file for loop playback
      _musicMaker.startPlayingFile(_audioCurrentFile);
    } else if (_audioCurrentFile[0] != '\0') {
      // Playback finished naturally
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
#include <AudioGeneratorWAV.h>
#include <AudioOutputI2S.h>

static AudioFileSourceSD* _audioSource = nullptr;
static AudioGeneratorWAV* _audioGen    = nullptr;
static AudioOutputI2S*    _audioOut    = nullptr;

void audioInit() {
  Serial.println("[Audio] Audio BFF (MAX98357 I2S)");

  if (!SD.begin(BFF_SDCS_PIN)) {
    Serial.println("[Audio] ERROR: SD card init failed (BFF)");
    displayError("SD Fail", "SD card not found (BFF)");
    return;
  }
  Serial.println("[Audio] SD OK");

  _audioOut = new AudioOutputI2S();
  _audioOut->SetPinout(BFF_BCK_PIN, BFF_WS_PIN, BFF_DATA_PIN);
  _audioOut->SetGain(0.5f);   // 50% gain default
  Serial.println("[Audio] I2S output configured");
}

bool audioPlay(const char* filename, uint8_t volume) {
  if (sdBusy) {
    Serial.println("[Audio] SD busy (FTP running) — play ignored");
    return false;
  }

  // Stop any existing playback
  if (_audioGen && _audioGen->isRunning()) {
    _audioGen->stop();
  }
  delete _audioGen;    _audioGen    = nullptr;
  delete _audioSource; _audioSource = nullptr;

  strncpy(_audioCurrentFile, filename, 32);
  _audioCurrentFile[32] = '\0';
  _audioVolume  = volume;
  _audioLooping = false;
  sdBusy = true;

  _audioOut->SetGain(volume / 100.0f);

  _audioSource = new AudioFileSourceSD(filename);
  if (!_audioSource->isOpen()) {
    Serial.print("[Audio] ERROR: could not open ");
    Serial.println(filename);
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
  if (_audioGen && _audioGen->isRunning()) _audioGen->stop();
  delete _audioGen;    _audioGen    = nullptr;
  delete _audioSource; _audioSource = nullptr;
  _audioCurrentFile[0] = '\0';
  _audioLooping = false;
  sdBusy = false;
  Serial.println("[Audio] Stopped");
}

void audioPause() {
  // ESP8266Audio does not have a native pause — stop is the closest
  if (_audioGen && _audioGen->isRunning()) _audioGen->stop();
  Serial.println("[Audio] Paused (stopped)");
}

void audioLoop(const char* filename, uint8_t volume) {
  _audioLooping = true;
  audioPlay(filename, volume);
}

void audioUpdate() {
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
  return _audioGen && _audioGen->isRunning();
}

const char* audioCurrentFile() {
  return _audioCurrentFile;
}

#else
  #error "AUDIO_BOARD must be AUDIO_BOARD_MUSIC_MAKER or AUDIO_BOARD_BFF"
#endif

// =====================================================================
//  SD file count helper (used by FTP status screen)
// =====================================================================
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
