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

inline const char* receiveModeLabel(ReceiveMode mode) {
  switch (mode) {
    case RECEIVE_MODE_COMBINED: return "Combined";
    default:                    return "Split";
  }
}

inline bool isValidReceiveMode(uint8_t mode) {
  return mode <= RECEIVE_MODE_COMBINED;
}

inline uint16_t totalActivePixels(const OutputConfig outputs[NUM_OUTPUTS]) {
  uint16_t total = 0;
  for (uint8_t i = 0; i < NUM_OUTPUTS; i++) {
    if (outputs[i].type == OUTPUT_OFF) continue;
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

  uint8_t activeIdx = 0;
  for (uint8_t i = 0; i < NUM_OUTPUTS; i++) {
    if (outputs[i].type == OUTPUT_OFF) continue;
    if (mode == RECEIVE_MODE_COMBINED) {
      outputs[i].universe = base;
    } else {
      outputs[i].universe = base + activeIdx;
      activeIdx++;
    }
  }

  expectedUniverseCount = (mode == RECEIVE_MODE_COMBINED) ? 1 : countActiveOutputs(outputs);
}

inline void loadStoredReceiveMode(Preferences& prefs, OutputConfig outputs[NUM_OUTPUTS]) {
  ReceiveMode mode = DEFAULT_RECEIVE_MODE;
  uint16_t base = DEFAULT_UNIVERSE_BASE;

  if (prefs.isKey("recvMode")) {
    uint8_t stored = prefs.getUChar("recvMode", DEFAULT_RECEIVE_MODE);
    if (isValidReceiveMode(stored)) {
      mode = (ReceiveMode)stored;
    }
  }
  if (prefs.isKey("univBase")) {
    base = (uint16_t)prefs.getUShort("univBase", DEFAULT_UNIVERSE_BASE);
  }

  applyReceiveMode(outputs, mode, base);
}

inline void saveReceiveMode(Preferences& prefs) {
  prefs.putUChar("recvMode", (uint8_t)currentReceiveMode);
  prefs.putUShort("univBase", currentUniverseBase);
}

inline int buildReceiveModeCapabilityToken(char* buf, int bufSize, int pos) {
  if (pos >= bufSize - 1) return pos;
  const char* tag = (currentReceiveMode == RECEIVE_MODE_COMBINED) ? "C" : "S";
  return pos + snprintf(buf + pos, bufSize - pos, "|U:%s:%u", tag, currentUniverseBase);
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
    if (outputs[o].type == OUTPUT_OFF) continue;
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
    if (outputs[o].type == OUTPUT_OFF) continue;

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
  if (!validateReceiveMode(mode, outputs)) return false;

  applyReceiveMode(outputs, mode, base);
  saveReceiveMode(prefs);
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
