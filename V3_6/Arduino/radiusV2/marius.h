/*
 * marius.h — Marius BLE Performance Controller (Phase 2: JSON loader + audio dispatch)
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
 * Network actions (osc, artnet_audio, artnet_dmx) are added in Phase 3.
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
#include <NimBLEDevice.h>

// ── NUS UUIDs ─────────────────────────────────────────────────────────
#define NUS_SERVICE_UUID "6E400001-B5A3-F393-E0A9-E50E24DCCA9E"
#define NUS_TX_UUID      "6E400003-B5A3-F393-E0A9-E50E24DCCA9E"

// ── Action types ───────────────────────────────────────────────────────
#define MARIUS_ACTION_NONE        0
#define MARIUS_ACTION_AUDIO_PLAY  1
#define MARIUS_ACTION_AUDIO_STOP  2
// Phase 3: MARIUS_ACTION_OSC, MARIUS_ACTION_ARTNET_AUDIO, MARIUS_ACTION_ARTNET_DMX

#define MARIUS_ACTIONS_MAX  8
#define MARIUS_VOLUME_UNSET 255   // use device's current _audioVolume

struct MariusAction {
    uint8_t type;        // MARIUS_ACTION_*
    char    file[33];    // audio_play: WAV filename on SD
    uint8_t volume;      // audio_play: 0–100 or MARIUS_VOLUME_UNSET
    bool    loop;        // audio_play: true → audioLoop(), false → audioPlay()
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
                // Use device current volume if none specified in marius.json
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
        }
    }
}

// =====================================================================
//  Action array parser (used by mariusLoad)
// =====================================================================

static void _mariusParseActionArray(JsonArray arr, MariusAction* actions, uint8_t* count) {
    *count = 0;
    for (JsonObject obj : arr) {
        if (*count >= MARIUS_ACTIONS_MAX) break;
        const char* typeStr = obj["type"] | "";
        MariusAction& a = actions[*count];
        a.file[0] = '\0';
        a.volume  = MARIUS_VOLUME_UNSET;
        a.loop    = false;

        if (strcmp(typeStr, "audio_play") == 0) {
            a.type = MARIUS_ACTION_AUDIO_PLAY;
            const char* fn = obj["file"] | "";
            strncpy(a.file, fn, 32);
            a.file[32] = '\0';
            if (a.file[0] == '\0') {
                Serial.println("[Marius] audio_play action missing file — skipped");
                continue;
            }
            if (obj["volume"].is<int>()) {
                int v = obj["volume"].as<int>();
                a.volume = (v >= 0 && v <= 100) ? (uint8_t)v : MARIUS_VOLUME_UNSET;
            }
            a.loop = obj["loop"] | false;
            Serial.printf("[Marius]   audio_%s \"%s\" vol=%s\n",
                a.loop ? "loop" : "play", a.file,
                a.volume == MARIUS_VOLUME_UNSET ? "dev" : String(a.volume).c_str());
            (*count)++;
        } else if (strcmp(typeStr, "audio_stop") == 0) {
            a.type = MARIUS_ACTION_AUDIO_STOP;
            Serial.println("[Marius]   audio_stop");
            (*count)++;
        } else {
            // Phase 3: osc, artnet_audio, artnet_dmx
            Serial.printf("[Marius]   skipping Phase 3+ action: %s\n", typeStr);
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
