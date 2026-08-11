# V5 Firmware Development

Canonical firmware for **both** Primus LED receivers and Radius audio receivers lives under `V5/Arduino/`. Upload profiles are selected in the sender Firmware panel or via the upload scripts below.

Packaged PrimusCentral apps bundle this source as a bootstrap fallback. On PrimusCentral,
the Firmware page can check GitHub releases for `PrimusReceiverFirmware-<version>.zip`
assets and install newer receiver source into app data without upgrading the sender app.

## Primus LED (`primusV3_receiver/`)

| Profile | Hardware | Upload |
|---------|----------|--------|
| `v1` | Adafruit HUZZAH32 (2022 RUR) | `./upload.sh --board v1` |
| `v2` | ESP32 Feather (2025 Make) | `./upload.sh --board v2` |
| `v3` | ESP32-S3 Reverse TFT + custom PCB (A0/A1 NeoPixel, A4 battery) | `./upload.sh --board v3` |

Discovery capability tag: `PV3CAP1|F:RIOHBMSG|B:v1|IP:D|U:C:0|G:1P`.
V1 and V3 add `B` for battery data; `G` advertises management and `G:1P` /
`G:1L` marks protocol v1 prototype/locked mode. Long Name and ArtPoll
`NumPorts` always inventory A0 and A1, including Off. Full descriptors come
from `GET_CONFIG`, not the 64-byte Node Report.

Protocol highlights: ArtDmx pixel output, paired management request/reply
(`0x8140`/`0x8141`), and explicit-target UDP 6455 unified status (`PST` v1).
Legacy ArtAddress and `0x8100`/`0x8110`/`0x8130`/`0x8200`/`0x8210` mutations
remain compatible in prototype mode.

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
| Split (default) | Stable slots: A0 = base, A1 = base+1, even when one is Off |
| Combined | Single universe; port A bytes then port B bytes (≤170 px total) |

NVS keys: `recvMode`, `univBase`. Runtime changes via ArtReceiveConfig or V3 TFT edit screen (pg3).

Upload flags: `--receivemode split|combined`, `--universe N`.

```bash
./V5/Arduino/upload.sh -v1 --auto --receivemode combined --universe 104
./V5/Arduino/upload.sh --board v3 --compile
./V5/Arduino/upload.sh -v3 -ssid "MyRouter" -pw "secret" --auto
```

### Management, output descriptors, and production mode

[`Arduino/primusV3_receiver/management_protocol.h`](Arduino/primusV3_receiver/management_protocol.h)
defines protocol v1, the 12-byte fixed OutputDescriptor, and the NVS descriptor
schema. Each of the two slots persists enabled/off, physical count (1–170),
linear/grid layout, rows, columns, row/column-major traversal,
progressive/serpentine scan, start corner, and virtual pixels. Grid fields are
metadata only; ArtDmx stays RGB in physical wire order. Combined total virtual
pixels remains limited to 170.

NVS key `outDescAll` is authoritative: one 28-byte blob containing schema,
slot count, both descriptors, and CRC-16/CCITT. A single NVS key update prevents
reset-time hybrid slot state, and the checksum rejects torn/corrupt data. On
first boot, the earlier 3.14 per-slot `outSchema`/`outDesc0`/`outDesc1` format
is validated and migrated once; older `otype0/1` and `vpx0/1` settings are the
next migration source. Reboots are idempotent and built-in definitions remain
the final safe defaults.

Management uses a fixed 20-byte envelope with protocol version, operation,
request ID, payload length, ACK/NACK status, and error code. Operations cover
`GET_CONFIG`, atomic two-slot descriptor updates, telemetry target, operating
mode, receive config, IP config, identity, and V1/V2 boot-window unlock. The
dependency-free executable codec and golden packets live in
[`sender/primus_protocol.py`](sender/primus_protocol.py) and
[`sender/tests/test_primus_protocol.py`](sender/tests/test_primus_protocol.py).

Shared UIs and third-party tools that talk to the V5 sender instead of sending
Art-Net directly should use the sender's explicit HTTP management facade
(`GET /api/device_full_config`, `GET /api/device_lock_state`,
`POST /api/refresh_device_full_config`, `POST /api/apply_device_output_descriptor`,
`POST /api/set_device_telemetry_target`, `POST /api/enter_device_production_mode`,
`POST /api/unlock_device_boot_window`, and `GET/POST/DELETE /api/output_presets`).
Those routes always refresh with authoritative `GET_CONFIG` after mutations and
surface management NACKs as structured JSON errors with route-level HTTP
statuses; see [`../API_REFERENCE.md`](../API_REFERENCE.md).

Production mode (`opMode` NVS key) locks technical/show names, network config,
descriptors, receive mode/base, and telemetry target. Legacy mutations are
ignored and management receives `NACK/LOCKED`; ArtDmx, discovery, status, and
identification remain active. V3 exits production with a local D1 long press;
D1 short toggles the TFT, which starts off in production. V1/V2 accept remote
unlock only during the first 60 seconds after boot.

#### Compatibility and commissioning

- Firmware 3.14+ management descriptors are authoritative. Both A0/A1 are
  always returned, including Off, so commissioning tools must not infer slot
  existence from active pixel count.
- The atomic `outDescAll` blob migrates the earlier per-slot management schema
  first, then legacy `otype0/1` plus `vpx0/1`; invalid CRC/schema data falls back
  safely to built-ins. Sender-side preset files do not alter firmware NVS until
  a preset is explicitly applied.
- Legacy nodes continue through capability-aware `0x8100`/`0x8110`/`0x8130`
  controls. Custom descriptors, explicit PST target, readback, and production
  lock require management support.
- Commission telemetry by writing `teleTarget`; do not derive it from ArtDmx,
  ArtPoll, EOS, or the latest packet source. `0.0.0.0` intentionally means no
  telemetry.
- Management protocol v1 has no multi-sender lease or ownership arbitration.
  Use one commissioning authority and production lock. Arbitration is deferred
  to a future version rather than added as a compatibility-breaking heuristic.

### Unified status and battery semantics

**V1:** HUZZAH32 LiPo on **A13** (GPIO35, onboard VBAT divider). No VBUS sense — reports voltage and percent only (`power_mode` 0 when valid). Modes 3–5 cover switch-off, fault, and unavailable readings.

**V2:** explicit unavailable battery mode, 0 mV, and 255 percent.

**V3:** 5V buck/boost rail on **A4** via 100k/100k divider. Firmware scales ADC x2, maps regulated-rail droop to percent, and shows a time-remaining estimate on the TFT only.

`teleTarget` is a persisted four-byte unicast IPv4 address. Unset means no
status. Packet sources never update it. `PST` is sent once per second with
MAC-derived phase jitter and includes sequence, uptime, flags, rendered FPS x10,
packet rate x10, RSSI, firmware version, operating/lock state, unlock time, and
battery mode/mV/percent. New Primus firmware does not emit PFP/PBT.

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
firmware use. The same list is held in `V5/sender/artnet.py` (`ARTNET_OPCODE_*`, plus the
versioned management pair in `V5/sender/primus_protocol.py`) and in each firmware `config.h`.
**Enforced by `V5/sender/tests/test_artnet_opcodes.py`**, which asserts (a) all sender opcodes
are pairwise-unique, (b) every opcode a firmware `config.h` defines equals the sender's value,
and (c) the two firmware families agree on shared opcodes. Add a new opcode here **and** in the
sender **and** in the relevant `config.h` in the same change, or the test fails.

Vendor-defined opcodes live in the `0x8000+` range, sub-allocated by concern:
`0x81xx` config / management · `0x82xx` node identity (IP, show info) · `0x83xx` Radius audio.

| Opcode | Name | LED (`primusV3_receiver`) | Radius (`radius_receiver`) | Purpose |
|--------|------|:---:|:---:|---------|
| 0x2000 | ArtPoll | ✅ | ✅ | Discovery request |
| 0x2100 | ArtPollReply | ✅ | ✅ | Discovery reply (capability tag) |
| 0x5000 | ArtDmx | ✅ | — | Pixel data (LED only) |
| 0x6000 | ArtAddress | ✅ | ✅ | Rename (NVS) |
| 0x8100 | ArtOutputConfig | ✅ | — | Set output types (LED only) |
| 0x8110 | ArtReceiveConfig | ✅ | — | Set receive mode / universe base (LED only) |
| 0x8130 | ArtVirtualResolution | ✅ | — | Set virtual grid resolution (LED only) |
| 0x8140 | ArtManagementRequest | ✅ | — | Versioned Primus management request |
| 0x8141 | ArtManagementReply | ✅ | — | Versioned Primus management reply |
| 0x8200 | ArtIPConfig | ✅ | ✅ | Static IP / DHCP (NVS, reboot) |
| 0x8210 | ArtShowInfo | ✅ | ✅ | Character/performer names (NVS): read / write / response, 143-byte packet, two 64-byte fields |
| 0x8300 | ArtAudioCmd | — | ✅ | play / loop / stop / pause / volume / test_tone / play_cue / loop_cue |
| 0x8301 | ArtFtpCmd | — | ✅ | FTP server start/stop |
| 0x8302 | ArtAudioStatus | — | ✅ | Unsolicited playback status from device → sender (UDP 6455) |

> **Merge guardrail.** The `0x83xx` audio range (`ArtAudioCmd`, `ArtFtpCmd`, `ArtAudioStatus`)
> came from the `radius-central` line and the `0x8140`/`0x8141` management pair from the Primus
> DeviceManager line; all must coexist. If a future merge from `main` conflicts on the opcode
> block in `artnet.py` / `primus_protocol.py` or either `config.h`, keep the **union** of both
> sides and run `test_artnet_opcodes.py` — a green run proves the allocation is still
> collision-free and firmware/sender are in sync. Never renumber the `0x83xx` block back into
> `0x82xx` (the historical `0x8200` collision that forced the original remap).

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
pinned by `V5/sender/tests/test_firmware_source_contracts.py` so a refactor or a bad merge
cannot quietly undo it. **All of these live in `radius_receiver/audio.h`.**

> **Merge guardrail.** `audio.h` carries ~140 lines of VS1053 hardening that a plain `main`
> tree does not have. If a merge conflict touches `audio.h`, **keep the guarded versions** of
> `_applyVolume`, `_muteChip`, `audioPlay`, `audioLoop`, and `audioTestTone` — do not accept a
> "simpler" version that drops the clamps, the cache invalidation, or the ordering. Then run the
> firmware source contract tests; a green run is the proof the hardening survived.

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

[`upload.sh`](upload.sh) supports the same `-include` override header as Primus:

```bash
./upload.sh --board radius_v1 -ssid "MyRouter" -pw "secret" --name "StageLeft" --compile
./upload.sh --board radius_v1 --static-ip 192.168.1.50 --gateway 192.168.1.1 --subnet 255.255.255.0 --compile
./upload.sh --board radius_v1 --dhcp --compile
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
