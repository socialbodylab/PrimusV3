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

char   _audioCurrentFile[33] = {0};
uint8_t _audioVolume = 80;
bool   _audioLooping = false;
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
  if (TRACK_TELEMETRY_ENABLED) {
    const char* name = (state == TRACK_STATE_STOPPED) ? "" : _audioCurrentFile;
    sendTrackTelemetry(state, name);
  }
}

static void _applyVolume(uint8_t volume) {
  if (volume == _lastAppliedVolume) return;
  _lastAppliedVolume = volume;
  _audioVolume = volume;
  uint8_t vs1053vol = (uint8_t)((100 - volume) * 254 / 100);
  _musicMaker.setVolume(vs1053vol, vs1053vol);
}

void audioInit() {
  Serial.println("[Audio] Music Maker FeatherWing (VS1053)");

  if (!_musicMaker.begin()) {
    Serial.println("[Audio] ERROR: VS1053 begin() failed");
    return;
  }

  if (!SD.begin(MM_SDCS_PIN)) {
    Serial.println("[Audio] ERROR: SD card init failed");
    return;
  }
  Serial.println("[Audio] SD + VS1053 OK");

  _applyVolume(80);
  _musicMaker.useInterrupt(VS1053_FILEPLAYER_PIN_INT);
}

bool audioPlay(const char* filename, uint8_t volume, uint16_t duration = 0) {
  if (sdBusy && _musicMaker.playingMusic) {
    _musicMaker.stopPlaying();
  }
  if (_musicMaker.playingMusic) _musicMaker.stopPlaying();

  strncpy(_audioCurrentFile, filename, 32);
  _audioCurrentFile[32] = '\0';
  _audioLooping = false;
  _audioDuration = duration;
  _audioStartMillis = millis();
  sdBusy = true;
  _applyVolume(volume);

  bool ok = _musicMaker.startPlayingFile(filename);
  if (!ok) {
    Serial.print("[Audio] ERROR: could not open ");
    Serial.println(filename);
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
  _audioLooping = true;
  audioPlay(filename, volume, duration);
}

void audioUpdate() {
  if (_audioDuration > 0 && _audioCurrentFile[0] != '\0') {
    if ((millis() - _audioStartMillis) >= (uint32_t)_audioDuration * 1000UL) {
      audioStop();
      return;
    }
  }

  if (!_musicMaker.playingMusic) {
    if (_audioLooping && _audioCurrentFile[0] != '\0') {
      if (_musicMaker.startPlayingFile(_audioCurrentFile)) {
        _notifyTrack(TRACK_STATE_PLAYING);
      }
    } else if (_audioCurrentFile[0] != '\0') {
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
