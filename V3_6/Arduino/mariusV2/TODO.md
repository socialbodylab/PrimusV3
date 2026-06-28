# Marius — TODO

Marius adds a BLE-controlled performance layer to a Radius device. A Puck.js v2 worn
by a performer sends button and accelerometer events over BLE UART; the Radius device
receives them, looks up a `marius.json` action map stored on its SD card, and fires the
configured actions (audio playback, OSC to sender, Art-Net audio to another Radius node,
or Art-Net DMX to an LED receiver).

---

## System Overview

```
[Puck.js v2]
  BTN press/release → BLE UART ("btn/press", "btn/release")
  Accel data        → BLE UART ("accel x y z") @ 12.5 Hz while held
        ↓  BLE (NUS)
[Radius device — ESP32-S3 or HUZZAH32]
  marius.h    — BLE central: scan → connect → subscribe to NUS notifications
  marius.json — action map on SD card
  action dispatch:
    • audio_play / audio_stop / audio_loop  → local VS1053 via audio.h
    • osc        → UDP OSC packet to sender
    • artnet_audio → ArtAudioCmd (0x8300) to another Radius device
    • artnet_dmx   → ArtDmx to an LED receiver
        ↓  WiFi / Art-Net / OSC
[Sender / other devices]
```

---

## Puck.js Firmware (`puckjsbutton.js`) — already done

- [x] `btn/press` on button down
- [x] `btn/release` on button up
- [x] `accel x y z` at 12.5 Hz while button held (LSM6DS3, ±2g, scale 8192 counts/g)

---

## `marius.json` Schema

File lives at `/marius.json` on the Radius SD card. Loaded at boot; reloaded when FTP
uploads a new version.

```json
{
  "puck_name": "Puck.js abc",
  "actions": {
    "press": [
      { "type": "audio_play", "file": "hit.wav", "volume": 80 }
    ],
    "release": [
      { "type": "audio_stop" }
    ],
    "accel": [
      { "type": "osc", "address": "/marius/accel" }
    ]
  }
}
```

`puck_name` — BLE advertised name to connect to (e.g. "Puck.js abc").  
`actions.press`, `actions.release`, `actions.accel` — each is an array of action objects
(multiple actions per event are allowed).

### Action types

| `type`         | Required fields                  | Optional fields                                        |
|----------------|----------------------------------|--------------------------------------------------------|
| `audio_play`   | `file`                           | `volume` (0–100), `loop` (bool)                        |
| `audio_stop`   | —                                | —                                                      |
| `osc`          | `address`                        | `args` (array), `target_ip`, `target_port`             |
| `artnet_audio` | `cmd` (0–7)                      | `target_ip`, `file`, `volume`                          |
| `artnet_dmx`   | `universe`, `channel` (1–512), `value` (0–255) | `target_ip`                            |

**Routing default — all network actions go to the sender.**
`target_ip` is optional on all network action types. When omitted, the firmware uses
`senderIP` (already known from incoming Art-Net discovery packets). This keeps the sender
as the central hub for routing, state tracking, and the Net Log.

Direct-to-device `target_ip` is available for low-latency cases (e.g. a Radius triggering
audio on another Radius in the same rack without involving the sender), but should be the
exception rather than the rule.

For `accel` actions the raw x/y/z float values are included as OSC float args or can be
mapped to volume in `audio_play` (`"volume_from": "accel_magnitude"`).

---

---

## Phase 1 — BLE scaffolding

Goal: Radius scans, connects to the Puck, and prints received lines to serial. No actions yet.

### `marius.h` — BLE client

- [x] Add `NimBLE-Arduino` to the library requirements in `upload.sh` check list
- [x] In `mariusInit()`: initialise NimBLE in client (central) role; set scan filter to
      match `puck_name` from `marius.json`
- [x] In `mariusUpdate()` (called from `loop()`): run scan → connect → subscribe state machine
  - SCANNING: passive scan, match device by name
  - CONNECTING: `NimBLEClient::connect()`
  - SUBSCRIBING: discover NUS service (`6E400001-B5A3-F393-E0A9-E50E24DCCA9E`) and TX
    characteristic (`6E400003-B5A3-F393-E0A9-E50E24DCCA9E`); register notification callback
  - CONNECTED: idle; reconnect automatically on disconnect
- [x] Notification callback: buffer incoming bytes; split on `\n`; dispatch complete lines
- [x] Line dispatch:
  - `"btn/press"` → `Serial.println("[Marius] PRESS")` + record last event
  - `"btn/release"` → `Serial.println("[Marius] RELEASE")` + record last event
  - `"accel x y z"` → parse three floats; log to serial only (actions deferred to Phase 5)
- [x] Track state: `mariusIsConnected()`, `mariusPuckName()`, `mariusIsActive()` (active = configured and not reverted)

### `radiusV2.ino` — Phase 1 integration

- [x] `#include "marius.h"`
- [x] In `setup()`: after `cuesLoad()`, call `mariusLoad()`; if `mariusIsConfigured()` call `mariusInit()`
- [x] In `loop()`: call `mariusUpdate()` after `ftpUpdate()`
- [x] Add Marius status to the periodic serial diagnostic line (connected device name or "scanning")
- [x] "Revert to Radius" flag: `mariusRevert()` sets `_mariusActive = false`, stops BLE scanning;
      `mariusIsActive()` returns false; Screen 5 D1 button calls this (wired in Phase 4)

---

## Phase 2 — JSON loader + audio actions

Goal: press/release fire audio on the local device.

### `marius.h` — JSON loader and audio dispatch

- [x] `mariusLoad()`: open `/marius.json` from SD with ArduinoJson
- [x] Parse `puck_name`, `actions.press[]`, `actions.release[]`
- [x] Store in flat C structs (`MariusAction`) — max 8 actions per event
- [x] `mariusIsConfigured()` — true if marius.json loaded successfully
- [x] Re-run `mariusLoad()` when FTP uploads a new `/marius.json` (mtime poll every 5 s, skips when sdBusy)
- [x] `mariusFireActions(event)` for `MARIUS_EVENT_PRESS` and `MARIUS_EVENT_RELEASE`:
  - `audio_play` → `audioPlay(file, volume, 0)` or `audioLoop(file, volume, 0)` if `"loop": true`
  - `audio_stop` → `audioStop()`
- [x] Volume: explicit `0–100` used; omitted → device current `_audioVolume`

---

## Phase 3 — Network actions

Goal: press/release can trigger OSC, remote audio, or LED DMX.

### `marius.h` — network dispatch

- [x] `osc` → binary OSC 1.0 packet (address-only, no args); UDP to `target_ip:target_port`
      (defaults: `senderIP`, port 53001)
- [x] `artnet_audio` → `ArtAudioCmd` (0x8300) packet; UDP to `target_ip:6454`
      (default: `senderIP`); supports all cmds 0–7; file included for cmd 1/2
- [x] `artnet_dmx` → `ArtDmx` (0x5000) packet; sets single channel; UDP to `target_ip:6454`
      (default: `senderIP`; sender routes to LED devices and tracks state)
- [x] `_mariusResolveTarget()` — resolves `target_ip` string or falls back to `senderIP`
- [x] `_mariusHasDest()` — guards sends when target_ip absent and sender not yet known
- [x] All three types parsed from `_mariusParseActionArray()` with field validation

---

## Phase 4 — Display + sender UI + editor

Goal: visible status on device and in Radius Central; editor for marius.json.

### `display.h` — Screen 5 (ESP32-S3 V2 only)

- [x] Add Screen 5: Marius status screen
  - Header: "DeviceName | Marius BLE"
  - State line: "Scanning..." (yellow) / "Connecting..." (orange) / puck name (cyan)
  - Last event: "PRESS" (green) / "RELEASE" (yellow) / "—"
  - Footer: "D1: Revert to Radius" or "BLE reverted — reboot to restore"
- [x] `displayMariusStatus(uint8_t state, puckName, lastEvent)` — full redraw
- [x] `displayMariusUpdate(uint8_t state, puckName, lastEvent)` — partial update
- [x] `MARIUS_DISPLAY_*` constants defined in display.h (avoids circular header dep with marius.h)
- [x] Screen cycle (D0) includes Screen 5 only when `mariusIsConfigured()` is true
- [x] D1 on Screen 5 → `mariusRevert()` + update display to "Reverted"
- [x] `mariusUpdate()` calls `displayMariusUpdate()` on state or event change

### Sender — `state.py` + `artnet.py` + `radius.html`

- [x] `artnet.py`: parse `MC:0/1` and `MP:name` from ArtPollReply node report capability tag
- [x] `state.py`: propagate `marius_connected` and `marius_puck` into device state dict + API response
- [x] `radiusV2.ino`: ArtPollReply includes `|MC:0/1|MP:PuckName` when Marius configured
- [x] Show "BLE" badge on audio device card when `marius_connected` is true

### Radius Central — Marius editor tab

- [x] New "Marius" tab in Radius Central navbar
- [x] Device selector dropdown (connected audio devices) with Load/Save buttons
- [x] `puck_name` field
- [x] Press and Release event sections each with ordered action list
- [x] Per-action: type dropdown + conditional fields:
  - `audio_play`: file, volume, loop checkbox
  - `audio_stop`: no fields
  - `osc`: address, target_ip, target_port
  - `artnet_audio`: cmd (0–7 dropdown), file (cmd 1/2), volume, target_ip
  - `artnet_dmx`: universe, channel, value, target_ip
- [x] Move up/down buttons per action
- [x] "↑ Save" → POST `/api/marius/push` (FTP upload /marius.json)
- [x] "↓ Load" → GET `/api/marius?ip=...` (FTP download /marius.json)
- [x] Export / Import JSON local backup
- [x] `server.py`: GET `/api/marius?ip=...` and POST `/api/marius/push` endpoints
- [x] `marius.js`: Alpine component (`mariusEditor()`)

---

## Phase 5 — Accel actions (stretch goal)

Goal: accelerometer data from Puck drives expressive actions.

- [ ] `mariusDispatch()` handles `"accel"` event with parsed x/y/z floats
- [ ] `osc` action for accel: send `/marius/accel` with three float args to sender
- [ ] `audio_play` with `"volume_from": "accel_magnitude"` — map accel magnitude to volume
- [ ] Rate-limit accel dispatch (Puck sends at 12.5 Hz; cap OSC sends at same rate)
- [ ] Editor: add Accel event section

---

## Sender UI — Radius Central

- [ ] Add Marius device status to `/api/state` device object:
  - `marius_connected` (bool)
  - `marius_puck` (string — connected Puck name or "")
- [ ] Expose `marius_connected` and `marius_puck` in `/api/state` response (`state.py`)
- [ ] Show Marius BLE status badge in the Radius Central audio device card (`radius.html`)
- [ ] **Marius editor tab** in Radius Central — visual editor for `marius.json`:
  - Select target Radius device (dropdown of connected audio devices)
  - `puck_name` text field (BLE device to connect to)
  - Three event sections: Press, Release, Accel — each with an action list
  - Per-action: type dropdown + type-specific fields (file, volume, address, cmd, universe,
    channel, value, target_ip)
  - "Save to Device" button — serialises to JSON and FTP-uploads to `/marius.json` on that device
  - "Load from Device" button — FTP-downloads and populates the editor
  - "Load from file" / "Export" for local backup

---

## `marius.json` examples

### Simple one-shot: press plays, release stops
```json
{
  "puck_name": "Puck.js abc",
  "actions": {
    "press":   [{ "type": "audio_play", "file": "drone.wav", "volume": 80, "loop": true }],
    "release": [{ "type": "audio_stop" }]
  }
}
```

### Press triggers LED flash via Art-Net DMX (routed through sender)
```json
{
  "puck_name": "Puck.js abc",
  "actions": {
    "press":   [
      { "type": "audio_play", "file": "hit.wav", "volume": 90 },
      { "type": "artnet_dmx", "universe": 0, "channel": 1, "value": 255 }
    ],
    "release": [
      { "type": "artnet_dmx", "universe": 0, "channel": 1, "value": 0 }
    ]
  }
}
```

### Same, but sent directly to a specific LED device (bypass sender)
```json
{
  "puck_name": "Puck.js abc",
  "actions": {
    "press":   [{ "type": "artnet_dmx", "target_ip": "192.168.8.103", "universe": 0, "channel": 1, "value": 255 }],
    "release": [{ "type": "artnet_dmx", "target_ip": "192.168.8.103", "universe": 0, "channel": 1, "value": 0 }]
  }
}
```

### Accel data streamed as OSC to sender
```json
{
  "puck_name": "Puck.js abc",
  "actions": {
    "press":   [{ "type": "audio_play", "file": "drone.wav", "volume": 70, "loop": true }],
    "release": [{ "type": "audio_stop" }],
    "accel":   [{ "type": "osc", "address": "/marius/accel" }]
  }
}
```

---

## BLE + WiFi coexistence note

ESP32 (both HUZZAH32 and S3) shares the 2.4 GHz radio between WiFi and BLE. NimBLE-Arduino
handles coexistence automatically via the ESP-IDF controller; no manual radio switching is
needed. However, BLE connection intervals and WiFi throughput will contend. For Marius the
data rate is low (button events + 12.5 Hz accel) so contention should be negligible.
NimBLE is strongly preferred over the classic Arduino BLE library for coexistence stability.

---

## Decisions

- [x] **Always-on**: if `/marius.json` is present at boot, Marius mode activates automatically.
      Screen 5 shows BLE status and has a D1 "Revert to Radius" action that disables BLE scanning
      for the session only — does not rename or delete `marius.json`. Device remains a Marius
      again after reboot.
- [x] **OSC default target**: `senderIP` (already known from Art-Net discovery). Each action
      has its own optional `target_ip`; there is no global target in the JSON file.
- [x] **`artnet_dmx` default**: sender IP. Direct `target_ip` per-action for low-latency override.
- [x] **Accel actions**: deferred to Phase 5 (stretch goal). `accel` lines from the Puck are
      parsed and logged to serial but no actions are fired until Phase 5.
- [x] **Multiple Pucks**: deferred as a low-priority stretch goal. One Puck per Marius device.

---

## Testing

- [ ] Flash Puck.js with `puckjsbutton.js` via Espruino Web IDE
- [ ] Confirm `btn/press` / `btn/release` / `accel` lines appear in BLE UART terminal
- [ ] Flash Radius with Marius build; confirm serial shows BLE scanning and connects to Puck
- [ ] Test `audio_play` / `audio_stop` action on press/release
- [ ] Test `osc` action — verify packet arrives in sender Net Log
- [ ] Test `artnet_audio` action — verify second Radius device plays audio
- [ ] Test `artnet_dmx` action — verify LED device responds
- [ ] Test reconnect: turn Puck off, back on — Radius should re-scan and reconnect
