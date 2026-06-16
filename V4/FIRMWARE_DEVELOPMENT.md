# V4 Firmware Development

Canonical firmware for **both** Primus LED receivers and Radius audio receivers lives under `V4/Arduino/`. Upload profiles are selected in the sender Firmware panel or via the upload scripts below.

## Primus LED (`primusV3_receiver/`)

| Profile | Hardware | Upload |
|---------|----------|--------|
| `v1` | Adafruit HUZZAH32 (2022 RUR) | `./upload.sh --board v1` |
| `v2` | ESP32 Feather (2025 Make) | `./upload.sh --board v2` |
| `v3` | Reverse TFT Feather + NeoPXL8 (2026 PCB) | `./upload.sh --board v3` |

Discovery capability tag: `PV3CAP1|B:v1|IP:D|F:RIOH` (V1 adds `B` in feature flags: `F:RIOHB`).

Protocol highlights: ArtDmx pixel output, ArtOutputConfig (`0x8100`), ArtIPConfig (`0x8200`), UDP 6455 back-channel (`PFP` FPS, `PBT` battery on V1).

### V1 battery telemetry (`PBT`)

V1 Huzzah32 boards read LiPo voltage on **A13** (GPIO35, onboard VBAT divider). The HUZZAH32 has no VBUS sense pin, so firmware reports **voltage and percent only** (`power_mode` 0 when valid). Modes 3–5 cover switch-off, fault, and unavailable readings. Reports every **5 s** on UDP 6455.

| Offset | Field | Description |
|--------|-------|-------------|
| 0–2 | `'P' 'B' 'T'` | Magic |
| 3 | `power_mode` | 0=battery, 1=charging, 2=plugged, 3=switch_off, 4=fault, 5=unavailable |
| 4–5 | `battery_mv` | uint16 BE, full pack millivolts |
| 6 | `battery_pct` | uint8 0–100 (255 = N/A) |
| 7 | `fw_minor` | ArtPollReply minor byte |
| 8 | `fw_major` | ArtPollReply major byte |

Sender: `PrimusTelemetryListener` in [`sender/artnet.py`](sender/artnet.py) merges `PFP` + `PBT` per device IP.

```bash
./V4/Arduino/upload.sh --board v3 --compile
./V4/Arduino/upload.sh -v3 -ssid "MyRouter" -pw "secret" --auto
```

Source of truth for output types and pins: [`primusV3_receiver/config.h`](primusV3_receiver/config.h).

---

## Radius audio (`radius_receiver/`)

Radius Central audio receiver firmware for **Feather HUZZAH32 + Music Maker FeatherWing**.

## Workload model

| | Primus LED receiver | Radius audio receiver |
|--|---------------------|------------------------|
| Network input | High bandwidth ArtDmx (~30 FPS) | Small sporadic Art-Net commands |
| Critical path | Frame assembly → NeoPixel | `audioUpdate()` → VS1053 + SD SPI |
| Success metric | Frame latency, show() timing | No audio dropouts, stable loop time |

Radius firmware optimizes for **audio-first loop scheduling** and **exclusive SD access**, not Art-Net throughput.

## Loop priority

1. `audioUpdate()` — highest when playing
2. `ftpUpdate()` — only when FTP server active
3. Art-Net UDP drain (bounded batch)
4. `checkWifiConnection()` — throttled every 200 ms
5. Buttons
6. PTR telemetry heartbeat (1 Hz while playing)
7. PFP packet-rate telemetry (1 Hz)

## Protocol

| Opcode | Name | Purpose |
|--------|------|---------|
| 0x6000 | ArtAddress | Rename (NVS) |
| 0x8200 | ArtIPConfig | Static IP / DHCP (NVS, reboot) |
| 0x8300 | ArtAudioCmd | play / loop / stop / pause / volume / test_tone / play_cue / loop_cue |
| 0x8301 | ArtFtpCmd | FTP server start/stop |

### ArtAudioCmd (0x8300)

| cmd | Name | Behavior |
|-----|------|----------|
| 0 | stop | Stop playback |
| 1 | play | Play filename from SD root |
| 2 | loop | Loop filename |
| 3 | pause | Pause |
| 4 | volume | Set VS1053 volume (byte 13) |
| 5 | test_tone | Play built-in test tone at volume |
| 6 | play_cue | Byte 13 = cue number; lookup `/cues.json` |
| 7 | loop_cue | Loop mapped cue file |

Packet layout: `[Art-Net header][opcode 0x8300][ver][cmd][volume][filename\\0][duration uint16 LE optional]`.

### `/cues.json` (SD card)

Loaded at boot by [`cues.h`](radius_receiver/cues.h) (requires ArduinoJson). Example:

```json
{
  "1": "intro.wav",
  "2": { "file": "loop.wav", "duration": 30 }
}
```

Cue numbers 1–255; firmware stores up to 64 entries. Changes require device reboot.

Discovery node report (dynamic):

```
#0001 [####] PVRAD1|B:v1|IP:D|F:RA
#0001 [####] PVRAD1|B:v1|IP:S:a.b.c.d:gw:mask|F:RA
```

UDP 6455 back-channel:

- `PFP` — 7-byte packet rate telemetry
- `PTR` — `[P][T][R][state][name_len][name…]` track name + playback state (0=stopped, 1=playing, 2=paused)

## SD / SPI contention

- `sdBusy` set while audio holds the SD bus
- FTP refused while audio is playing
- Audio commands stop FTP before playback
- FTP start stops audio before opening server

## Compile-time overrides

[`radius_upload.sh`](radius_upload.sh) supports the same `-include` override header as Primus:

```bash
./radius_upload.sh --board radius_v1 -ssid "MyRouter" -pw "secret" --name "StageLeft" --compile
./radius_upload.sh --board radius_v1 --static-ip 192.168.1.50 --gateway 192.168.1.1 --subnet 255.255.255.0 --compile
./radius_upload.sh --board radius_v1 --dhcp --compile
```

## Diagnostics

Set `RADIUS_DIAG=1` in [`config.h`](radius_receiver/config.h) (or via compile `-D RADIUS_DIAG=1`) for CSV loop timing on Serial:

```
diag,loop_us_max,heap,min_heap,playing,ftp,pkt_rate:...
```

Production builds use `RADIUS_DIAG=0` (default).

## Efficiency evaluation matrix

Run on real HUZZAH32 + Music Maker hardware for ≥60 s each:

| ID | Scenario | Pass criteria |
|----|----------|---------------|
| E1 | Idle connected | Loop p99 < 2 ms; heap stable |
| E2 | Playing WAV | No audible glitches; loop p99 < 5 ms |
| E3 | Play + Poll burst | No glitches during 10 Poll/s |
| E4 | FTP upload via UI | Completes; audio blocked until FTP stops |
| E5 | FTP cmd while playing | FTP rejected or audio stopped cleanly first |
| E6 | Command storm | Last command wins; no crash |
| E7 | WiFi drop during play | Reconnects; no SD hang |
| E8 | Loop mode 10 min | Heap drift < 4 KB |

Record results in a dev log when validating releases.

## Sign-off checklist

- [ ] E1–E8 executed on reference hardware
- [ ] ArtIPConfig static + DHCP revert verified from Radius Central device panel
- [ ] PTR track name visible in sender UI while playing
- [ ] `--compile` flash usage under 85% on HUZZAH32 partition
