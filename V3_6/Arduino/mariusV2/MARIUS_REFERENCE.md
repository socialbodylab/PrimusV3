# Marius — Reference

Marius is a BLE performance controller layer for a Radius audio device. A Puck.js v2 worn
by a performer sends button and accelerometer events over Bluetooth; the Radius receives
them, reads an action map from `/marius.json` on its SD card, and fires the configured
actions — local audio playback, OSC to the sender, Art-Net audio to another Radius, or
Art-Net DMX to an LED receiver.

## System architecture

```
[Puck.js v2]
  Button press/release  → "btn/press" / "btn/release"  over BLE UART (NUS)
  Accelerometer (held)  → "accel x y z" at 12.5 Hz     over BLE UART
  Triple-tap            → "btn/sleep" then NRF.sleep()
        ↓  BLE (Nordic UART Service)
[Radius device — ESP32-S3 or HUZZAH32]
  marius.h    — BLE central: scan → connect → subscribe to NUS notifications
  marius.json — action map on SD card (loaded at boot, hot-reloaded via FTP)
  action dispatch:
    • audio_play / audio_stop   → local VS1053 via audio.h
    • osc                       → UDP OSC 1.0 packet to sender
    • artnet_audio              → ArtAudioCmd (0x8300) to a Radius device
    • artnet_dmx                → ArtDmx (0x5000) to an LED receiver
        ↓  WiFi / Art-Net / OSC
[Sender / other Radius / LED receivers]
```

Marius mode activates automatically at boot when `/marius.json` is present on the SD card.
If the file is absent the device operates as a normal Radius. The Marius BLE screen (Screen 5
on ESP32-S3 V2) shows scan/connect status and the last event; D2 reverts BLE for the session.

---

## Puck.js BLE UART messages

| Message | When sent |
|---|---|
| `btn/press` | Button pressed down |
| `btn/release` | Button released |
| `accel x y z` | 12.5 Hz while button held; x/y/z are float g values |
| `btn/sleep` | Triple-tap detected — sent just before `NRF.sleep()` |

**Triple-tap sleep**: three complete press+release cycles within 800 ms.
`NRF.sleep()` turns off the BLE radio; the CPU and `setWatch` keep running.

**Wake**: the next button press calls `NRF.wake()` to restore BLE advertising and returns
without firing a cue. The Radius receives `btn/sleep` and immediately disconnects and
restarts scanning so it is ready before the user wakes the Puck.

---

## `marius.json` format

File lives at `/marius.json` on the Radius SD card. Loaded at boot; reloaded automatically
within 5 seconds when FTP uploads a new version (file-size change detection).

```json
{
  "puck_name": "Puck.js d8c8",
  "actions": {
    "press":       [...],
    "release":     [...],
    "press_cycle": [...],
    "accel":       [...]
  }
}
```

| Field | Description |
|---|---|
| `puck_name` | BLE advertised name of the Puck to connect to |
| `actions.press` | All listed actions fire on every button press |
| `actions.release` | All listed actions fire on every button release |
| `actions.press_cycle` | One action fires per press, advancing round-robin through the list |
| `actions.accel` | Phase 5 — not yet implemented |

`press` and `press_cycle` are independent. Both can be defined and both will fire on a press.
Each event's actions are an array; up to 8 actions per event are supported.

---

## Action types

### `audio_play`
Play or loop a WAV file on the local Radius device.

```json
{ "type": "audio_play", "file": "drone.wav", "volume": 80, "loop": true }
```

| Field | Required | Notes |
|---|---|---|
| `file` | yes | WAV filename on the SD card |
| `volume` | no | 0–100; omit to use the device's current volume |
| `loop` | no | `true` to loop continuously; default `false` |

---

### `audio_stop`
Stop local audio playback.

```json
{ "type": "audio_stop" }
```

No additional fields.

---

### `osc`
Send an OSC 1.0 address-only message over UDP.

```json
{ "type": "osc", "address": "/cue/1", "target_ip": "192.168.8.10", "target_port": 53001 }
```

| Field | Required | Notes |
|---|---|---|
| `address` | yes | OSC address string, e.g. `/cue/1`, `/stop` |
| `target_ip` | no | Defaults to sender IP (from Art-Net discovery) |
| `target_port` | no | Defaults to 53001 |

---

### `artnet_audio`
Send an `ArtAudioCmd` (opcode `0x8300`) to a Radius device.

```json
{ "type": "artnet_audio", "cmd": 1, "file": "hit.wav", "volume": 90, "target_ip": "192.168.8.151" }
```

| Field | Required | Notes |
|---|---|---|
| `cmd` | yes | Audio command (see table below) |
| `file` | yes for cmd 1/2 | WAV filename; required for play and loop |
| `volume` | no | 0–100 |
| `target_ip` | no | Defaults to sender IP |

| `cmd` | Action |
|---|---|
| 0 | Stop |
| 1 | Play |
| 2 | Loop |
| 3 | Pause |
| 4 | Set volume |
| 5 | Test tone |
| 6 | Play cue (resolved from `/cues.json` on target SD) |
| 7 | Loop cue |

---

### `artnet_dmx`
Send an `ArtDmx` (opcode `0x5000`) packet setting a single channel value.

```json
{ "type": "artnet_dmx", "universe": 0, "channel": 1, "value": 255, "target_ip": "192.168.8.103" }
```

| Field | Required | Notes |
|---|---|---|
| `universe` | yes | 0-based Art-Net universe |
| `channel` | yes | 1–512 |
| `value` | yes | 0–255 |
| `target_ip` | no | Defaults to sender IP (sender routes to LED receivers and tracks state) |

---

## Routing defaults

All network actions (`osc`, `artnet_audio`, `artnet_dmx`) default to sending to the sender IP,
which the Radius learns automatically from incoming Art-Net discovery packets. The sender acts
as a central hub for routing, state tracking, and the Net Log.

`target_ip` can be set per-action for direct device-to-device sends — useful for low-latency
cases like one Radius triggering audio on another without involving the sender. Use sparingly;
direct sends bypass the sender's state tracking and Net Log.

Network actions are silently skipped if no destination is available (no `target_ip` set and
sender not yet discovered). This resolves itself once the Radius receives its first Art-Net
packet from the sender.

---

## Examples

### Alternating cues on each press
```json
{
  "puck_name": "Puck.js d8c8",
  "actions": {
    "press_cycle": [
      { "type": "osc", "address": "/cue/1" },
      { "type": "osc", "address": "/cue/3" }
    ]
  }
}
```

### Press plays, release stops
```json
{
  "puck_name": "Puck.js d8c8",
  "actions": {
    "press":   [{ "type": "audio_play", "file": "drone.wav", "volume": 80, "loop": true }],
    "release": [{ "type": "audio_stop" }]
  }
}
```

### Press triggers audio and LED flash
```json
{
  "puck_name": "Puck.js d8c8",
  "actions": {
    "press": [
      { "type": "audio_play", "file": "hit.wav", "volume": 90 },
      { "type": "artnet_dmx", "universe": 0, "channel": 1, "value": 255 }
    ],
    "release": [
      { "type": "artnet_dmx", "universe": 0, "channel": 1, "value": 0 }
    ]
  }
}
```

### Direct LED control bypassing sender
```json
{
  "puck_name": "Puck.js d8c8",
  "actions": {
    "press":   [{ "type": "artnet_dmx", "target_ip": "192.168.8.103", "universe": 0, "channel": 1, "value": 255 }],
    "release": [{ "type": "artnet_dmx", "target_ip": "192.168.8.103", "universe": 0, "channel": 1, "value": 0 }]
  }
}
```

### Trigger audio on a second Radius
```json
{
  "puck_name": "Puck.js d8c8",
  "actions": {
    "press":   [{ "type": "artnet_audio", "cmd": 1, "file": "hit.wav", "volume": 85, "target_ip": "192.168.8.151" }],
    "release": [{ "type": "artnet_audio", "cmd": 0, "target_ip": "192.168.8.151" }]
  }
}
```

---

## Hot-reload

Upload a new `marius.json` via FTP while the device is running and it will be picked up
within 5 seconds without a reboot. FTP is available at the device IP on port 21
(credentials: `primus` / `primus`). The reload is skipped if the SD is busy with audio
playback and retried on the next 5-second poll.

```bash
curl -T marius.json ftp://192.168.8.150/marius.json --user primus:primus
```

The reload is detected by file size change. If you upload a file with the exact same byte
count, the reload will not trigger — in practice any real edit changes the size.

---

## BLE + WiFi coexistence

ESP32 shares the 2.4 GHz radio between WiFi and BLE. NimBLE-Arduino handles coexistence
automatically via the ESP-IDF controller. For Marius the BLE data rate is low (button events
+ 12.5 Hz accel) so contention with WiFi is negligible in practice.
