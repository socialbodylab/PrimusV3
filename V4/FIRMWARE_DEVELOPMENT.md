# V4 Firmware Development

Canonical firmware for **both** Primus LED receivers and Radius audio receivers lives under `V4/Arduino/`. Upload profiles are selected in the sender Firmware panel or via the upload scripts below.

Packaged PrimusCentral apps bundle this source as a bootstrap fallback. On PrimusCentral,
the Firmware page can check GitHub releases for `PrimusReceiverFirmware-<version>.zip`
assets and install newer receiver source into app data without upgrading the sender app.

## Primus LED (`primusV3_receiver/`)

| Profile | Hardware | Upload |
|---------|----------|--------|
| `v1` | Adafruit HUZZAH32 (2022 RUR) | `./upload.sh --board v1` |
| `v2` | ESP32 Feather (2025 Make) | `./upload.sh --board v2` |
| `v3` | ESP32-S3 Reverse TFT + custom PCB (A0/A1 NeoPixel, A4 battery) | `./upload.sh --board v3` |

Discovery capability tag: `PV3CAP1|B:v1|IP:D|F:RIOHBM` (V1 and V3 add `B` in features for battery; firmware 3.8+ adds `M` for receive-mode config and `U:S:0` or `U:C:N` universe tokens).

Protocol highlights: ArtDmx pixel output, ArtOutputConfig (`0x8100`), ArtReceiveConfig (`0x8110`), ArtIPConfig (`0x8200`), UDP 6455 back-channel (`PFP` FPS, `PBT` battery on V1 and V3).

### V3 custom PCB (profile `v3`)

| Signal | Pin | Notes |
|--------|-----|-------|
| Output 0 | A0 (GPIO17) | Direct NeoPixel |
| Output 1 | A1 (GPIO18) | Direct NeoPixel |
| Battery sense | A4 (GPIO14) | 5V buck/boost output via 100k/100k divider (×2 scale) |

**Output power gating:** LED outputs stay disabled until WiFi connects (buck/boost spin-up). Strips clear and disable again on WiFi loss.

**TFT screens (D0 cycles):**

| Screen | Content |
|--------|---------|
| pg1 Dashboard | Connection banner, IP, battery % + time estimate, name, receive mode, output types with ON/OFF badges |
| pg2 Info | SSID, DHCP/static, RSSI, firmware version |
| pg3 Edit | D1 short = change value; D1 hold = next field (Out0 / Out1 / Receive mode) |

### Receive mode (`receive_mode.h`)

| Mode | ArtDmx layout |
|------|---------------|
| Split (default) | One universe per active output |
| Combined | Single universe; port A bytes then port B bytes (≤170 px total) |

NVS keys: `recvMode`, `univBase`. Runtime changes via ArtReceiveConfig or V3 TFT edit screen (pg3).

Upload flags: `--receivemode split|combined`, `--universe N`.

```bash
./V4/Arduino/upload.sh -v1 --auto --receivemode combined --universe 104
./V4/Arduino/upload.sh --board v3 --compile
./V4/Arduino/upload.sh -v3 -ssid "MyRouter" -pw "secret" --auto
```

### Battery telemetry (`PBT`)

**V1:** HUZZAH32 LiPo on **A13** (GPIO35, onboard VBAT divider). No VBUS sense — reports voltage and percent only (`power_mode` 0 when valid). Modes 3–5 cover switch-off, fault, and unavailable readings.

**V3:** 5V buck/boost rail on **A4** via 100k/100k divider. Firmware scales ADC ×2, maps regulated-rail droop to percent, and shows a **time-remaining estimate on the TFT only** (not sent in PBT).

Both profiles report every **5 s** on UDP 6455.

| Offset | Field | Description |
|--------|-------|-------------|
| 0–2 | `'P' 'B' 'T'` | Magic |
| 3 | `power_mode` | 0=battery, 1=charging, 2=plugged, 3=switch_off, 4=fault, 5=unavailable |
| 4–5 | `battery_mv` | uint16 BE, full pack millivolts |
| 6 | `battery_pct` | uint8 0–100 (255 = N/A) |
| 7 | `fw_minor` | ArtPollReply minor byte |
| 8 | `fw_major` | ArtPollReply major byte |

Sender: `PrimusTelemetryListener` in [`sender/artnet.py`](sender/artnet.py) merges `PFP` + `PBT` per device IP.

Source of truth for output types and pins: [`primusV3_receiver/config.h`](primusV3_receiver/config.h).
Receive mode module: [`primusV3_receiver/receive_mode.h`](primusV3_receiver/receive_mode.h).

### Factory clear NVS (`clear_nvs/`)

One-shot sketch that erases the entire ESP32 NVS partition (device name, show info, static IP, output types, receive mode, WiFi credentials). Covers both Preferences namespaces used by this project (`primus35` and `artnet`).

```bash
./V4/Arduino/clear_nvs_upload.sh -v1 --auto
./V4/Arduino/clear_nvs_upload.sh -v2 --auto
./V4/Arduino/clear_nvs_upload.sh -v3 --auto
./V4/Arduino/clear_nvs_upload.sh --board radius_v1 --auto
```

After upload, open serial at 115200 baud and confirm `NVS CLEAR COMPLETE`, then re-flash normal Primus or Radius firmware. This is a refurbish/reset tool — it is not part of the normal Firmware panel workflow.

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
| 5 | test_tone | Built-in 1 kHz sine burst (500 ms); no filename |
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

## VS1053 Audio Chip: Safe Patterns

### Do not use useInterrupt on ESP32

The Adafruit VS1053 library supports interrupt-driven `feedBuffer()`, but on ESP32 the SPI layer uses FreeRTOS semaphores that cannot safely be called from an ISR. Radius firmware calls `_musicMaker.feedBuffer()` from `audioUpdate()` in the main loop instead.

### sciWrite() does not check DREQ

The Adafruit VS1053 library's `sciWrite()` writes SCI register bytes directly over SPI **without checking DREQ first**:

```cpp
void Adafruit_VS1053::sciWrite(uint8_t addr, uint16_t data) {
  uint8_t buffer[4] = {VS1053_SCI_WRITE, addr, uint8_t(data >> 8), uint8_t(data & 0xFF)};
  spi_dev_ctrl->write(buffer, 4);  // no DREQ gate
}
```

The VS1053 datasheet states that SCI writes are only guaranteed when DREQ is high. A write that lands while DREQ is low may be silently dropped or corrupt an adjacent register. In practice, a bad write after `sineTest()` can put the chip into a state where subsequent `startPlayingFile()` calls produce no audio output, even though the library reports `playingMusic = true`.

### sineTest() resets the chip and leaves DREQ unstable

`sineTest()` calls `reset()` internally at the start:

```cpp
void Adafruit_VS1053::sineTest(uint8_t n, uint16_t ms) {
  reset();           // soft reset + clock setup + setVolume(40,40)
  // ... enters SM_TEST mode, plays sine wave, sends sine_stop ...
  // SM_TEST is NOT cleared on return
}
```

After `sineTest()` returns:

- `SCI_MODE` still has `SM_TEST` set — the chip is still in hardware test mode.
- DREQ may be low or transitioning as the VS1053 exits its sine burst.
- Any `sciWrite()` call (e.g. `setVolume()`) issued before DREQ is confirmed high may be lost or corrupt state.

`startPlayingFile()` does clear `SM_TEST` by writing a clean mode value to `SCI_MODE`, so normal audio playback after a `sineTest()` is safe **as long as no corrupting `sciWrite()` was called in between**.

### Safe pattern for audioTestTone()

Do not call `setVolume()` or any `sciWrite()` immediately after `sineTest()`. The working pattern in [`radius_receiver/audio.h`](radius_receiver/audio.h) is:

```cpp
void audioTestTone() {
  if (_musicMaker.playingMusic) _musicMaker.stopPlaying();
  _audioCurrentFile[0] = '\0';
  _audioLooping = false;
  // No setVolume before sineTest — reset() inside sineTest always overrides
  // to setVolume(40,40) regardless.
  _musicMaker.sineTest(0x44, 500);
  // Do NOT call setVolume() here. sciWrite() does not check DREQ; a write
  // immediately after sineTest() while DREQ is low will corrupt VS1053 state
  // and silence all subsequent audio output until the next power cycle.
}
```

ArtAudioCmd case 5 (hello / test tone from sender) must call `audioTestTone()` only — not `audioSetVolume()` before or after the sine burst. Display feedback should update before the blocking `sineTest()` call.

The version that broke playback was adding `setVolume(254, 254)` / `audioSetVolume()` **after** `sineTest()`. A `setVolume()` call immediately **before** `sineTest()` is harmless (`reset()` overrides it to 40,40), but avoid any SCI write after the tone completes.

### Controlling test tone volume (future improvement)

`sineTest()` always plays at the volume that `reset()` sets (`setVolume(40, 40)`, approximately -20 dB). To adjust volume safely after a test tone, poll DREQ before calling `setVolume()`:

```cpp
uint32_t t = millis();
while (!digitalRead(MM_DREQ_PIN) && millis() - t < 200) { delay(1); }
audioSetVolume(_audioVolume);
```

Alternatively, replace `sineTest()` with a short WAV file playback for the test tone, which gives full volume control without touching SM_TEST mode.

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
