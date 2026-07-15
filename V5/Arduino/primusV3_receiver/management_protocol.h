/*
 * management_protocol.h — Primus management wire primitives and NVS schema
 */

#ifndef MANAGEMENT_PROTOCOL_H
#define MANAGEMENT_PROTOCOL_H

#include "config.h"
#include <Preferences.h>

enum ManagementOperation : uint8_t {
  MGMT_GET_CONFIG = 0x01,
  MGMT_SET_OUTPUT_DESCRIPTORS = 0x10,
  MGMT_SET_TELEMETRY_TARGET = 0x11,
  MGMT_SET_OPERATING_MODE = 0x12,
  MGMT_SET_RECEIVE_CONFIG = 0x13,
  MGMT_SET_IP_CONFIG = 0x14,
  MGMT_SET_IDENTITY = 0x15,
  MGMT_BOOT_WINDOW_UNLOCK = 0x16,
};

enum ManagementReplyStatus : uint8_t {
  MGMT_ACK = 0,
  MGMT_NACK = 1,
};

enum ManagementError : uint8_t {
  MGMT_ERROR_NONE = 0,
  MGMT_ERROR_MALFORMED_PACKET = 1,
  MGMT_ERROR_UNSUPPORTED_VERSION = 2,
  MGMT_ERROR_UNSUPPORTED_OPERATION = 3,
  MGMT_ERROR_INVALID_PAYLOAD = 4,
  MGMT_ERROR_LOCKED = 5,
  MGMT_ERROR_OUT_OF_RANGE = 6,
  MGMT_ERROR_NOT_AVAILABLE = 7,
  MGMT_ERROR_INTERNAL = 8,
};

enum OperatingMode : uint8_t {
  OPERATING_MODE_PROTOTYPE = 0,
  OPERATING_MODE_PRODUCTION = 1,
};

enum UnifiedStatusFlags : uint16_t {
  STATUS_WIFI_CONNECTED = 1 << 0,
  STATUS_STATIC_IP = 1 << 1,
  STATUS_OUTPUT_POWER = 1 << 2,
  STATUS_TEST_ACTIVE = 1 << 3,
  STATUS_TELEMETRY_CONFIGURED = 1 << 4,
  STATUS_PRODUCTION = 1 << 5,
  STATUS_UNLOCK_WINDOW_OPEN = 1 << 6,
  STATUS_BATTERY_VALID = 1 << 7,
};

struct ManagementReplayKey {
  uint8_t remoteIp[4];
  uint16_t requestId;
  uint8_t operation;
  uint8_t protocolVersion;
  uint16_t declaredPayloadLen;
  uint16_t actualPayloadLen;
  uint8_t payload[MANAGEMENT_REQUEST_PAYLOAD_MAX_LEN];
  uint8_t requestStatus;
  uint8_t requestError;
};

struct ManagementReplyCacheEntry {
  bool valid;
  unsigned long storedAtMs;
  ManagementReplayKey key;
  uint16_t replyLen;
  uint8_t reply[MANAGEMENT_REPLY_PACKET_MAX_LEN];
};

struct ManagementReplyCache {
  ManagementReplyCacheEntry entries[MANAGEMENT_REPLY_CACHE_SIZE];
  uint8_t nextSlot;
};

struct ManagementRequestContext {
  IPAddress remoteAddr;
  uint16_t requestId;
  uint8_t operation;
  uint8_t protocolVersion;
  uint16_t declaredPayloadLen;
  uint16_t actualPayloadLen;
  uint8_t requestStatus;
  uint8_t requestError;
  const uint8_t* payload;
};

inline uint16_t readBe16(const uint8_t* data) {
  return ((uint16_t)data[0] << 8) | data[1];
}

inline uint32_t readBe32(const uint8_t* data) {
  return ((uint32_t)data[0] << 24) | ((uint32_t)data[1] << 16) |
         ((uint32_t)data[2] << 8) | data[3];
}

inline void writeBe16(uint8_t* data, uint16_t value) {
  data[0] = (value >> 8) & 0xFF;
  data[1] = value & 0xFF;
}

inline void writeBe32(uint8_t* data, uint32_t value) {
  data[0] = (value >> 24) & 0xFF;
  data[1] = (value >> 16) & 0xFF;
  data[2] = (value >> 8) & 0xFF;
  data[3] = value & 0xFF;
}

inline void buildManagementReplayKey(ManagementReplayKey& key,
                                     const IPAddress& remoteAddr,
                                     uint16_t requestId,
                                     uint8_t operation,
                                     uint8_t protocolVersion,
                                     uint16_t declaredPayloadLen,
                                     uint16_t actualPayloadLen,
                                     const uint8_t* payload,
                                     uint8_t requestStatus,
                                     uint8_t requestError) {
  key.remoteIp[0] = remoteAddr[0];
  key.remoteIp[1] = remoteAddr[1];
  key.remoteIp[2] = remoteAddr[2];
  key.remoteIp[3] = remoteAddr[3];
  key.requestId = requestId;
  key.operation = operation;
  key.protocolVersion = protocolVersion;
  key.declaredPayloadLen = declaredPayloadLen;
  key.actualPayloadLen = actualPayloadLen;
  memset(key.payload, 0, sizeof(key.payload));
  if (actualPayloadLen > 0) {
    memcpy(key.payload, payload, actualPayloadLen);
  }
  key.requestStatus = requestStatus;
  key.requestError = requestError;
}

inline bool managementReplayKeysEqual(const ManagementReplayKey& a,
                                      const ManagementReplayKey& b) {
  return memcmp(a.remoteIp, b.remoteIp, sizeof(a.remoteIp)) == 0 &&
         a.requestId == b.requestId &&
         a.operation == b.operation &&
         a.protocolVersion == b.protocolVersion &&
         a.declaredPayloadLen == b.declaredPayloadLen &&
         a.actualPayloadLen == b.actualPayloadLen &&
         memcmp(a.payload, b.payload, a.actualPayloadLen) == 0 &&
         a.requestStatus == b.requestStatus &&
         a.requestError == b.requestError;
}

inline bool isManagementReplyCacheEntryFresh(
  const ManagementReplyCacheEntry& entry, unsigned long now) {
  return entry.valid &&
         (uint32_t)(now - entry.storedAtMs) <= MANAGEMENT_REPLY_CACHE_TTL_MS;
}

inline bool shouldCacheManagementReply(ManagementReplyStatus status,
                                       ManagementError error) {
  return status == MGMT_ACK ||
         (status == MGMT_NACK && error != MGMT_ERROR_INTERNAL);
}

inline ManagementReplyCacheEntry* findManagementReplyCacheEntry(
  ManagementReplyCache& cache, const ManagementReplayKey& key,
  unsigned long now) {
  for (uint8_t i = 0; i < MANAGEMENT_REPLY_CACHE_SIZE; i++) {
    ManagementReplyCacheEntry& entry = cache.entries[i];
    if (!entry.valid) continue;
    if (!isManagementReplyCacheEntryFresh(entry, now)) {
      entry.valid = false;
      continue;
    }
    if (managementReplayKeysEqual(entry.key, key)) {
      return &entry;
    }
  }
  return nullptr;
}

inline ManagementReplyCacheEntry* reserveManagementReplyCacheEntry(
  ManagementReplyCache& cache, unsigned long now) {
  for (uint8_t i = 0; i < MANAGEMENT_REPLY_CACHE_SIZE; i++) {
    ManagementReplyCacheEntry& entry = cache.entries[i];
    if (!entry.valid || !isManagementReplyCacheEntryFresh(entry, now)) {
      entry.valid = false;
      return &entry;
    }
  }
  ManagementReplyCacheEntry* entry =
    &cache.entries[cache.nextSlot % MANAGEMENT_REPLY_CACHE_SIZE];
  cache.nextSlot = (cache.nextSlot + 1) % MANAGEMENT_REPLY_CACHE_SIZE;
  entry->valid = false;
  return entry;
}

inline void encodeOutputDescriptor(const OutputConfig& cfg, uint8_t* data) {
  data[0] = cfg.enabled ? 1 : 0;
  data[1] = (uint8_t)cfg.layout;
  writeBe16(data + 2, cfg.pixelCount);
  data[4] = cfg.gridRows;
  data[5] = cfg.gridCols;
  data[6] = (uint8_t)cfg.traversalAxis;
  data[7] = (uint8_t)cfg.scanPattern;
  data[8] = (uint8_t)cfg.startCorner;
  data[9] = 0;
  writeBe16(data + 10, cfg.virtualPixelCount);
}

inline bool decodeOutputDescriptor(const uint8_t* data, OutputConfig& cfg) {
  if (data[0] > 1 || data[1] > LAYOUT_GRID || data[6] > TRAVERSAL_COLUMN_MAJOR ||
      data[7] > SCAN_SERPENTINE || data[8] > START_BOTTOM_RIGHT || data[9] != 0) {
    return false;
  }

  OutputConfig candidate = cfg;
  candidate.enabled = data[0] == 1;
  candidate.layout = (LayoutType)data[1];
  candidate.pixelCount = readBe16(data + 2);
  candidate.gridRows = data[4];
  candidate.gridCols = data[5];
  candidate.traversalAxis = (TraversalAxis)data[6];
  candidate.scanPattern = (ScanPattern)data[7];
  candidate.startCorner = (StartCorner)data[8];
  candidate.virtualPixelCount = readBe16(data + 10);
  candidate.bytesPerPixel = candidate.enabled ? 3 : 0;
  if (!validateOutputDescriptor(candidate)) return false;
  candidate.type = inferOutputType(candidate);
  cfg = candidate;
  return true;
}

inline bool saveOutputDescriptors(Preferences& prefs,
                                  const OutputConfig outputs[NUM_OUTPUTS]) {
  uint8_t blob[OUTPUT_DESCRIPTOR_BLOB_LEN] = {};
  blob[0] = OUTPUT_DESCRIPTOR_SCHEMA;
  blob[1] = NUM_OUTPUTS;
  for (uint8_t i = 0; i < NUM_OUTPUTS; i++) {
    encodeOutputDescriptor(
      outputs[i], blob + 2 + i * OUTPUT_DESCRIPTOR_WIRE_LEN);
  }
  uint16_t crc = persistenceCrc16(blob, OUTPUT_DESCRIPTOR_BLOB_LEN - 2);
  writeBe16(blob + OUTPUT_DESCRIPTOR_BLOB_LEN - 2, crc);
  if (prefs.putBytes("outDescAll", blob, sizeof(blob)) != sizeof(blob)) {
    return false;
  }

  // Keep legacy mirrors for downgrade compatibility. The single blob above is
  // authoritative, so interruption during these writes cannot create hybrids.
  for (uint8_t i = 0; i < NUM_OUTPUTS; i++) {
    String typeKey = "otype" + String(i);
    String virtualKey = "vpx" + String(i);
    prefs.putUChar(typeKey.c_str(), (uint8_t)outputs[i].type);
    prefs.putUShort(virtualKey.c_str(), outputs[i].virtualPixelCount);
  }
  return true;
}

inline bool loadAtomicOutputDescriptors(Preferences& prefs,
                                        OutputConfig outputs[NUM_OUTPUTS]) {
  if (prefs.getBytesLength("outDescAll") != OUTPUT_DESCRIPTOR_BLOB_LEN) return false;
  uint8_t blob[OUTPUT_DESCRIPTOR_BLOB_LEN];
  if (prefs.getBytes("outDescAll", blob, sizeof(blob)) != sizeof(blob)) return false;
  if (blob[0] != OUTPUT_DESCRIPTOR_SCHEMA || blob[1] != NUM_OUTPUTS) return false;
  uint16_t expectedCrc = readBe16(blob + OUTPUT_DESCRIPTOR_BLOB_LEN - 2);
  if (persistenceCrc16(blob, OUTPUT_DESCRIPTOR_BLOB_LEN - 2) != expectedCrc) {
    return false;
  }

  OutputConfig candidates[NUM_OUTPUTS] = {outputs[0], outputs[1]};
  for (uint8_t i = 0; i < NUM_OUTPUTS; i++) {
    if (!decodeOutputDescriptor(
          blob + 2 + i * OUTPUT_DESCRIPTOR_WIRE_LEN, candidates[i])) {
      return false;
    }
  }
  for (uint8_t i = 0; i < NUM_OUTPUTS; i++) outputs[i] = candidates[i];
  return true;
}

inline bool migratePerSlotOutputDescriptors(Preferences& prefs,
                                            OutputConfig outputs[NUM_OUTPUTS]) {
  if (prefs.getUChar("outSchema", 0) != OUTPUT_DESCRIPTOR_SCHEMA) return false;

  OutputConfig candidates[NUM_OUTPUTS] = {outputs[0], outputs[1]};
  uint8_t wire[OUTPUT_DESCRIPTOR_WIRE_LEN];
  for (uint8_t i = 0; i < NUM_OUTPUTS; i++) {
    String key = "outDesc" + String(i);
    if (prefs.getBytesLength(key.c_str()) != sizeof(wire)) return false;
    if (prefs.getBytes(key.c_str(), wire, sizeof(wire)) != sizeof(wire)) return false;
    if (!decodeOutputDescriptor(wire, candidates[i])) return false;
  }
  for (uint8_t i = 0; i < NUM_OUTPUTS; i++) outputs[i] = candidates[i];
  if (!saveOutputDescriptors(prefs, outputs)) return false;
  prefs.remove("outSchema");
  prefs.remove("outDesc0");
  prefs.remove("outDesc1");
  return true;
}

inline void migrateLegacyOutputDescriptors(Preferences& prefs,
                                           OutputConfig outputs[NUM_OUTPUTS]) {
  for (uint8_t i = 0; i < NUM_OUTPUTS; i++) {
    String typeKey = "otype" + String(i);
    if (prefs.isKey(typeKey.c_str())) {
      uint8_t storedType = prefs.getUChar(typeKey.c_str(), outputs[i].type);
      if (storedType < NUM_OUTPUT_TYPES &&
          profileSupportsOutputType((OutputType)storedType)) {
        outputs[i].type = (OutputType)storedType;
        deriveFromType(outputs[i]);
      }
    }
    String virtualKey = "vpx" + String(i);
    if (prefs.isKey(virtualKey.c_str())) {
      uint16_t storedVirtual =
        prefs.getUShort(virtualKey.c_str(), outputs[i].virtualPixelCount);
      applyVirtualPixelCount(outputs[i], storedVirtual);
    }
  }
  saveOutputDescriptors(prefs, outputs);
}

inline void loadStoredOutputDescriptors(Preferences& prefs,
                                        OutputConfig outputs[NUM_OUTPUTS]) {
  if (loadAtomicOutputDescriptors(prefs, outputs)) return;
  if (prefs.isKey("outDescAll")) {
    // A present but invalid authoritative blob is never reconstructed from
    // separately written compatibility mirrors.
    saveOutputDescriptors(prefs, outputs);
    return;
  }
  if (migratePerSlotOutputDescriptors(prefs, outputs)) return;
  migrateLegacyOutputDescriptors(prefs, outputs);
}

#endif // MANAGEMENT_PROTOCOL_H
