# CLAUDE.md - PrimusV3 Agent Context

## What is this project?

PrimusV3 is a WiFi LED lighting controller for live performance costumes. A Python sender drives ESP32 receiver nodes over Art-Net (UDP 6454). The sender has a built-in web UI, clip/look workflow, cue controller, OSC input, firmware upload panel, and effects engine. The current V3.6 track supports reflashed V1, V2, and V3.1 hardware with one shared Art-Net protocol.

## Active version: V3.6

V3.6 is the active compatibility track under `V3_6/`. V3.5, V3.1, and V3.0 remain historical references. Do new sender, firmware, packaging, and documentation work in `V3_6/` unless the user explicitly asks for an older track.

V3.6 adds sender-side Clip, Look, and Timeline segment brightness. Receiver LED driver brightness stays fixed at 255; the sender scales RGB pixel values before ArtDmx transport. Do not revive the old V2 brightness-byte protocol or receiver `setBrightness()` for show dimming.

V3.6 also adds portable Clip and Look sharing bundles through `sharing.py`: `GET /api/clips/:id/export`, `GET /api/looks/:id/export`, and `POST /api/import_bundle`. Look imports remap Clip IDs and clear saved `device_ips` so shared files do not overwrite local content or target someone else's receiver IPs.

The 0.7 workshop release defaults the browser UI to a workshop profile that hides some output choices and renames the workshop kit: `small_grid` = Badge, `short_strip` = Collar, `extra_long_strip` = Belt, `none` = None. This is UI-only; do not remove output types from sender state, API, or firmware. Full UI can be restored with `?ui=full` or `?profile=full`; return with `?ui=workshop` or `?profile=workshop`. The browser stores the choice in `localStorage` as `primusUiProfile`.

## Repository layout

### V3.6 Sender (`V3_6/sender/`)
- `run.py` - Entry point. Starts HTTP server, OSC listener, FPS listener, animation loop, mixer/controller loop, UI lifecycle handling, logging, and macOS low-latency activity.
- `state.py` - Core runtime state, output tables, animation tick, device tracking, brightness scaling, Art-Net send loop, `/api/performance` diagnostics, and macOS thread QoS helpers.
- `server.py` - HTTP server. Serves static web UI and JSON API endpoints.
- `effects.py` - Built-in effects computed into pixel buffers.
- `clips.py` - Clip CRUD and preview computation. Clips stored as JSON in `V3_6/sender/clips/` for source runs or app data for packaged runs.
- `mixer.py` - Look timeline frame computation and crossfades.
- `controller.py` - Cue Controller state and transitions.
- `sharing.py` - Portable Clip/Look import and export bundles.
- `firmware.py` - Firmware tool setup, compile, upload, and job status for the web UI.
- `network_settings.py` - Sender host network route/static-IP Settings support.
- `osc_control.py` - Inbound OSC parser/listener for cue triggers.
- `artnet.py` - Art-Net protocol: ArtPoll, ArtPollReply, ArtDmx, ArtAddress, ArtOutputConfig, ArtIPConfig, FPS telemetry, and capability-tag parsing.
- `paths.py` - Source vs packaged data/tools/log path handling.
- `web/` - Static Alpine.js UI files.
- `tests/` - Stdlib unittest coverage.

### V3.6 Sender Data
- Source runs default to `V3_6/sender/clips/`, `V3_6/sender/looks/`, `V3_6/sender/cues.json`, and `V3_6/sender/.primus_state.json`.
- Packaged macOS runs use `~/Library/Application Support/PrimusV3/V3_6/sender/`.
- Packaged Windows runs use `%APPDATA%\PrimusV3\V3_6\sender\`.
- Runtime logs for bundled apps go to app data `logs/sender.log`.

### Receiver Firmware
- `V3_6/Arduino/primusV3_receiver/` - Shared V3.6 firmware with `-v1`, `-v2`, and `-v3` upload profiles.
  - `config.h` - Source of truth for output types, pins, network defaults, firmware name/version, and capability tag.
  - `primusV3_receiver.ino` - Main sketch: WiFi, Art-Net parsing, output config, IP config, NeoPixel output, FPS telemetry, ArtPollReply.
  - `display.h` - TFT display screens.
  - `buttons.h` - Button input handling.
- `V3_6/Arduino/upload.sh` - arduino-cli build/upload script.

### Docs
- `README.md` - Project overview, active V3.6 quick start, packaging marker summary.
- `API_REFERENCE.md` - Network protocol, HTTP API, sharing endpoints, performance diagnostics, packaging touchpoints.
- `V3_6/README.md` - V3.6 documentation index and quick start.
- `V3_6/FIRMWARE_DEVELOPMENT.md` - Firmware profiles, pins, protocol contracts, and validation.
- `V3_6/SENDER_DEVELOPMENT.md` - Sender architecture, discovery metadata, API behavior, and tests.
- `V3_6/PACKAGING.md` - App packaging, signing, notarization, DMG creation, and packaged FPS validation.

## Audio Receiver Firmware (V3.2 / Radius)

Radius nodes are audio-only ESP32 devices controlled by the V3.6 sender via Art-Net. The active firmware is in `V3_6/Arduino/radiusV2/`; `V3_2/Arduino/radiusV2/` is the historical reference.

- `V3_6/Arduino/radiusV2/` — Active Radius firmware (colocated with V3.6 sender).
  - `config.h` — Adds Music Maker pin config, `ARTNET_OPCODE_AUDIO_CMD 0x8300`, `ARTNET_OPCODE_FTP_CMD 0x8301`.
  - `radiusV2.ino` — Main sketch: WiFi, audio, FTP orchestration.
  - `audio.h` — WAV playback via VS1053 (Music Maker FeatherWing, SPI).
  - `ftp.h` — FTP server. Starts automatically at boot; Art-Net 0x8301 and D1 button can toggle it.
  - `display.h` — Audio and FTP screens.
  - `cues.h` — Loads `/cues.json` from SD at boot (ArduinoJson). Max 64 cues.
- `V3_2/Arduino/radiusV2/` — Historical reference (same code, kept for git history).
- Upload: `cd V3_6/Arduino && ./upload.sh` (uses same upload.sh as LED firmware).

**Radius V1** = HUZZAH32 (no display). **Radius V2** = ESP32-S3 Reverse TFT Feather (240x135 TFT). Both use the Music Maker FeatherWing (VS1053) and the same `radiusV2` firmware via `TARGET_BOARD` compile-time switch.

**WAV format**: RIFF PCM WAV, 16-bit, 44100 Hz. Convert with: `afconvert -f WAVE -d LEI16@44100 input.aif output.wav`

**Audio commands (0x8300)**: cmd 0=stop, 1=play, 2=loop, 3=pause, 4=volume, 5=test tone, 6=play cue, 7=loop cue. Cmd 6/7 resolve via `/cues.json` on the SD card (max 64 cues). Values: plain filename string or `{"file": "x.wav", "duration": 30}`.

**FTP control (0x8301)**: cmd 0=stop FTP server, 1=start FTP server.

**SD bus mutex** (`sdBusy`): set true during playback; FTP stalls (not fails) until audio finishes.

**Radius Central**: Audio-only SPA at `/radius` (`V3_6/sender/web/radius.html`). Sidebar shows only `is_audio` devices. Tabs: Audio, Audio Cues, Cue Map, Net Log. Run with `python3 V3_6/sender/run.py --mode radius`.

## Critical sync points

The sender and receiver must agree on:
- **Output type IDs**: `LOOK_OUTPUT_TYPES` list (Python) indices = `OutputType` enum (C++) values.
- **Pixel counts**: `OUTPUT_TYPES` dict (Python, in `state.py`) = `OUTPUT_TYPE_TABLE` (C++).
- **Custom opcode 0x8100**: ArtOutputConfig for runtime output type changes.
- **Custom opcode 0x8200**: ArtIPConfig for static IP / DHCP configuration (V3.x LED nodes).
- **Custom opcode 0x8300**: ArtAudioCmd for Radius audio control (V3.2 Radius nodes only).
- **Custom opcode 0x8301**: ArtFtpCmd for Radius FTP server toggle (V3.2 Radius nodes only).
- **Discovery capability tag**: `PV3CAP1|...|B:<profile>|IP:D|F:RIOH` in ArtPollReply Node Report.
- **Feature flags**: `R` rename, `H` identify flash, `I` IP config, `O` output config.
- **FPS telemetry**: 7-byte `PFP` packets on UDP 6455.
- **Brightness**: sender-side RGB scaling only; no receiver brightness channel.

## How to run and test

```bash
python3 V3_6/sender/run.py                        # Primus Central (LED + audio)
python3 V3_6/sender/run.py --mode radius           # Radius Central (audio-only)
python3 V3_6/sender/run.py --port 0
python3 V3_6/sender/run.py --no-browser --port 0
python3 -m py_compile V3_6/sender/*.py
python3 -m unittest discover -s V3_6/sender/tests
```

Firmware:

```bash
./V3_6/Arduino/upload.sh --ports
./V3_6/Arduino/upload.sh -v1 --compile
./V3_6/Arduino/upload.sh -v2 --compile
./V3_6/Arduino/upload.sh -v3 --compile
./V3_6/Arduino/upload.sh -v3 --auto
./V3_6/Arduino/upload.sh -v2 --all
./V3_6/Arduino/upload.sh -v2 -ssid "PrimusRouter" -pw "router-password" --auto
```

Use `--auto` only when exactly one ESP32-like serial port is connected. Use `--all` only when every detected ESP32-like candidate should receive the same board profile. Upload commands compile automatically before flashing.

## Packaging and release marker: v0.65

The v0.65 release is an important packaged macOS performance marker. It fixed an FPS drop where source `run.py` and direct binary execution reached about 30 FPS, but a real `.app` LaunchServices/Finder launch dropped to about 15-20 FPS. Future packaged FPS validation must launch the app through Finder or LaunchServices, not by running `PrimusCentral.app/Contents/MacOS/PrimusCentral` directly.

Validated macOS release identity:
- App name: `PrimusCentral.app`
- Bundle ID: `com.socialbodylab.PrimusCentral`
- Developer ID identity: `Developer ID Application: Nicholas Puckett (SAV2V7GXQ5)`
- Notary profile: `PrimusCentral Notary`
- Build output: `V3_6/dist/macos/PrimusCentral.app`

Build, sign, notarize, staple, and verify the app:

```bash
python3 V3_6/build_sender_app.py \
  --target macos \
  --sign-identity "Developer ID Application: Nicholas Puckett (SAV2V7GXQ5)" \
  --notary-profile "PrimusCentral Notary" \
  --notary-timeout 1h
```

Equivalent build-time environment overrides:
- `PRIMUSV3_CODESIGN_IDENTITY`
- `PRIMUSV3_NOTARY_PROFILE`
- `PRIMUSV3_NOTARY_TIMEOUT`

Runtime/path overrides:
- `PRIMUSV3_DATA_DIR` - force writable sender data directory.
- `PRIMUSV3_USE_APP_DATA=1` - use platform app data while running from source.
- `PRIMUSV3_TOOLS_DIR` - force firmware tools directory.
- `PRIMUSV3_DISABLE_MACOS_ACTIVITY=1` - disable only the macOS `caffeinate` activity assertion for diagnostics.

Packaged macOS timing methods that must be preserved:
- `run.py` starts `caffeinate -dimsu -w <pid>` so the app has a process-scoped activity assertion.
- `state.py` sets animation and mixer/controller threads to user-interactive QoS using `pthread_set_qos_class_self_np` on Darwin.
- `state.py` uses low-latency frame pacing with short sleep slices and a spin tail.
- `/api/performance` reports rolling timings, counters, and cumulative rates for validation.

Use this LaunchServices validation path for packaged FPS:

```bash
open -n V3_6/dist/macos/PrimusCentral.app --args --port 8097
curl -s http://127.0.0.1:8097/api/performance
```

Do not reintroduce the raw Objective-C `objc_msgSend`/`ctypes` app-activity bridge; it previously crashed the packaged app with SIGSEGV. The safe project approach is the `caffeinate` process assertion plus QoS/frame-pacing changes above.

Release DMG method:
- Remove and recreate `V3_6/build/macos/dmg-staging` from scratch.
- Copy only `V3_6/dist/macos/PrimusCentral.app` into staging.
- Add `Applications` as a symlink to `/Applications`; do not copy the real `/Applications` folder.
- Create `V3_6/dist/macos/PrimusCentral-<version>-macOS-arm64.dmg` with `hdiutil create -format UDZO`.
- Sign the DMG, submit it to Apple notary, staple it, validate it, and run `hdiutil verify`.
- Generate the `.sha256` file after the final stapling step.
- GitHub release assets should be the DMG and matching `.dmg.sha256` file.

## Runtime diagnostics

`GET /api/performance` returns:
- `uptime_seconds`
- `samples` with `count`, `last`, `avg`, and `max`
- `counters`
- `rates_per_second`

Useful samples include `animation_tick_ms`, `animation_sleep_requested_ms`, `animation_sleep_latency_ms`, `tick_lock_wait_ms`, `tick_lock_held_ms`, `tick_send_batch_ms`, `tick_send_packets`, `tick_total_ms`, and `artnet_send_ms`. Useful counters include `animation_frames`, `animation_frame_overruns`, `artnet_packets`, `artnet_frames_with_packets`, `animation_thread_qos_enabled`, and `mixer_controller_thread_qos_enabled`.

Cumulative rates include startup/browser/restore time, so calculate steady-state FPS from counter deltas after launch has settled or use receiver FPS telemetry.

## V3.6 concepts

- **Clip**: A saved effect configuration for one output type. Stores effect parameters and normalized brightness.
- **Look**: Timeline tracks and segments combining Clips across two output slots. Stores master brightness.
- **Cue**: Production trigger that can fire one or more Looks or a blackout assignment.
- **Playback sources**: `designer`, `mixer`, `controller`, and `idle`.
- **Output types**: `none`, `short_strip` (30 px), `long_strip` (72 px), `grid` (8x8 / 64 px), `small_grid` (8x4 / 32 px), `extra_long_strip` (122 px).

## Conventions

- No external Python runtime dependencies in the sender.
- V3.6 web UI is static files under `V3_6/sender/web/` (Alpine.js, no build step).
- 0.7 workshop focus belongs in browser UI profiles, not firmware/protocol tables.
- Keep output types table-driven on both sender and firmware sides.
- Device-control UI is capability-aware: rename, hello, IP config, and output config are enabled from discovery capabilities, with legacy Primus fallback for older firmware.
- Grid layout is always serpentine (even rows left-to-right, odd rows right-to-left).
- RGB color order is always 3 bytes per pixel.
- Custom Art-Net opcodes use the 0x8000+ range.
- Device names are stored in ESP32 NVS via ArtAddress.
- Static IP configuration is stored in ESP32 NVS via custom ArtIPConfig opcode 0x8200. Defaults to DHCP.

## Effects

none, solid, pulse, linear, constrainbow, rainbow, noise, static_noise, sparkle_noise, knight_rider, chase, radial (grid), spiral (grid)

## V3.6 API endpoints

**GET**: `/`, `/api/runtime`, `/api/state`, `/api/performance`, `/api/network/status`, `/api/clips`, `/api/clips/<id>`, `/api/clips/<id>/export`, `/api/looks`, `/api/looks/<id>`, `/api/looks/<id>/export`, `/api/cues`, `/api/integrations/osc`, `/api/firmware/status`, `/api/firmware/jobs/<id>`

**POST (devices)**: `/api/update`, `/api/connect`, `/api/disconnect`, `/api/connect_all`, `/api/disconnect_all`, `/api/discover`, `/api/add_discovered`, `/api/add_manual`, `/api/remove_device`, `/api/rename_node`, `/api/hello_device`, `/api/set_device_ip`, `/api/revert_device_dhcp`, `/api/set_playback_source`, `/api/device_groups`

**POST (clips/looks/sharing)**: `/api/clip/preview`, `/api/clips/save`, `/api/clips/save_single`, `/api/import_bundle`, `/api/looks/save`, `/api/mixer/frame`, `/api/mixer/preview`, `/api/mixer/update`, `/api/mixer/stop_preview`

**POST (cues/controller/OSC/firmware/network)**: `/api/cues`, `/api/cues/go`, `/api/cues/stop`, `/api/cues/goto`, `/api/controller/activate`, `/api/controller/activate_many`, `/api/controller/deactivate_look`, `/api/controller/blackout`, `/api/integrations/osc`, `/api/firmware/jobs`, `/api/network/preferred_interface`, `/api/network/controller_connection`, `/api/network/ssid_profile`, `/api/network/apply_static_ip`, `/api/network/set_dhcp`

**DELETE**: `/api/clips/<id>`, `/api/looks/<id>`, `/api/device_groups/<id>`

## Hardware

- V1 Huzzah32: direct NeoPixel outputs on GPIO32/GPIO12, LED_BUILTIN WiFi indicator.
- V2 ESP32 Feather: direct NeoPixel outputs on GPIO32/GPIO12, onboard NeoPixel WiFi indicator.
- V3.1 Reverse TFT Feather: NeoPXL8 FeatherWing outputs 6/7 on GPIO14/GPIO15, 240x135 ST7789 TFT, D0/D1 buttons.
- Max 122 LEDs per port, 2 active ports per node.
