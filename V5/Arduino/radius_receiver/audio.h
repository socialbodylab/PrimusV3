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
uint8_t  _audioVolume           = 80;
bool     _audioLooping          = false;
bool     _audioSdReady          = false;
bool     _audioHwReady          = false;
uint8_t  _audioPlaybackState    = TRACK_STATE_STOPPED;
uint8_t  _lastAppliedVolume     = 255;
uint16_t _audioDuration         = 0;
uint32_t _audioStartMillis      = 0;
// pausePlaying(true) clears the library's playingMusic flag, which makes a
// paused track indistinguishable from a finished one inside audioUpdate().
// Track paused explicitly so loop-restart / natural-end cleanup never fire
// on a track that is merely paused.
bool     _audioPaused           = false;

Adafruit_VS1053_FilePlayer _musicMaker(
  MM_CS_PIN, MM_DCS_PIN, MM_DREQ_PIN, MM_SDCS_PIN);

bool audioIsPlaying() {
  return _musicMaker.playingMusic || _audioPaused;
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

static void _cancelPlayback() {
  // Aborting a WAV mid-stream leaves the decoder holding stale stream
  // state (stopPlaying only sets SM_CANCEL and walks away) — the next
  // track then decodes at the wrong rate and plays audibly slow. A soft
  // reset clears the decoder; ~100 ms, and only ever runs on an explicit
  // track switch or stop, never in the streaming path. Natural track end
  // consumes the stream fully and needs none of this.
  _musicMaker.stopPlaying();
  delay(5);
  _musicMaker.softReset();
  _musicMaker.setVolume(254, 254);  // reset leaves the volume register loud
  _lastAppliedVolume = 255;         // force reapply on the next play
}

void audioInit() {
  Serial.println("[Audio] Music Maker FeatherWing (VS1053)");

  if (!_musicMaker.begin()) {
    Serial.println("[Audio] ERROR: VS1053 begin() failed");
    return;
  }

  _musicMaker.setVolume(254, 254);
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
  if (!_audioSdReady) {
    Serial.println("[Audio] ERROR: SD not ready");
    return false;
  }

  char trackPath[66];
  snprintf(trackPath, sizeof(trackPath), "%s%s", filename[0] == '/' ? "" : "/", filename);

  {
    File f = SD.open(trackPath);
    if (!f) {
      Serial.print("[Audio] ERROR: file not found: ");
      Serial.println(trackPath);
      return false;
    }
    uint8_t magic[12] = {0};
    f.read(magic, 12);
    f.close();
    if (memcmp(magic, "RIFF", 4) != 0 || memcmp(magic + 8, "WAVE", 4) != 0) {
      Serial.print("[Audio] ERROR: not a WAV file: ");
      Serial.println(trackPath);
      return false;
    }
  }

  if (_musicMaker.playingMusic || _audioPaused) {
    _cancelPlayback();
  }
  _audioPaused = false;

  strncpy(_audioCurrentFile, filename, 64);
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
  if (_musicMaker.playingMusic || _audioPaused) _cancelPlayback();
  _audioPaused = false;
  _musicMaker.setVolume(254, 254);
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
  if (!_musicMaker.playingMusic) return;  // nothing playing (or already paused)
  _musicMaker.pausePlaying(true);
  _audioPaused = true;
  _musicMaker.setVolume(254, 254);
  // The hardware is now muted behind _applyVolume's back — invalidate its
  // cache or the next play at an unchanged volume skips the volume write
  // and plays silently.
  _lastAppliedVolume = 255;
  _notifyTrack(TRACK_STATE_PAUSED);
  Serial.println("[Audio] Paused");
}

void audioSetVolume(uint8_t volume) {
  _applyVolume(volume);
}

void audioTestTone() {
  if (!_audioHwReady) return;
  if (_musicMaker.playingMusic) _musicMaker.stopPlaying();
  _audioPaused = false;
  _audioCurrentFile[0] = '\0';
  _audioLooping = false;
  _audioDuration = 0;
  _audioStartMillis = 0;
  sdBusy = false;
  Serial.println("[Audio] Test tone: 1kHz, 500ms");
  _musicMaker.sineTest(0x44, 500);
  // Do NOT call setVolume() here. sineTest() calls reset() internally which
  // can leave DREQ low briefly; sciWrite() does not check DREQ, so any SCI
  // write immediately after sineTest() may be dropped and corrupt VS1053 state.
  // But reset() DID change the hardware volume — invalidate _applyVolume's
  // cache so the next play re-applies the requested volume.
  _lastAppliedVolume = 255;
  Serial.println("[Audio] Test tone complete");
}

void audioLoop(const char* filename, uint8_t volume, uint16_t duration = 0) {
  audioPlay(filename, volume, duration);
  _audioLooping = true;
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
  } else if (_audioPaused) {
    // Paused: the codec holds position and the library's playingMusic flag
    // is false. This is NOT a track end — without this branch a paused
    // looping track restarts itself and a paused one-shot gets cleaned up.
  } else {
    if (_audioLooping && _audioCurrentFile[0] != '\0') {
      char trackPath[66];
      snprintf(trackPath, sizeof(trackPath), "%s%s",
               _audioCurrentFile[0] == '/' ? "" : "/", _audioCurrentFile);
      if (_musicMaker.startPlayingFile(trackPath)) {
        _notifyTrack(TRACK_STATE_PLAYING);
      }
    } else if (_audioCurrentFile[0] != '\0') {
      _musicMaker.setVolume(254, 254);
      // Natural track end mutes the codec directly (hiss-kill) —
      // invalidate _applyVolume's cache so the next play re-applies the
      // real volume instead of matching the cached value and staying muted.
      _lastAppliedVolume = 255;
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

uint16_t sdFileCount() {
  if (!_audioSdReady) return 0;
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
