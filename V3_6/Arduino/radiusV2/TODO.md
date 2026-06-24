# Radius Firmware — TODO

---

## Firmware

### Boot sequence

Current boot plays no audio and starts FTP unconditionally regardless of SD state.

Agreed sequence:
1. VS1053 init — error screen if codec fails
2. Play VS1053 test tone beep (built-in synth, no SD needed — hardware confirmation)
3. SD init
   - SD ready → scan `/` (root only) for first `.wav` file; play it for 2 s at volume 60 using the existing `duration` param in `audioPlay()`
   - SD not ready → auto-navigate to Screen 4 (SD error screen)
4. Start FTP only if SD is ready; skip `ftpStart()` if SD is missing
5. If SD retry succeeds from Screen 4 (D1 button), call `ftpStart()` then

- [x] After `audioInit()`, always call `audioTestTone()` as the boot beep — already in `audioBootTest()`
- [x] After SD init, if `audioSdIsReady()`: scan SD root for first `.wav` file and call `audioPlay(filename, 60, 2)` — implemented in `audioBootTest()` in `audio.h`
- [x] Gate `ftpStart()` in `setup()` on `audioSdIsReady()` — `radiusV2.ino`
- [x] In the Screen 4 SD retry handler, call `ftpStart()` after a successful retry — `radiusV2.ino`
- [x] If SD not ready after init, call `displaySdStatus(false, 0)` immediately — `radiusV2.ino`

### MAX9744 amplifier integration (Variant B) — LOW PRIORITY

The I2C wiring and volume control pattern are documented in `HARDWARE_WIRING.md` but not yet implemented in firmware. Deferred until Variant B hardware is assembled.

- [ ] Add `#define MAX9744_I2C_ADDR 0x4B` to `config.h`
- [ ] Add `Wire.begin()` to `setup()` in `radiusV2.ino`
- [ ] Implement `setAmplifierVolume(uint8_t v)` — single I2C byte (0–63) to `MAX9744_I2C_ADDR`
- [ ] Hook MAX9744 volume into Art-Net cmd 4 alongside the existing `audioSetVolume()` call
- [ ] Initialise MAX9744 volume at startup (safe default: ~40/63)

### SD screen file navigation

- [x] Restore D2 button (GPIO2, active-HIGH) in `config.h` and `buttons.h`
- [x] Add `sdSelectedFile` / `sdCachedFileCount` globals to `radiusV2.ino`
- [x] `sdScreenLoadFile(advance)` — scans SD root for WAV files; loads first or advances with wrap-around
- [x] SD screen shows selected filename (size-2 text) and PLAYING / Idle status
- [x] D1 on SD screen: play/stop selected file (falls back to SD retry when card missing)
- [x] D2 on SD screen: advance to next file (wraps to first)
- [x] Natural stop and Art-Net stop both refresh SD screen immediately

### Display — known issues

- [x] **Test tone screen update**: `displayAudioStatus("test_tone", ..., true)` is called in `handleD1Press()` before the blocking `audioTestTone()` call to show "playing", and `displayAudioUpdate()` after to restore idle immediately.

### VS1053 test tone — volume control (LOW PRIORITY)

**What works today**: `audioTestTone()` calls `_musicMaker.sineTest(0x44, 500)` with no `setVolume()` before or after. The tone always plays at the volume that `sineTest()`'s internal `reset()` sets (`setVolume(40, 40)` ≈ -20 dB). This is fixed and not user-adjustable.

**What we tried and broke**: Adding `setVolume(vs1053vol, vs1053vol)` before and `setVolume(254, 254)` / `audioSetVolume(_audioVolume)` after `sineTest()`. After the first play/stop cycle the VS1053 entered a state where all subsequent audio commands (play, loop, test tone) produced no sound. Root cause: `sciWrite()` in the Adafruit VS1053 library does not check DREQ. A `sciWrite()` immediately after `sineTest()` — while DREQ may still be low from the chip exiting SM_TEST mode — is silently dropped or corrupts a VS1053 register, breaking all future SCI communication until the chip is power-cycled.

**Rule**: Never call `setVolume()` or any `sciWrite()` immediately after `sineTest()` without first confirming DREQ is high. See `FIRMWARE_DEVELOPMENT.md` → "VS1053 Audio Chip: Safe Patterns" for the full explanation and the DREQ-polling pattern to use when this is eventually needed.

**Future fix path** (when volume control for the test tone is actually needed):
- [ ] Option A: After `sineTest()`, poll `digitalRead(MM_DREQ_PIN)` with a 200 ms timeout before calling `audioSetVolume(_audioVolume)`.
- [ ] Option B: Replace `sineTest()` with a short PCM WAV file played via `audioPlay()`, which already sets volume correctly and exits SM_TEST cleanly via `startPlayingFile()`.

### Audio back-channel rename

- [x] Rename `FPS_REPORT_PORT` → `AUDIO_REPORT_PORT` in `config.h`
- [x] Remove `FPS_BACKCHANNEL_ENABLED` and `FPS_INTERVAL`; replace with `STATUS_INTERVAL`
- [x] Rename `udpFps` → `udpReport`, `lastFpsTime` → `lastStatusTime` in `radiusV2.ino`
- [x] Remove dead `sendFpsTelemetry()` function — Radius does not send FPS packets

### Audio playback bug fix

- [x] Add `delay(20)` after `stopPlaying()` in `audioPlay()` (`audio.h`) — prevents VS1053 from misparsing the new file's WAV header when switching tracks without an explicit stop, which caused playback at wrong (higher) frequency
- [x] Fix `audioLoop()` in `audio.h`: `_audioLooping = true` was set before calling `audioPlay()`, which resets it to `false`; moved the assignment to after `audioPlay()` so loop restart in `audioUpdate()` actually fires
- [x] Fix `fire_audio_cue()` in `state.py`: `duration` from per-IP action was read but never passed to `send_audio_cmd()`; added `kw["duration"] = int(duration)` alongside the existing `volume` kwarg

### Minor cleanup

- [x] `config.h` — consolidated firmware version to single source of truth (`_H`/`_L`/`_PATCH`); string derived by preprocessor. Bumped to 3.6.0 to match V3.6 system track.

---

## Sender UI

### Audio panel — device card styling
- [x] Add missing CSS for all audio panel classes (`audio-node-card`, `audio-transport`, `audio-fm-*` family) — `css/style.css`
- [x] Cue map select: add `:selected="dev._di === deviceIdx"` so selection survives state poll re-renders — `radius.html`
- [x] Fix stale V3.2 firmware reference in audio panel empty state — `radius.html`
- [x] Project library file list: cap height at 220px with scroll, restore `align-items: center` on rows — `css/style.css`, `radius.html`

### Audio panel — keyboard control
- [x] Spacebar toggles play/stop on the Audio tab — stops first playing device; if nothing playing, resumes last-played file or first WAV on first device; ignored when focus is in an input — `audio-panel.js`

### Net Log — IN messages
- [x] Log incoming FPS telemetry (rate-limited 1/s per IP) via `netlog.log_fps()` — `artnet.py`
- [x] Log incoming `ArtAudioStatus` (0x8302) packets with playing/stopped state and filename — `artnet.py`
- [x] Log outgoing `ArtPoll` per destination — `artnet.py`
- [x] Log incoming `ArtPollReply` with node name and firmware version — `artnet.py`

---

## Hardware Build

### Variant A — Headphone / Line-Out
ESP32-S3 Reverse TFT Feather + Music Maker FeatherWing (stacked) + panel-mount TRS socket

- [ ] Stack Feather + Music Maker
- [ ] Wire Music Maker 3.5mm out to panel-mount TRS socket

### Variant B — Amplifier Build
ESP32-S3 Reverse TFT Feather + Music Maker FeatherWing on FeatherWing Doubler + MAX9744 + speaker (#1314)

- [ ] Assemble Doubler with Feather (Slot A) and Music Maker (Slot B)
- [ ] Wire MAX9744 I2C: 4 wires from Doubler tap points (SDA L12, SCL L11, 3V R2, GND R4) to MAX9744 pins 4/5/6/13
- [ ] Connect Music Maker 3.5mm out → MAX9744 3.5mm in
- [ ] Wire speaker to MAX9744 Left+ / Left− via mono TS socket (or direct)
- [ ] Connect 5V ≥ 2A supply to MAX9744 barrel jack

---

## Playback Status Reporting

When a WAV file finishes playing, the firmware sends an unsolicited status packet to the sender so the UI and display reflect the current state in real time. Status is also sent on playback start for round-trip confirmation.

**Approach: new custom opcode `0x8302` `ArtAudioStatus`** sent by firmware via UDP to the sender's IP.

### Firmware (`config.h`, `radiusV2.ino`, `audio.h`, `display.h`)
- [x] Add `#define ARTNET_OPCODE_AUDIO_STATUS 0x8302` to `config.h`
- [x] Record sender IP from any incoming Art-Net packet in `radiusV2.ino` (already present: `senderIP` / `senderKnown`)
- [x] In `loop()`, detect `audioCurrentFile()` transitioning from non-empty → empty (natural end of file)
- [x] On that transition, send an `ArtAudioStatus` UDP packet to `senderIP` via `udpReport` on `AUDIO_REPORT_PORT` (6455): status byte (0=stopped, 1=playing), current filename (or empty if stopped)
- [x] Also send `ArtAudioStatus` at end of `handleArtAudioCmd()` for round-trip confirmation on play/stop/cue commands
- [x] TFT display (Screen 2) already updates via the existing 500ms `displayAudioUpdate()` poll — no additional calls needed

### Sender (`artnet.py`, `state.py`)
- [x] Handle `0x8302` in `FpsListener.run()` on port 6455; parse status byte and filename
- [x] Add `get_audio_status(ip)` to `FpsListener`; 30s TTL
- [x] Expose `now_playing` and `audio_status` on each device in the `/api/state` response

### UI (`radius.html`, `audio-panel.js`)
- [x] Add `nowPlaying(di)` to `audioPanel`: reads server `audio_status`/`now_playing` first, falls back to optimistic client state
- [x] `isPlaying()` and `isLooping()` updated to use `nowPlaying()`
- [x] Audio card "now playing" row uses `nowPlaying(dev.di)` — clears automatically when server reports stopped

---

## Battery Status Reporting

Primus LED receiver firmware has no battery status implementation. Radius will be the first to add it.

**Approach: ArtPollReply Node Report string** (least disruptive — no protocol changes, sender already parses this field)

### Firmware (`config.h`, `radiusV2.ino`)
- [ ] `analogRead(A13)` (GPIO35) to read VBAT via onboard voltage divider
- [ ] Voltage math: `(raw / 4095.0) * 3.3 * 2` → battery voltage → map to 0–100% percentage
- [ ] Append `BAT:nn` (integer percent) to the existing `PV3CAP1|...` Node Report string in ArtPollReply

### Sender (`artnet.py`, `state.py`)
- [ ] Parse `BAT:nn` field from Node Report in `artnet.py` capability tag parser
- [ ] Expose `battery_pct` on the device object in `state.py`

### UI (`radius.html`)
- [ ] Display battery percentage in the Radius Central audio device card

---

## Testing

### Variant A
- [ ] Flash `-v3` profile and confirm boot / WiFi / display screens
- [ ] Test headphone output with a WAV file
- [ ] Test volume control (VS1053 only)
- [ ] Test D1 button audio test tone (Screen 2)
- [ ] Test FTP: connect via FTP client, upload a WAV file to SD
- [ ] Test Art-Net cmd 1 (play) and cmd 2 (loop) from sender
- [ ] Test Art-Net cmd 4 (volume)
- [ ] Test Art-Net cmd 6/7 (play/loop cue) via `cues.json` on SD
- [ ] Test FTP toggle via Art-Net cmd 0x8301

### Variant B
- [ ] Flash `-v3` profile and confirm boot / WiFi / display
- [ ] Test speaker output with a WAV file
- [ ] Test Art-Net cmd 4 (volume) — confirm both VS1053 and MAX9744 respond
- [ ] Confirm MAX9744 volume initialises at startup
