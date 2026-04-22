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

// Tell SimpleFTPServer to use SD on ESP32.
// FtpServerKey.h only sets DEFAULT_STORAGE_TYPE_ESP32 inside
// #ifndef DEFAULT_FTP_SERVER_NETWORK_TYPE_ESP32 — so we must pre-define
// the network type too, otherwise the library redefines storage to FFAT.
#define DEFAULT_FTP_SERVER_NETWORK_TYPE_ESP32 NETWORK_ESP32
#define DEFAULT_STORAGE_TYPE_ESP32 STORAGE_SD
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

// =====================================================================
//  API
// =====================================================================

void ftpInit(fs::FS& fsRef) {
  // SD must already be initialised by audioInit() before FTP can start
  Serial.println("[FTP] FTP subsystem ready (SimpleFTPServer/SD)");
}

void ftpStart() {
  if (_ftpRunning) return;

  if (sdBusy) {
    Serial.println("[FTP] SD busy (audio playing) — FTP start refused");
    return;
  }

  _ftpServer.begin(FTP_USER, FTP_PASSWORD);
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
  if (_ftpRunning) {
    _ftpServer.handleFTP();
  }
}

bool ftpIsRunning() {
  return _ftpRunning;
}

#endif // FTP_H
