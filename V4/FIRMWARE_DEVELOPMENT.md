# V4 Firmware Development

Canonical firmware for **both** Primus LED receivers and Radius audio receivers lives under `V4/Arduino/`. Upload profiles are selected in the sender Firmware panel or via the upload scripts below.

## Primus LED (`primusV3_receiver/`)

| Profile | Hardware | Upload |
|---------|----------|--------|
| `v1` | Adafruit HUZZAH32 (2022 RUR) | `./upload.sh --board v1` |
| `v2` | ESP32 Feather (2025 Make) | `./upload.sh --board v2` |
| `v3` | Reverse TFT Feather + NeoPXL8 (2026 PCB) | `./upload.sh --board v3` |

Discovery capability tag: `PV3CAP1|B:v1|IP:D|F:RIOHBM` (V1 battery adds `B` in features; firmware 3.8+ adds `M` for receive-mode config and `U:S:0` or `U:C:N` universe tokens).

Protocol highlights: ArtDmx pixel output, ArtOutputConfig (`0x8100`), ArtReceiveConfig (`0x8110`), ArtIPConfig (`0x8200`), UDP 6455 back-channel (`PFP` FPS, `PBT` battery on V1).

### Receive mode (`receive_mode.h`)

| Mode | ArtDmx layout |
|------|---------------|
| Split (default) | One universe per active output |
| Combined | Single universe; port A bytes then port B bytes (≤170 px total) |

NVS keys: `recvMode`, `univBase`. Runtime changes via ArtReceiveConfig or V3 TFT (D1 on Receive screen).

Upload flags: `--receivemode split|combined`, `--universe N`.

```bash
./V4/Arduino/upload.sh -v1 --auto --receivemode combined --universe 104
./V4/Arduino/upload.sh --board v3 --compile
./V4/Arduino/upload.sh -v3 -ssid "MyRouter" -pw "secret" --auto
```

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

Source of truth for output types and pins: [`primusV3_receiver/config.h`](primusV3_receiver/config.h).
Receive mode module: [`primusV3_receiver/receive_mode.h`](primusV3_receiver/receive_mode.h).

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

### Art-Net opcode registry (single source of truth)

This table is the **authoritative allocation** for every Art-Net opcode the sender and
firmware use. It is the same list held in `V4/sender/artnet.py` (`ARTNET_OPCODE_*`) and in
each firmware `config.h`. **Enforced by `V4/sender/tests/test_artnet_opcodes.py`**, which
asserts (a) all sender opcodes are pairwise-unique, (b) every opcode a firmware `config.h`
defines equals the sender's value, and (c) the two firmware families agree on shared opcodes.
Add a new opcode here **and** in `artnet.py` **and** in the relevant `config.h` in the same
change, or the test fails.

Vendor-defined opcodes live in the `0x8000+` range, sub-allocated by concern:
`0x81xx` output/receive config · `0x82xx` node identity (IP, show info) · `0x83xx` Radius audio.

| Opcode | Name | LED (`primusV3_receiver`) | Radius (`radius_receiver`) | Purpose |
|--------|------|:---:|:---:|---------|
| 0x2000 | ArtPoll | ✅ | ✅ | Discovery request |
| 0x2100 | ArtPollReply | ✅ | ✅ | Discovery reply (capability tag) |
| 0x5000 | ArtDmx | ✅ | — | Pixel data (LED only) |
| 0x6000 | ArtAddress | ✅ | ✅ | Rename (NVS) |
| 0x8100 | ArtOutputConfig | ✅ | — | Set output types (LED only) |
| 0x8110 | ArtReceiveConfig | ✅ | — | Set receive mode / universe base (LED only) |
| 0x8200 | ArtIPConfig | ✅ | ✅ | Static IP / DHCP (NVS, reboot) |
| 0x8210 | ArtShowInfo | ✅ | ✅ | Character/performer names (NVS): read / write / response, 143-byte packet, two 64-byte fields |
| 0x8300 | ArtAudioCmd | — | ✅ | play / loop / stop / pause / volume / test_tone / play_cue / loop_cue |
| 0x8301 | ArtFtpCmd | — | ✅ | FTP server start/stop |
| 0x8302 | ArtAudioStatus | — | ✅ | Unsolicited playback status from device → sender (UDP 6455) |

> **Merge guardrail (radius-central → main / V5).** The `0x83xx` audio range
> (`ArtAudioCmd`, `ArtFtpCmd`, `ArtAudioStatus`) is **new on the `radius-central` branch**;
> `0x8110` (`ArtReceiveConfig`) and `0x8210` (`ArtShowInfo`) also exist on `main`. All of them
> must coexist after the merge — do **not** let a merge drop the `0x83xx` block or renumber it
> back into `0x82xx` (the historical `0x8200` collision that forced the original remap). If a
> conflict touches the opcode block in `artnet.py` or either `config.h`, keep the union of both
> sides and run `test_artnet_opcodes.py` — a green run is the proof the allocation is still
> collision-free and firmware/sender are in sync.

Radius capability flags in the ArtPollReply node report (`PVRAD1|…|F:`):
`R` rename, `A` audio (implies FTP), `S` show info, `B` battery telemetry
(rv1 only — HUZZAH32 A13 half-divider, 9-byte `PBT` packets on UDP 6455
every 5 s, skipped while a track is playing because audio is main-loop fed).

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

## VS1053 audio chip: safe patterns

The VS1053 (Music Maker FeatherWing) is the source of a whole family of "audio goes silent
or wrong until a power cycle" bugs. Each rule below cost a debugging session; each is now
pinned by `V4/sender/tests/test_firmware_source_contracts.py` so a refactor or a bad merge
cannot quietly undo it. **All of these live in `radius_receiver/audio.h`.**

> **Merge guardrail (radius-central → main / V5).** `audio.h` on this branch carries ~140
> lines of VS1053 hardening that `main` does not have yet. If a merge conflict touches
> `audio.h`, **keep this branch's guarded versions** of `_applyVolume`, `_muteChip`,
> `audioPlay`, `audioLoop`, and `audioTestTone` — do not accept a "simpler" main-side version
> that drops the clamps, the cache invalidation, or the ordering. Then run the firmware source
> contract tests; a green run is the proof the hardening survived.

### Never write SCI_VOL 254 — it is analog powerdown, not "very quiet"
`setVolume(254, 254)` (SCI_VOL ≈ 0xFEFE) is the VS1053's **analog powerdown** command; the
analog stage can stay dead until a full reset. All attenuation is clamped to
`VS1053_MAX_SAFE_ATTENUATION` (250, ≈ −125 dB, inaudible, analog stage alive) in
`_applyVolume()`. *Pinned: `test_no_analog_powerdown_volume_writes`.*

### Every hard mute and reset() must invalidate the volume cache
`_applyVolume()` skips the SCI write when the requested volume equals `_lastAppliedVolume`.
So any path that writes the chip volume directly — the hard mute in `_muteChip()`, or the
`reset()` on a sample-rate change (which sets chip volume to 40/40) — must set
`_lastAppliedVolume = 255` afterward, or the next `_applyVolume()` at the old value is skipped
and playback runs **silently** while status packets still report "playing". Route all direct
mutes through `_muteChip()`. *Pinned: `test_chip_mute_always_invalidates_volume_cache`,
`test_no_bare_soft_reset`.*

### Use the library's full `reset()`, never a bare `softReset()`
A bare `softReset()` clears `SCI_CLOCKF` (the clock multiplier); at 1.0× the decoder cannot
run and playback streams silently while `playingMusic` stays true. `reset()` restores CLOCKF
with the settle delays this hardware needs. Used only on a sample-rate change in `audioPlay()`.
*Pinned: `test_no_bare_soft_reset`.*

### `sciWrite()` does not gate on DREQ — no SCI writes right after `sineTest()`
The Adafruit library's `sciWrite()` writes SPI without checking DREQ. `sineTest()` leaves the
chip exiting SM_TEST with DREQ low/transitioning, so a `setVolume()`/`sciWrite()` issued before
DREQ goes high can be dropped or corrupt an SCI register — silencing **all** later playback
until a power cycle. The runtime `audioTestTone()` therefore ends on `sineTest()` with no volume
write after it. (`audioBootTest()` may set volume *before* `sineTest()` — its internal `reset()`
overrides it — which is safe.) To control test-tone volume in future, poll `MM_DREQ_PIN` high
first. *Pinned: `test_no_sci_write_after_sinetest_in_test_tone`.*

### `delay(20)` after `stopPlaying()` before feeding a new file
Switching tracks without letting the codec flush makes it misparse the next WAV header and play
at the wrong pitch (or silently). `audioPlay()` waits after `stopPlaying()`. *Pinned:
`test_delay_after_stop_playing_before_new_file`.*

### `_audioLooping = true` must be set AFTER `audioPlay()`
`audioPlay()` resets `_audioLooping` to false, so setting the flag before the call makes loops
play exactly once. This one has regressed on every port. *Pinned:
`test_audio_looping_set_after_audio_play`.*

### Battery sampling is gated on `!audioIsPlaying()`
Reading VBAT blocks ~16 ms; Radius audio is main-loop fed (no DREQ interrupt), so a mid-track
sample underruns the VS1053. *Pinned: `test_battery_tick_skips_active_playback`.*

## SD / SPI contention

- `sdBusy` set while audio holds the SD bus
- FTP refused while audio is playing
- Audio commands stop FTP before playback
- FTP start stops audio before opening server

## Compile-time overrides

[`upload.sh`](upload.sh) supports the same `-include` override header for Radius profiles as for Primus:

```bash
./upload.sh -rv1 -ssid "MyRouter" -pw "secret" --name "StageLeft" --compile
./upload.sh -rv1 --static-ip 192.168.1.50 --gateway 192.168.1.1 --subnet 255.255.255.0 --compile
./upload.sh -rv1 --dhcp --compile
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
