/*
 * receive_mode.h — Art-Net receive mode (universe layout)
 * =========================================================
 * Modular dispatch for how a node expects ArtDmx data.
 *
 * Modes:
 *   RECEIVE_MODE_SPLIT    — one universe per active output (legacy default)
 *   RECEIVE_MODE_COMBINED — single universe, ports laid out contiguously
 *
 * To add a future mode: extend ReceiveMode, validateReceiveMode(),
 * applyReceiveMode(), handleArtDmxForReceiveMode(), and the capability token.
 */

#ifndef RECEIVE_MODE_H
#define RECEIVE_MODE_H

#include "config.h"
#include <Preferences.h>

// =====================================================================
//  Receive mode enum
// =====================================================================

enum ReceiveMode : uint8_t {
  RECEIVE_MODE_SPLIT    = 0,
  RECEIVE_MODE_COMBINED = 1,
};

#ifndef DEFAULT_RECEIVE_MODE
  #define DEFAULT_RECEIVE_MODE RECEIVE_MODE_COMBINED
#endif

#ifndef DEFAULT_UNIVERSE_BASE
  #define DEFAULT_UNIVERSE_BASE 0
#endif

#ifdef PRIMUS_DEFAULT_RECEIVE_MODE
  #undef DEFAULT_RECEIVE_MODE
  #define DEFAULT_RECEIVE_MODE PRIMUS_DEFAULT_RECEIVE_MODE
#endif

#ifdef PRIMUS_DEFAULT_UNIVERSE_BASE
  #undef DEFAULT_UNIVERSE_BASE
  #define DEFAULT_UNIVERSE_BASE PRIMUS_DEFAULT_UNIVERSE_BASE
#endif

#define RECEIVE_MODE_COMBINED_MAX_PIXELS 170

// Runtime state
ReceiveMode currentReceiveMode = DEFAULT_RECEIVE_MODE;
uint16_t    currentUniverseBase = DEFAULT_UNIVERSE_BASE;
uint8_t     expectedUniverseCount = 1;
char        receiveOverrideBuildId[OVERRIDE_BUILD_ID_MAX_LEN + 1] = {0};

inline const char* receiveModeLabel(ReceiveMode mode) {
  switch (mode) {
    case RECEIVE_MODE_COMBINED: return "Combined";
    default:                    return "Split";
  }
}

inline bool isValidReceiveMode(uint8_t mode) {
  return mode <= RECEIVE_MODE_COMBINED;
}

inline bool validateUniverseBase(ReceiveMode mode, uint16_t base) {
  return base <= (mode == RECEIVE_MODE_SPLIT ? 32766 : 32767);
}

inline uint16_t totalActivePixels(const OutputConfig outputs[NUM_OUTPUTS]) {
  uint16_t total = 0;
  for (uint8_t i = 0; i < NUM_OUTPUTS; i++) {
    if (!outputs[i].enabled) continue;
    total += outputs[i].virtualPixelCount;
  }
  return total;
}

inline bool validateReceiveMode(ReceiveMode mode, const OutputConfig outputs[NUM_OUTPUTS]) {
  if (mode == RECEIVE_MODE_COMBINED) {
    return totalActivePixels(outputs) <= RECEIVE_MODE_COMBINED_MAX_PIXELS;
  }
  return true;
}

inline void applyReceiveMode(OutputConfig outputs[NUM_OUTPUTS],
                             ReceiveMode mode, uint16_t base) {
  currentReceiveMode = mode;
  currentUniverseBase = base;

  for (uint8_t i = 0; i < NUM_OUTPUTS; i++) {
    if (!outputs[i].enabled) {
      outputs[i].universe = base + i;
      continue;
    }
    if (mode == RECEIVE_MODE_COMBINED) {
      outputs[i].universe = base;
    } else {
      outputs[i].universe = base + i;
    }
  }

  expectedUniverseCount = (mode == RECEIVE_MODE_COMBINED) ? 1 : countActiveOutputs(outputs);
}

inline bool saveReceiveModeRecord(Preferences& prefs, ReceiveMode mode,
                                  uint16_t base, const char* overrideBuildId) {
  if (!isValidReceiveMode((uint8_t)mode) || !validateUniverseBase(mode, base)) {
    return false;
  }
  uint8_t overrideLen =
    (uint8_t)strnlen(overrideBuildId, OVERRIDE_BUILD_ID_MAX_LEN + 1);
  if (overrideLen > OVERRIDE_BUILD_ID_MAX_LEN) return false;
  uint8_t blob[RECEIVE_CONFIG_BLOB_LEN] = {};
  blob[0] = RECEIVE_CONFIG_SCHEMA;
  blob[1] = (uint8_t)mode;
  blob[2] = (uint8_t)(base >> 8);
  blob[3] = (uint8_t)(base & 0xFF);
  blob[4] = overrideLen;
  memcpy(blob + 5, overrideBuildId, overrideLen);
  uint16_t crc = persistenceCrc16(blob, RECEIVE_CONFIG_BLOB_LEN - 2);
  blob[RECEIVE_CONFIG_BLOB_LEN - 2] = (uint8_t)(crc >> 8);
  blob[RECEIVE_CONFIG_BLOB_LEN - 1] = (uint8_t)(crc & 0xFF);
  if (prefs.putBytes("recvCfg", blob, sizeof(blob)) != sizeof(blob)) return false;

  strncpy(receiveOverrideBuildId, overrideBuildId, OVERRIDE_BUILD_ID_MAX_LEN);
  receiveOverrideBuildId[OVERRIDE_BUILD_ID_MAX_LEN] = '\0';
  // Compatibility mirrors are non-authoritative and only follow the commit.
  prefs.putUChar("recvMode", (uint8_t)mode);
  prefs.putUShort("univBase", base);
  return true;
}

inline bool saveReceiveMode(Preferences& prefs, ReceiveMode mode, uint16_t base) {
  return saveReceiveModeRecord(
    prefs, mode, base, receiveOverrideBuildId);
}

inline bool decodeReceiveConfig(const uint8_t blob[RECEIVE_CONFIG_BLOB_LEN],
                                ReceiveMode& mode, uint16_t& base,
                                char overrideBuildId[OVERRIDE_BUILD_ID_MAX_LEN + 1]) {
  if (blob[0] != RECEIVE_CONFIG_SCHEMA || !isValidReceiveMode(blob[1]) ||
      blob[4] > OVERRIDE_BUILD_ID_MAX_LEN) {
    return false;
  }
  uint16_t expected =
    ((uint16_t)blob[RECEIVE_CONFIG_BLOB_LEN - 2] << 8) |
    blob[RECEIVE_CONFIG_BLOB_LEN - 1];
  if (persistenceCrc16(blob, RECEIVE_CONFIG_BLOB_LEN - 2) != expected) {
    return false;
  }
  ReceiveMode candidateMode = (ReceiveMode)blob[1];
  uint16_t candidateBase = ((uint16_t)blob[2] << 8) | blob[3];
  if (!validateUniverseBase(candidateMode, candidateBase)) return false;
  mode = candidateMode;
  base = candidateBase;
  memcpy(overrideBuildId, blob + 5, blob[4]);
  overrideBuildId[blob[4]] = '\0';
  return true;
}

inline void loadStoredReceiveMode(Preferences& prefs, OutputConfig outputs[NUM_OUTPUTS]) {
  ReceiveMode mode = DEFAULT_RECEIVE_MODE;
  uint16_t base = DEFAULT_UNIVERSE_BASE;
  bool needsCommit = false;
  if (prefs.isKey("recvCfg")) {
    uint8_t blob[RECEIVE_CONFIG_BLOB_LEN];
    if (prefs.getBytesLength("recvCfg") != sizeof(blob) ||
        prefs.getBytes("recvCfg", blob, sizeof(blob)) != sizeof(blob) ||
        !decodeReceiveConfig(blob, mode, base, receiveOverrideBuildId)) {
      // Never rebuild a corrupt authoritative record from compatibility mirrors.
      mode = DEFAULT_RECEIVE_MODE;
      base = DEFAULT_UNIVERSE_BASE;
      needsCommit = true;
    }
  } else {
    if (prefs.isKey("recvMode")) {
      uint8_t stored = prefs.getUChar("recvMode", DEFAULT_RECEIVE_MODE);
      if (isValidReceiveMode(stored)) mode = (ReceiveMode)stored;
    }
    if (prefs.isKey("univBase")) {
      base = (uint16_t)prefs.getUShort("univBase", DEFAULT_UNIVERSE_BASE);
    }
    if (!validateUniverseBase(mode, base)) {
      base = mode == RECEIVE_MODE_SPLIT ? 32766 : 32767;
    }
    needsCommit = true;
  }

  ReceiveMode durableMode = mode;
  uint16_t durableBase = base;
  bool overridePending = false;
  const char* commitOverrideBuildId = receiveOverrideBuildId;
#if defined(PRIMUSV3_OVERRIDE_BUILD_ID) && \
    (defined(PRIMUS_DEFAULT_RECEIVE_MODE) || defined(PRIMUS_DEFAULT_UNIVERSE_BASE))
  overridePending =
    strcmp(receiveOverrideBuildId, PRIMUSV3_OVERRIDE_BUILD_ID) != 0;
  if (overridePending) {
  #ifdef PRIMUS_DEFAULT_RECEIVE_MODE
    mode = PRIMUS_DEFAULT_RECEIVE_MODE;
  #endif
  #ifdef PRIMUS_DEFAULT_UNIVERSE_BASE
    base = PRIMUS_DEFAULT_UNIVERSE_BASE;
  #endif
    if (!validateUniverseBase(mode, base)) {
      base = mode == RECEIVE_MODE_SPLIT ? 32766 : 32767;
    }
    needsCommit = true;
    commitOverrideBuildId = PRIMUSV3_OVERRIDE_BUILD_ID;
  }
#endif

  if (overridePending && !validateReceiveMode(mode, outputs)) {
    mode = durableMode;
    base = durableBase;
    overridePending = false;
    commitOverrideBuildId = receiveOverrideBuildId;
  }
  bool committed = !needsCommit ||
    saveReceiveModeRecord(prefs, mode, base, commitOverrideBuildId);
  if (!committed && overridePending) {
    mode = durableMode;
    base = durableBase;
  }
  applyReceiveMode(outputs, mode, base);
}

inline int buildReceiveModeCapabilityToken(char* buf, int bufSize, int pos) {
  if (pos >= bufSize - 1) return pos;
  const char* tag = (currentReceiveMode == RECEIVE_MODE_COMBINED) ? "C" : "S";
  // snprintf returns the length it *would* have written even when the
  // actual write got truncated to fit — clamp so callers never compute a
  // negative/underflowed "remaining space" from this on the next append.
  int written = pos + snprintf(buf + pos, bufSize - pos, "|U:%s:%u", tag, currentUniverseBase);
  return written > bufSize ? bufSize : written;
}

inline void clearOutputBuffers(uint8_t outputBuffers[NUM_OUTPUTS][MAX_BUFFER_SIZE],
                               bool outputDataReady[NUM_OUTPUTS]) {
  for (uint8_t i = 0; i < NUM_OUTPUTS; i++) {
    memset(outputBuffers[i], 0, MAX_BUFFER_SIZE);
    outputDataReady[i] = false;
  }
}

struct FrameAssemblyState {
  uint8_t  sequence;
  uint8_t  univCount;
  unsigned long firstArrival;
  bool     ready;
};

inline void markFrameProgress(FrameAssemblyState& frame, uint8_t seq,
                              unsigned long now, uint8_t requiredUnivCount) {
  if (seq != frame.sequence || frame.ready) {
    frame.sequence = seq;
    frame.univCount = 1;
    frame.firstArrival = now;
    frame.ready = false;
  } else {
    frame.univCount++;
  }
  if (frame.univCount >= requiredUnivCount) {
    frame.ready = true;
  }
}

inline void copyOutputSlice(uint8_t* dest, uint16_t destLen,
                            const uint8_t* src, uint16_t srcLen) {
  uint16_t toCopy = (srcLen < destLen) ? srcLen : destLen;
  if (toCopy > 0) memcpy(dest, src, toCopy);
  if (toCopy < destLen) {
    memset(dest + toCopy, 0, destLen - toCopy);
  }
}

inline void handleArtDmxSplit(OutputConfig outputs[NUM_OUTPUTS],
                              uint8_t outputBuffers[NUM_OUTPUTS][MAX_BUFFER_SIZE],
                              bool outputDataReady[NUM_OUTPUTS],
                              bool outputActive[NUM_OUTPUTS],
                              unsigned long outputLastPacket[NUM_OUTPUTS],
                              FrameAssemblyState& frame,
                              uint16_t universe, uint8_t seq,
                              const uint8_t* pixelData, uint16_t dataLen,
                              unsigned long now) {
  for (uint8_t o = 0; o < NUM_OUTPUTS; o++) {
    if (!outputs[o].enabled) continue;
    if (outputs[o].universe != universe) continue;

    uint16_t needed = outputs[o].virtualPixelCount * outputs[o].bytesPerPixel;
    if (needed > MAX_BUFFER_SIZE) needed = MAX_BUFFER_SIZE;
    copyOutputSlice(outputBuffers[o], needed, pixelData, dataLen);
    outputDataReady[o] = true;
    outputActive[o] = true;
    outputLastPacket[o] = now;
    markFrameProgress(frame, seq, now, expectedUniverseCount);
    break;
  }
}

inline void handleArtDmxCombined(OutputConfig outputs[NUM_OUTPUTS],
                                 uint8_t outputBuffers[NUM_OUTPUTS][MAX_BUFFER_SIZE],
                                 bool outputDataReady[NUM_OUTPUTS],
                                 bool outputActive[NUM_OUTPUTS],
                                 unsigned long outputLastPacket[NUM_OUTPUTS],
                                 FrameAssemblyState& frame,
                                 uint16_t universe, uint8_t seq,
                                 const uint8_t* pixelData, uint16_t dataLen,
                                 unsigned long now) {
  if (universe != currentUniverseBase) return;

  uint16_t offset = 0;
  bool anyReady = false;
  for (uint8_t o = 0; o < NUM_OUTPUTS; o++) {
    if (!outputs[o].enabled) continue;

    uint16_t needed = outputs[o].virtualPixelCount * outputs[o].bytesPerPixel;
    if (needed > MAX_BUFFER_SIZE) needed = MAX_BUFFER_SIZE;
    if (offset >= dataLen) {
      memset(outputBuffers[o], 0, needed);
    } else {
      uint16_t available = dataLen - offset;
      copyOutputSlice(outputBuffers[o], needed, pixelData + offset, available);
    }
    offset += needed;
    outputDataReady[o] = true;
    outputActive[o] = true;
    outputLastPacket[o] = now;
    anyReady = true;
  }

  if (anyReady) {
    markFrameProgress(frame, seq, now, expectedUniverseCount);
  }
}

inline void handleArtDmxForReceiveMode(OutputConfig outputs[NUM_OUTPUTS],
                                       uint8_t outputBuffers[NUM_OUTPUTS][MAX_BUFFER_SIZE],
                                       bool outputDataReady[NUM_OUTPUTS],
                                       bool outputActive[NUM_OUTPUTS],
                                       unsigned long outputLastPacket[NUM_OUTPUTS],
                                       FrameAssemblyState& frame,
                                       uint16_t universe, uint8_t seq,
                                       const uint8_t* pixelData, uint16_t dataLen,
                                       unsigned long now) {
  if (currentReceiveMode == RECEIVE_MODE_COMBINED) {
    handleArtDmxCombined(outputs, outputBuffers, outputDataReady, outputActive,
                         outputLastPacket, frame, universe, seq,
                         pixelData, dataLen, now);
  } else {
    handleArtDmxSplit(outputs, outputBuffers, outputDataReady, outputActive,
                      outputLastPacket, frame, universe, seq,
                      pixelData, dataLen, now);
  }
}

inline bool setReceiveMode(Preferences& prefs,
                           OutputConfig outputs[NUM_OUTPUTS],
                           uint8_t outputBuffers[NUM_OUTPUTS][MAX_BUFFER_SIZE],
                           bool outputDataReady[NUM_OUTPUTS],
                           ReceiveMode mode, uint16_t base) {
  if (!isValidReceiveMode((uint8_t)mode)) return false;
  if (!validateUniverseBase(mode, base)) return false;
  if (!validateReceiveMode(mode, outputs)) return false;

  if (!saveReceiveMode(prefs, mode, base)) return false;
  applyReceiveMode(outputs, mode, base);
  clearOutputBuffers(outputBuffers, outputDataReady);
  return true;
}

inline bool handleArtReceiveConfig(Preferences& prefs,
                                   OutputConfig outputs[NUM_OUTPUTS],
                                   uint8_t outputBuffers[NUM_OUTPUTS][MAX_BUFFER_SIZE],
                                   bool outputDataReady[NUM_OUTPUTS],
                                   uint8_t* data, uint16_t len) {
  // [header 8][opcode 2][version 2][mode 1][base universe 2 LE]
  if (len < 15) return false;

  uint8_t modeVal = data[12];
  uint16_t base = (uint16_t)data[13] | ((uint16_t)data[14] << 8);
  if (!isValidReceiveMode(modeVal)) return false;

  ReceiveMode mode = (ReceiveMode)modeVal;
  if (!validateReceiveMode(mode, outputs)) return false;

  if (!setReceiveMode(prefs, outputs, outputBuffers, outputDataReady, mode, base)) {
    return false;
  }

  Serial.print("ArtReceiveConfig: ");
  Serial.print(receiveModeLabel(mode));
  Serial.print(" base universe ");
  Serial.println(base);
  return true;
}

#endif // RECEIVE_MODE_H
