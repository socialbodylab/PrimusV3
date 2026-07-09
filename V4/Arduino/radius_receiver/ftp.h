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

// Set when an FTP upload of /cues.json completes; the main loop reloads
// the cue map when the SD bus is free, so pushed cue maps take effect
// without a reboot.
bool cuesReloadPending = false;

static void _ftpTransferCallback(FtpTransferOperation op, const char* name, uint32_t transferredSize) {
  if (op != FTP_UPLOAD_STOP || name == NULL) return;
  const char* base = strrchr(name, '/');
  base = base ? base + 1 : name;
  if (strcasecmp(base, "cues.json") == 0) {
    cuesReloadPending = true;
    Serial.println("[FTP] cues.json uploaded — reload scheduled");
  }
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
