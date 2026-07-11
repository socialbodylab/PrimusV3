/*
 * ftp.h — PrimusV3 FTP Server Wrapper
 * =====================================================
 * Wraps SimpleFTPServer by Renzo Mischianti (xreef):
 *   Library Manager name: "SimpleFTPServer"
 *   https://github.com/xreef/SimpleFTPServer
 *
 * Storage is set to STORAGE_SD before including the library so it
 * uses SD.h (same filesystem used by the audio subsystem).
 *
 * SD bus mutex: audioStop() is called before FTP starts so the
 * SD card is always accessed by one subsystem at a time.
 *
 * API used:
 *   FtpServer::begin(user, pass)  — start server
 *   FtpServer::handleFTP()        — call every loop() iteration
 * Stop is handled by ceasing handleFTP() calls and re-running begin()
 * on the next start; the TCP socket is lightweight when idle.
 */

#ifndef FTP_H
#define FTP_H

#include "config.h"
#include <SD.h>

bool audioIsPlaying();

// SimpleFTPServer storage type is set via compiler flags in upload.sh
// (-DDEFAULT_FTP_SERVER_NETWORK_TYPE_ESP32=6 -DDEFAULT_STORAGE_TYPE_ESP32=5)
// so that the values reach library compilation, not just the sketch.
#include <SimpleFTPServer.h>

// =====================================================================
//  Shared resources from the .ino
// =====================================================================
extern bool sdBusy;

// =====================================================================
//  State
// =====================================================================
static FtpServer _ftpServer;
static bool _ftpRunning = false;

// Set when any FTP upload activity touches /cues.json; the main loop
// reloads the cue map once the transfer has gone quiet, so pushed cue
// maps take effect without a reboot.
//
// Trigger on upload START/progress, not completion: the library only
// fires the completion callback when the transfer took >0 ms, and a
// few-hundred-byte cues.json routinely lands in 0 ms over local WiFi —
// the completion event silently never comes. The quiet period keeps us
// from reloading a half-written file.
bool cuesReloadPending = false;
static unsigned long _cuesUploadActivityMs = 0;
#define CUES_RELOAD_QUIET_MS 1000

static void _ftpTransferCallback(FtpTransferOperation op, const char* name, uint32_t transferredSize) {
  if (name == NULL) return;
  if (op != FTP_UPLOAD_START && op != FTP_UPLOAD && op != FTP_UPLOAD_STOP) return;
  const char* base = strrchr(name, '/');
  base = base ? base + 1 : name;
  if (strcasecmp(base, "cues.json") == 0) {
    if (!cuesReloadPending)
      Serial.println("[FTP] cues.json upload detected — reload scheduled");
    cuesReloadPending = true;
    _cuesUploadActivityMs = millis();
  }
}

// True once a pending cues.json upload has gone quiet long enough that
// the file is safely complete on the SD card.
bool ftpCuesReloadDue() {
  return cuesReloadPending &&
         (millis() - _cuesUploadActivityMs) >= CUES_RELOAD_QUIET_MS;
}

// =====================================================================
//  API
// =====================================================================

void ftpInit() {
  // Begin the TCP server once here — it stays bound for the life of the sketch.
  // ftpStart/ftpStop only toggle _ftpRunning; they never re-call begin().
  _ftpServer.setTransferCallback(_ftpTransferCallback);
  _ftpServer.begin(FTP_USER, FTP_PASSWORD);
  Serial.println("[FTP] FTP subsystem ready (SimpleFTPServer/SD)");
}

void ftpStart() {
  if (_ftpRunning) return;
  _ftpRunning = true;
  Serial.print("[FTP] Server started — user: ");
  Serial.print(FTP_USER);
  Serial.print("  pass: ");
  Serial.println(FTP_PASSWORD);
}

void ftpStop() {
  if (!_ftpRunning) return;
  _ftpRunning = false;
  Serial.println("[FTP] Server stopped");
}

void ftpUpdate() {
  if (_ftpRunning && !sdBusy) {
    _ftpServer.handleFTP();
  }
}

bool ftpIsRunning() {
  return _ftpRunning;
}

#endif // FTP_H
