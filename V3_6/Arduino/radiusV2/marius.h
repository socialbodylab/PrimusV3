/*
 * marius.h — Marius BLE Performance Controller (Phase 3: network actions)
 * ====================================================================
 * When /marius.json is present on SD, the Radius becomes a Marius
 * receiver. A Puck.js v2 worn by a performer sends BLE UART lines over
 * the Nordic UART Service (NUS):
 *
 *   "btn/press"     — button pressed
 *   "btn/release"   — button released
 *   "accel x y z"  — accelerometer at 12.5 Hz while held (Phase 5)
 *
 * Phase 2 loads action arrays from marius.json and dispatches
 * audio_play / audio_stop actions on press and release.
 * Phase 3 adds osc, artnet_audio, and artnet_dmx network actions.
 *
 * BLE UUIDs (NUS):
 *   Service:       6E400001-B5A3-F393-E0A9-E50E24DCCA9E
 *   TX char (RX by central, notify): 6E400003-B5A3-F393-E0A9-E50E24DCCA9E
 *
 * NOTE: NimBLEClient::connect() blocks for up to the connection timeout
 * (~5 s default). loop() is stalled during this window. Acceptable for
 * Phase 1; move to a FreeRTOS task if audio continuity matters during
 * reconnect.
 */

#ifndef MARIUS_H
#define MARIUS_H

#include "config.h"
#include <ArduinoJson.h>
#include <SD.h>
#include <WiFiUdp.h>
#include <NimBLEDevice.h>

// Globals declared later in radiusV2.ino — visible here because marius.h
// is compiled in the same translation unit, but we need forward externs
// for the send helpers that reference them before their definition point.
extern IPAddress senderIP;
extern bool      senderKnown;
extern bool      wifiConnected;
extern WiFiUDP   udpReport;

// ── NUS UUIDs ─────────────────────────────────────────────────────────
#define NUS_SERVICE_UUID "6E400001-B5A3-F393-E0A9-E50E24DCCA9E"
#define NUS_TX_UUID      "6E400003-B5A3-F393-E0A9-E50E24DCCA9E"

// ── Action types ───────────────────────────────────────────────────────
#define MARIUS_ACTION_NONE          0
#define MARIUS_ACTION_AUDIO_PLAY    1
#define MARIUS_ACTION_AUDIO_STOP    2
#define MARIUS_ACTION_OSC           3
#define MARIUS_ACTION_ARTNET_AUDIO  4
#define MARIUS_ACTION_ARTNET_DMX    5

#define MARIUS_ACTIONS_MAX  8
#define MARIUS_VOLUME_UNSET 255   // use device's current _audioVolume

struct MariusAction {
    uint8_t  type;           // MARIUS_ACTION_*

    // audio_play / artnet_audio: filename + volume
    char     file[33];       // WAV filename on SD
    uint8_t  volume;         // 0–100 or MARIUS_VOLUME_UNSET
    bool     loop;           // audio_play: true → audioLoop()

    // network actions: target routing (all three network types)
    char     target_ip[16];  // "" = use senderIP as default
    uint16_t target_port;    // osc only; 0 = OSC_PORT

    // osc
    char     osc_addr[64];   // e.g. "/cue/1", "/stop"

    // artnet_audio
    uint8_t  artnet_cmd;     // 0-7 (same as ArtAudioCmd cmd byte)

    // artnet_dmx
    uint16_t dmx_universe;   // 0-based Art-Net universe
    uint16_t dmx_channel;    // 1–512
    uint8_t  dmx_value;      // 0–255
};

#define MARIUS_EVENT_PRESS   0
#define MARIUS_EVENT_RELEASE 1

// ── Internal state ─────────────────────────────────────────────────────
enum MariusState { MARIUS_IDLE, MARIUS_SCANNING, MARIUS_CONNECTING, MARIUS_CONNECTED };

static char        _mariusPuckName[33]    = {0};
static bool        _mariusConfigured      = false;
static bool        _mariusActive          = false;
static MariusState _mariusState           = MARIUS_IDLE;
static char        _mariusLastEvent[16]   = {0};  // "PRESS" / "RELEASE" / ""

// Found device — written by scan callback (BLE task), read by mariusUpdate() (main task).
// NimBLEAddress is a 7-byte struct; copied in callback, read after volatile flag is set.
static NimBLEAddress     _mariusFoundAddress;
static volatile bool     _mariusFoundDevice = false;

// Pending event — written by notify callback (BLE task), read by mariusUpdate() (main task).
static char              _mariusEventLine[64]    = {0};
static volatile bool     _mariusEventPending     = false;

// Incoming byte buffer for assembling newline-delimited lines
static char     _mariusLineBuf[128] = {0};
static uint8_t  _mariusLineBufLen   = 0;

static NimBLEClient* _mariusClient = nullptr;

// ── Phase 2: action arrays ─────────────────────────────────────────────
static MariusAction _mariusPressActions[MARIUS_ACTIONS_MAX];
static uint8_t      _mariusPressCount   = 0;
static MariusAction _mariusReleaseActions[MARIUS_ACTIONS_MAX];
static uint8_t      _mariusReleaseCount = 0;

// mtime-based reload: check every 5 s; skip if SD is busy with audio
static uint32_t _mariusJsonMtime   = 0;
static uint32_t _mariusMtimeLastMs = 0;

// =====================================================================
//  Notify callback — runs in BLE task
// =====================================================================

static void _mariusOnNotify(NimBLERemoteCharacteristic*, uint8_t* data, size_t len, bool) {
    for (size_t i = 0; i < len; i++) {
        char c = (char)data[i];
        if (c == '\n' || c == '\r') {
            if (_mariusLineBufLen > 0) {
                _mariusLineBuf[_mariusLineBufLen] = '\0';
                strncpy(_mariusEventLine, _mariusLineBuf, sizeof(_mariusEventLine) - 1);
                _mariusEventLine[sizeof(_mariusEventLine) - 1] = '\0';
                _mariusEventPending = true;
                _mariusLineBufLen   = 0;
            }
        } else if (_mariusLineBufLen < sizeof(_mariusLineBuf) - 1) {
            _mariusLineBuf[_mariusLineBufLen++] = c;
        }
    }
}

// =====================================================================
//  Client callbacks
// =====================================================================

class _MariusClientCB : public NimBLEClientCallbacks {
    void onConnect(NimBLEClient*) override {
        Serial.printf("[Marius] Connected — %s\n", _mariusPuckName);
    }
    void onDisconnect(NimBLEClient*, int reason) override {
        Serial.printf("[Marius] Disconnected (reason %d) — restarting scan\n", reason);
        _mariusState = MARIUS_SCANNING;
        NimBLEDevice::getScan()->start(0);
    }
};
static _MariusClientCB _mariusClientCB;

// =====================================================================
//  Scan callbacks
// =====================================================================

class _MariusScanCB : public NimBLEScanCallbacks {
    void onResult(const NimBLEAdvertisedDevice* device) override {
        if (_mariusFoundDevice) return;
        if (strcmp(device->getName().c_str(), _mariusPuckName) == 0) {
            Serial.printf("[Marius] Found: %s\n", device->getAddress().toString().c_str());
            _mariusFoundAddress = device->getAddress();
            _mariusFoundDevice  = true;
            NimBLEDevice::getScan()->stop();
        }
    }
};
static _MariusScanCB _mariusScanCB;

// =====================================================================
//  Connection helper
// =====================================================================

static bool _mariusConnect() {
    if (_mariusClient) {
        if (_mariusClient->isConnected()) _mariusClient->disconnect();
        NimBLEDevice::deleteClient(_mariusClient);
        _mariusClient = nullptr;
    }

    _mariusClient = NimBLEDevice::createClient();
    _mariusClient->setClientCallbacks(&_mariusClientCB, false);

    Serial.printf("[Marius] Connecting to %s...\n", _mariusFoundAddress.toString().c_str());
    if (!_mariusClient->connect(_mariusFoundAddress)) {
        Serial.println("[Marius] Connect failed");
        NimBLEDevice::deleteClient(_mariusClient);
        _mariusClient = nullptr;
        return false;
    }

    NimBLERemoteService* svc = _mariusClient->getService(NUS_SERVICE_UUID);
    if (!svc) {
        Serial.println("[Marius] NUS service not found");
        _mariusClient->disconnect();
        return false;
    }

    NimBLERemoteCharacteristic* txCh = svc->getCharacteristic(NUS_TX_UUID);
    if (!txCh || !txCh->canNotify()) {
        Serial.println("[Marius] TX characteristic missing or non-notifiable");
        _mariusClient->disconnect();
        return false;
    }

    if (!txCh->subscribe(true, _mariusOnNotify)) {
        Serial.println("[Marius] Subscribe failed");
        _mariusClient->disconnect();
        return false;
    }

    Serial.println("[Marius] Subscribed — ready to receive events");
    return true;
}

// =====================================================================
//  Network send helpers (Phase 3)
//  senderIP, senderKnown, wifiConnected, udpReport, ARTNET_PORT, OSC_PORT
//  are globals defined in radiusV2.ino; visible here in the same TU.
// =====================================================================

// Static Art-Net DMX packet buffer — up to 512 slots + 18-byte header.
static uint8_t _mariusDmxBuf[530];

// Art-Net header bytes, reused by both send helpers.
static const uint8_t _kArtMagic[8] = {'A','r','t','-','N','e','t','\0'};

// Resolve target: explicit IP string or sender fallback.
static IPAddress _mariusResolveTarget(const char* ipStr) {
    if (ipStr[0] != '\0') {
        IPAddress ip;
        if (ip.fromString(ipStr)) return ip;
    }
    return senderIP;
}

// Check that we have a destination before sending.
static bool _mariusHasDest(const char* ipStr) {
    return (ipStr[0] != '\0') || senderKnown;
}

// OSC 1.0 message with no arguments.
static void _mariusSendOsc(const MariusAction& a) {
    if (!wifiConnected || !_mariusHasDest(a.target_ip)) return;
    if (a.osc_addr[0] == '\0') return;

    IPAddress dest = _mariusResolveTarget(a.target_ip);
    uint16_t  port = (a.target_port != 0) ? a.target_port : OSC_PORT;

    // Address string padded to 4-byte boundary (includes null terminator).
    uint8_t addrLen    = (uint8_t)strlen(a.osc_addr);
    uint8_t addrPadded = (addrLen + 4) & ~3u;
    if (addrPadded > 96) return;  // safety guard

    uint8_t buf[104];
    memset(buf, 0, sizeof(buf));
    memcpy(buf, a.osc_addr, addrLen);
    // Type tag string ",\0\0\0" starts right after address block.
    buf[addrPadded] = ',';
    uint8_t pktLen = addrPadded + 4;  // type tag: ',' + 3 nulls already cleared

    udpReport.beginPacket(dest, port);
    udpReport.write(buf, pktLen);
    udpReport.endPacket();
    Serial.printf("[Marius] OSC -> %s:%d %s\n", dest.toString().c_str(), port, a.osc_addr);
}

// ArtAudioCmd (opcode 0x8300) to a Radius device or the sender.
static void _mariusSendArtAudio(const MariusAction& a) {
    if (!wifiConnected || !_mariusHasDest(a.target_ip)) return;

    IPAddress dest = _mariusResolveTarget(a.target_ip);

    uint8_t buf[48];
    memset(buf, 0, sizeof(buf));
    memcpy(buf, _kArtMagic, 8);
    buf[8]  = 0x00;  // opcode 0x8300 LE
    buf[9]  = 0x83;
    buf[10] = 0x00;
    buf[11] = 0x0E;  // protocol version 14
    buf[12] = a.artnet_cmd;
    buf[13] = (a.volume != MARIUS_VOLUME_UNSET) ? a.volume : 0;

    uint8_t pktLen = 15;
    if (a.artnet_cmd == 1 || a.artnet_cmd == 2) {
        uint8_t fnLen = (uint8_t)strlen(a.file);
        if (fnLen > 32) fnLen = 32;
        memcpy(buf + 14, a.file, fnLen);
        // buf[14+fnLen] is already '\0' from memset
        pktLen = 15 + fnLen;
    }

    udpReport.beginPacket(dest, ARTNET_PORT);
    udpReport.write(buf, pktLen);
    udpReport.endPacket();
    Serial.printf("[Marius] ArtAudio -> %s cmd=%d\n", dest.toString().c_str(), a.artnet_cmd);
}

// ArtDmx (opcode 0x5000) — sends enough slots to cover the target channel.
static void _mariusSendArtDmx(const MariusAction& a) {
    if (!wifiConnected || !_mariusHasDest(a.target_ip)) return;
    if (a.dmx_channel < 1 || a.dmx_channel > 512) return;

    IPAddress dest = _mariusResolveTarget(a.target_ip);

    // Slot count must be even and >= channel (1-indexed).
    uint16_t ch        = a.dmx_channel;
    uint16_t slotCount = (ch % 2 == 0) ? ch : ch + 1;

    memset(_mariusDmxBuf, 0, 18 + slotCount);
    memcpy(_mariusDmxBuf, _kArtMagic, 8);
    _mariusDmxBuf[8]  = 0x00;  // opcode 0x5000 LE
    _mariusDmxBuf[9]  = 0x50;
    _mariusDmxBuf[10] = 0x00;
    _mariusDmxBuf[11] = 0x0E;
    _mariusDmxBuf[12] = 0;     // sequence (disabled)
    _mariusDmxBuf[13] = 0;     // physical
    _mariusDmxBuf[14] = a.dmx_universe & 0xFF;
    _mariusDmxBuf[15] = (a.dmx_universe >> 8) & 0x0F;
    _mariusDmxBuf[16] = (slotCount >> 8) & 0xFF;  // length big-endian
    _mariusDmxBuf[17] = slotCount & 0xFF;
    _mariusDmxBuf[18 + ch - 1] = a.dmx_value;

    udpReport.beginPacket(dest, ARTNET_PORT);
    udpReport.write(_mariusDmxBuf, 18 + slotCount);
    udpReport.endPacket();
    Serial.printf("[Marius] ArtDmx -> %s u%d ch%d=%d\n",
                  dest.toString().c_str(), a.dmx_universe, ch, a.dmx_value);
}

// =====================================================================
//  Public API
// =====================================================================

bool        mariusIsConfigured() { return _mariusConfigured; }
bool        mariusIsActive()     { return _mariusActive; }
bool        mariusIsConnected()  { return _mariusClient && _mariusClient->isConnected(); }
const char* mariusPuckName()     { return _mariusPuckName; }
const char* mariusLastEvent()    { return _mariusLastEvent; }
MariusState mariusGetState()     { return _mariusState; }

void mariusRevert() {
    Serial.println("[Marius] Reverted to Radius for this session");
    _mariusActive = false;
    NimBLEDevice::getScan()->stop();
    if (_mariusClient && _mariusClient->isConnected()) _mariusClient->disconnect();
    _mariusState = MARIUS_IDLE;
}

// =====================================================================
//  mariusFireActions() — dispatch audio actions for an event
// =====================================================================

void mariusFireActions(uint8_t event) {
    MariusAction* actions = (event == MARIUS_EVENT_PRESS)
                            ? _mariusPressActions  : _mariusReleaseActions;
    uint8_t count         = (event == MARIUS_EVENT_PRESS)
                            ? _mariusPressCount    : _mariusReleaseCount;

    for (uint8_t i = 0; i < count; i++) {
        switch (actions[i].type) {
            case MARIUS_ACTION_AUDIO_PLAY: {
                uint8_t vol = (actions[i].volume != MARIUS_VOLUME_UNSET)
                              ? actions[i].volume : _audioVolume;
                if (actions[i].loop)
                    audioLoop(actions[i].file, vol, 0);
                else
                    audioPlay(actions[i].file, vol, 0);
                break;
            }
            case MARIUS_ACTION_AUDIO_STOP:
                audioStop();
                break;
            case MARIUS_ACTION_OSC:
                _mariusSendOsc(actions[i]);
                break;
            case MARIUS_ACTION_ARTNET_AUDIO:
                _mariusSendArtAudio(actions[i]);
                break;
            case MARIUS_ACTION_ARTNET_DMX:
                _mariusSendArtDmx(actions[i]);
                break;
        }
    }
}

// =====================================================================
//  Action array parser (used by mariusLoad)
// =====================================================================

// Parse volume field common to audio_play and artnet_audio.
static uint8_t _mariusParseVolume(JsonObject obj) {
    if (obj["volume"].is<int>()) {
        int v = obj["volume"].as<int>();
        return (v >= 0 && v <= 100) ? (uint8_t)v : MARIUS_VOLUME_UNSET;
    }
    return MARIUS_VOLUME_UNSET;
}

// Parse target_ip and target_port common to all network actions.
static void _mariusParseRouting(JsonObject obj, MariusAction& a) {
    const char* ip = obj["target_ip"] | "";
    strncpy(a.target_ip, ip, 15);
    a.target_ip[15] = '\0';
    a.target_port = obj["target_port"] | 0;
}

static void _mariusParseActionArray(JsonArray arr, MariusAction* actions, uint8_t* count) {
    *count = 0;
    for (JsonObject obj : arr) {
        if (*count >= MARIUS_ACTIONS_MAX) break;
        const char* typeStr = obj["type"] | "";
        MariusAction& a = actions[*count];
        // Zero all fields; individual parsers only fill what they need.
        memset(&a, 0, sizeof(MariusAction));
        a.volume = MARIUS_VOLUME_UNSET;

        if (strcmp(typeStr, "audio_play") == 0) {
            a.type = MARIUS_ACTION_AUDIO_PLAY;
            const char* fn = obj["file"] | "";
            strncpy(a.file, fn, 32);
            a.file[32] = '\0';
            if (a.file[0] == '\0') {
                Serial.println("[Marius]   audio_play missing file — skipped");
                continue;
            }
            a.volume = _mariusParseVolume(obj);
            a.loop   = obj["loop"] | false;
            Serial.printf("[Marius]   audio_%s \"%s\" vol=%s\n",
                a.loop ? "loop" : "play", a.file,
                a.volume == MARIUS_VOLUME_UNSET ? "dev" : String(a.volume).c_str());
            (*count)++;

        } else if (strcmp(typeStr, "audio_stop") == 0) {
            a.type = MARIUS_ACTION_AUDIO_STOP;
            Serial.println("[Marius]   audio_stop");
            (*count)++;

        } else if (strcmp(typeStr, "osc") == 0) {
            const char* addr = obj["address"] | "";
            if (addr[0] == '\0') {
                Serial.println("[Marius]   osc missing address — skipped");
                continue;
            }
            a.type = MARIUS_ACTION_OSC;
            strncpy(a.osc_addr, addr, 63);
            a.osc_addr[63] = '\0';
            _mariusParseRouting(obj, a);
            Serial.printf("[Marius]   osc %s -> %s:%d\n", a.osc_addr,
                a.target_ip[0] ? a.target_ip : "sender",
                a.target_port ? a.target_port : OSC_PORT);
            (*count)++;

        } else if (strcmp(typeStr, "artnet_audio") == 0) {
            a.type       = MARIUS_ACTION_ARTNET_AUDIO;
            a.artnet_cmd = obj["cmd"] | 0;
            if (a.artnet_cmd == 1 || a.artnet_cmd == 2) {
                const char* fn = obj["file"] | "";
                strncpy(a.file, fn, 32);
                a.file[32] = '\0';
                if (a.file[0] == '\0') {
                    Serial.println("[Marius]   artnet_audio play/loop missing file — skipped");
                    continue;
                }
            }
            a.volume = _mariusParseVolume(obj);
            _mariusParseRouting(obj, a);
            Serial.printf("[Marius]   artnet_audio cmd=%d -> %s\n", a.artnet_cmd,
                a.target_ip[0] ? a.target_ip : "sender");
            (*count)++;

        } else if (strcmp(typeStr, "artnet_dmx") == 0) {
            a.type         = MARIUS_ACTION_ARTNET_DMX;
            a.dmx_universe = obj["universe"] | 0;
            a.dmx_channel  = obj["channel"]  | 0;
            a.dmx_value    = obj["value"]    | 0;
            if (a.dmx_channel < 1 || a.dmx_channel > 512) {
                Serial.println("[Marius]   artnet_dmx invalid channel — skipped");
                continue;
            }
            _mariusParseRouting(obj, a);
            Serial.printf("[Marius]   artnet_dmx u%d ch%d=%d -> %s\n",
                a.dmx_universe, a.dmx_channel, a.dmx_value,
                a.target_ip[0] ? a.target_ip : "sender");
            (*count)++;

        } else {
            Serial.printf("[Marius]   unknown action type: %s — skipped\n", typeStr);
        }
    }
}

// =====================================================================
//  mariusLoad() — call after cuesLoad() in setup(), and on SD reload
// =====================================================================

void mariusLoad() {
    _mariusConfigured  = false;
    _mariusActive      = false;
    _mariusPuckName[0] = '\0';
    _mariusPressCount  = 0;
    _mariusReleaseCount = 0;

    File f = SD.open("/marius.json");
    if (!f) {
        Serial.println("[Marius] No /marius.json — Radius mode");
        return;
    }

    _mariusJsonMtime = (uint32_t)f.getLastWrite();

    JsonDocument doc;
    DeserializationError err = deserializeJson(doc, f);
    f.close();

    if (err) {
        Serial.printf("[Marius] JSON parse error: %s\n", err.c_str());
        return;
    }

    const char* name = doc["puck_name"] | "";
    if (name[0] == '\0') {
        Serial.println("[Marius] marius.json missing puck_name — ignored");
        return;
    }

    strncpy(_mariusPuckName, name, 32);
    _mariusPuckName[32] = '\0';

    Serial.printf("[Marius] Configured — puck: \"%s\"\n", _mariusPuckName);
    Serial.println("[Marius] press actions:");
    _mariusParseActionArray(doc["actions"]["press"].as<JsonArray>(),
                            _mariusPressActions, &_mariusPressCount);
    Serial.println("[Marius] release actions:");
    _mariusParseActionArray(doc["actions"]["release"].as<JsonArray>(),
                            _mariusReleaseActions, &_mariusReleaseCount);
    Serial.printf("[Marius] press:%d release:%d action(s) loaded\n",
                  _mariusPressCount, _mariusReleaseCount);

    _mariusConfigured = true;
    _mariusActive     = true;
}

// =====================================================================
//  mariusInit() — call if mariusIsConfigured(), after mariusLoad()
// =====================================================================

void mariusInit() {
    NimBLEDevice::init("");
    NimBLEScan* scan = NimBLEDevice::getScan();
    scan->setScanCallbacks(&_mariusScanCB, false);
    scan->setActiveScan(false);  // passive — Puck advertises its name in ADV packets
    scan->setInterval(100);
    scan->setWindow(99);
    _mariusState = MARIUS_SCANNING;
    scan->start(0);  // 0 = scan indefinitely
    Serial.println("[Marius] BLE scanning...");
}

// =====================================================================
//  mariusUpdate() — call from loop() after ftpUpdate()
// =====================================================================

void mariusUpdate() {
    if (!_mariusActive) return;

    // ── SD reload: check marius.json mtime every 5 s ──────────────────
    uint32_t now = millis();
    if (now - _mariusMtimeLastMs > 5000 && !sdBusy) {
        _mariusMtimeLastMs = now;
        File fChk = SD.open("/marius.json");
        if (fChk) {
            uint32_t mtime = (uint32_t)fChk.getLastWrite();
            fChk.close();
            if (mtime != _mariusJsonMtime) {
                Serial.println("[Marius] /marius.json updated — reloading");
                mariusLoad();
            }
        }
    }

    // ── Dispatch pending event (written by BLE task, read here) ──────
    if (_mariusEventPending) {
        _mariusEventPending = false;
        char line[64];
        strncpy(line, _mariusEventLine, sizeof(line) - 1);
        line[sizeof(line) - 1] = '\0';

        if (strcmp(line, "btn/press") == 0) {
            Serial.println("[Marius] PRESS");
            strncpy(_mariusLastEvent, "PRESS", sizeof(_mariusLastEvent) - 1);
            mariusFireActions(MARIUS_EVENT_PRESS);
        } else if (strcmp(line, "btn/release") == 0) {
            Serial.println("[Marius] RELEASE");
            strncpy(_mariusLastEvent, "RELEASE", sizeof(_mariusLastEvent) - 1);
            mariusFireActions(MARIUS_EVENT_RELEASE);
        } else if (strncmp(line, "accel ", 6) == 0) {
            // Phase 5: parse floats and dispatch accel actions
            Serial.printf("[Marius] accel: %s\n", line + 6);
        } else {
            Serial.printf("[Marius] unknown line: %s\n", line);
        }
    }

    // ── Display update on state or event change ───────────────────────
    {
        static uint8_t prevDisplayState = 255;
        static char    prevEvent[16]    = {0};
        uint8_t ds = _mariusActive ? (uint8_t)_mariusState : MARIUS_DISPLAY_REVERTED;
        if (ds != prevDisplayState || strcmp(_mariusLastEvent, prevEvent) != 0) {
            prevDisplayState = ds;
            strncpy(prevEvent, _mariusLastEvent, sizeof(prevEvent) - 1);
            displayMariusUpdate(ds, _mariusPuckName, _mariusLastEvent);
        }
    }

    // ── State machine ──────────────────────────────────────────────────
    switch (_mariusState) {

        case MARIUS_SCANNING:
            if (_mariusFoundDevice) {
                _mariusFoundDevice = false;
                _mariusState = MARIUS_CONNECTING;
            }
            break;

        case MARIUS_CONNECTING:
            if (_mariusConnect()) {
                _mariusState = MARIUS_CONNECTED;
            } else {
                // Connect failed — restart scan
                _mariusFoundDevice = false;
                _mariusState = MARIUS_SCANNING;
                NimBLEDevice::getScan()->start(0);
                Serial.println("[Marius] Retrying scan...");
            }
            break;

        case MARIUS_CONNECTED:
            break;  // NimBLE maintains connection; onDisconnect restarts scan

        case MARIUS_IDLE:
        default:
            break;
    }
}

#endif // MARIUS_H
