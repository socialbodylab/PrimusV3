# CLAUDE.md - PrimusV3 Agent Context

## What is this project?

PrimusV3 is a WiFi LED lighting controller for live performance costumes. A Python sender drives ESP32 receiver nodes over Art-Net (UDP 6454). The sender has a built-in web UI, clip/look workflow, cue controller, OSC input, firmware upload panel, and effects engine. The current V3.6 track supports reflashed V1, V2, and V3.1 hardware with one shared Art-Net protocol.

## Active version: V4 (PrimusCentral + RadiusCentral)

**V4 is the canonical sender and packaging track** under `V4/`. Shipped PrimusCentral releases (v0.81–v0.86+) are built from here with `--product primus`. V3.6 under `V3_6/` remains a historical/source reference for the V3.6 protocol line; do new PrimusCentral sender, firmware, packaging, and documentation work in `V4/` unless the user explicitly asks for an older track.

### PrimusCentral (LED clip/look/cue workflow)

- Launch: `python3 V4/sender/run.py --product primus`
- Package: `python3 V4/build_sender_app.py --target macos --product primus --name PrimusCentral`
- Web UI: `V4/sender/web/index-primus.html` (served at `/` or `/primus`)
- State: `V4/sender/` clips, looks, cues, `.primus_state.json`
- Packaged app data: `~/Library/Application Support/PrimusV3/V4/sender/` (macOS) or `%APPDATA%\PrimusV3\V4\sender\` (Windows)
- Firmware: `V4/Arduino/primusV3_receiver/` + `upload.sh` (profiles `-v1`, `-v2`, `-v3`)

### RadiusCentral (audio workflow)

- Launch: `python3 V4/sender/run.py` or `python3 V4/sender/run.py --product radius`
- Package: `python3 V4/build_sender_app.py --target macos --product radius --name RadiusCentral`
- Web UI: `V4/sender/web/index.html` (served at `/radius`)
- State: `V4/sender/radius_state.py` (device, audio, FTP only — no clips/looks/cues)
- App data: `RadiusV3/V4/sender/` (`.radius_state.json`)
- Firmware: `V4/Arduino/radius_receiver/` + `radius_upload.sh` (profile `radius_v1`, HUZZAH32 + Music Maker)
- Radius opcodes: `0x8300` ArtAudioCmd, `0x8301` ArtFtpCmd; shared `0x8200` ArtIPConfig; capability tag `PVRAD1|B:v1|IP:D|F:RA`
- Track telemetry: UDP 6455 magic `PTR` for current filename

See `V4/README.md` and `V4/PACKAGING.md` for quick start and release details.

### V3.6 reference track (`V3_6/`)

V3.5, V3.1, and V3.0 remain historical references. The `V3_6/` tree still documents the V3.6 Art-Net protocol and can be run from source (`python3 V3_6/sender/run.py`) for comparison, but **do not build new PrimusCentral releases from `V3_6/build_sender_app.py`** — use V4 with `--product primus` instead.

V3.6 adds sender-side Clip, Look, and Timeline segment brightness. Receiver LED driver brightness stays fixed at 255; the sender scales RGB pixel values before ArtDmx transport. Do not revive the old V2 brightness-byte protocol or receiver `setBrightness()` for show dimming.

V3.6 also adds portable Clip and Look sharing bundles through `sharing.py`: `GET /api/clips/:id/export`, `GET /api/looks/:id/export`, and `POST /api/import_bundle`. Look imports remap Clip IDs and clear saved `device_ips` so shared files do not overwrite local content or target someone else's receiver IPs.

The 0.7 workshop release defaults the browser UI to a workshop profile that hides some output choices and renames the workshop kit: `small_grid` = Badge, `short_strip` = Collar, `extra_long_strip` = Belt, `none` = None. This is UI-only; do not remove output types from sender state, API, or firmware. Full UI can be restored with `?ui=full` or `?profile=full`; return with `?ui=workshop` or `?profile=workshop`. The browser stores the choice in `localStorage` as `primusUiProfile`.

## Repository layout

### V4 Unified Sender (`V4/sender/`) — canonical track

- `run.py` — Entry point for PrimusCentral (`--product primus`) and RadiusCentral (`--product radius`).
- `state.py` — Core runtime state, output tables, animation tick, device tracking, brightness scaling, Art-Net send loop, `/api/performance` diagnostics, and macOS thread QoS helpers.
- `server.py` — HTTP server. Serves static web UI and JSON API endpoints.
- `effects.py`, `clips.py`, `mixer.py`, `controller.py`, `sharing.py` — Primus clip/look/cue workflow.
- `firmware.py`, `network_settings.py`, `osc_control.py`, `artnet.py`, `paths.py` — Shared infrastructure.
- `web/` — Static Alpine.js UI (`index-primus.html`, `index.html`, shared CSS/JS).
- `tests/` — Stdlib unittest coverage.

### V4 Sender Data

- **PrimusCentral source runs:** `V4/sender/clips/`, `looks/`, `cues.json`, `.primus_state.json`
- **PrimusCentral packaged:** `~/Library/Application Support/PrimusV3/V4/sender/` (macOS) or `%APPDATA%\PrimusV3\V4\sender\` (Windows)
- **RadiusCentral packaged:** `~/Library/Application Support/RadiusV3/V4/sender/`

### Receiver Firmware (canonical: `V4/Arduino/`)

- `V4/Arduino/primusV3_receiver/` — Shared V3.6 Primus firmware with `-v1`, `-v2`, and `-v3` upload profiles.
- `V4/Arduino/upload.sh` — Primus compile/upload script.
- `V4/Arduino/radius_receiver/` + `radius_upload.sh` — Radius audio firmware.
- `V3_6/Arduino/` retains copies for the historical V3.6 release line; new firmware changes should land in `V4/Arduino/`.

### V3.6 Reference Sender (`V3_6/sender/`) — historical/source only

Same module layout as V4 Primus path, but not used for current PrimusCentral releases. Packaged V3.6 app data lived under `PrimusV3/V3_6/sender/`.

### Docs
- `README.md` - Project overview, V4 quick start, packaging marker summary.
- `V4/README.md` - V4 documentation index, PrimusCentral and RadiusCentral quick start.
- `V4/PACKAGING.md` - App packaging, signing, notarization, DMG creation, and packaged FPS validation.
- `API_REFERENCE.md` - Network protocol, HTTP API, sharing endpoints, performance diagnostics, packaging touchpoints.
- `V3_6/README.md` - Historical V3.6 protocol/source reference.
- `V3_6/FIRMWARE_DEVELOPMENT.md` - Firmware profiles, pins, protocol contracts, and validation.
- `V3_6/SENDER_DEVELOPMENT.md` - Sender architecture, discovery metadata, API behavior, and tests.

## Critical sync points

The sender and receiver must agree on:
- **Output type IDs**: `LOOK_OUTPUT_TYPES` list (Python) indices = `OutputType` enum (C++) values.
- **Pixel counts**: `OUTPUT_TYPES` dict (Python, in `state.py`) = `OUTPUT_TYPE_TABLE` (C++).
- **Custom opcode 0x8100**: ArtOutputConfig for runtime output type changes.
- **Custom opcode 0x8200**: ArtIPConfig for static IP / DHCP configuration.
- **Discovery capability tag**: `PV3CAP1|...|B:<profile>|IP:D|F:RIOH` in ArtPollReply Node Report.
- **Feature flags**: `R` rename, `H` identify flash, `I` IP config, `O` output config.
- **FPS telemetry**: 7-byte `PFP` packets on UDP 6455.
- **Brightness**: sender-side RGB scaling only; no receiver brightness channel.

## How to run and test

**PrimusCentral (canonical):**

```bash
python3 V4/sender/run.py --product primus
python3 V4/sender/run.py --product primus --port 0
python3 V4/sender/run.py --product primus --no-browser --port 0
python3 -m py_compile V4/sender/*.py
python3 -m unittest discover -s V4/sender/tests
```

**RadiusCentral:**

```bash
python3 V4/sender/run.py --product radius
```

**V3.6 source reference (comparison only):**

```bash
python3 V3_6/sender/run.py
python3 -m unittest discover -s V3_6/sender/tests
```

Firmware (canonical `V4/Arduino/`):

```bash
./V4/Arduino/upload.sh --ports
./V4/Arduino/upload.sh -v1 --compile
./V4/Arduino/upload.sh -v2 --compile
./V4/Arduino/upload.sh -v3 --compile
./V4/Arduino/upload.sh -v3 --auto
./V4/Arduino/upload.sh -v2 --all
./V4/Arduino/upload.sh -v2 -ssid "PrimusRouter" -pw "router-password" --auto
```

Use `--auto` only when exactly one ESP32-like serial port is connected. Use `--all` only when every detected ESP32-like candidate should receive the same board profile. Upload commands compile automatically before flashing.

## Packaging and release marker

Shipped PrimusCentral releases (v0.81+) are built from **V4** with `--product primus`. The v0.65 release is an important packaged macOS performance marker from the earlier V3_6 line. It fixed an FPS drop where source `run.py` and direct binary execution reached about 30 FPS, but a real `.app` LaunchServices/Finder launch dropped to about 15-20 FPS. Future packaged FPS validation must launch the app through Finder or LaunchServices, not by running `PrimusCentral.app/Contents/MacOS/PrimusCentral` directly.

Validated macOS release identity:
- App name: `PrimusCentral.app`
- Bundle ID: `com.socialbodylab.PrimusCentral`
- Developer ID identity: `Developer ID Application: Nicholas Puckett (SAV2V7GXQ5)`
- Notary profile: `PrimusCentral Notary`
- Build output: `V4/dist/macos/PrimusCentral.app`

Build, sign, notarize, staple, and verify the app:

```bash
python3 V4/build_sender_app.py \
  --target macos \
  --product primus \
  --name PrimusCentral \
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
open -n V4/dist/macos/PrimusCentral.app --args --port 8097
curl -s http://127.0.0.1:8097/api/performance
```

Do not reintroduce the raw Objective-C `objc_msgSend`/`ctypes` app-activity bridge; it previously crashed the packaged app with SIGSEGV. The safe project approach is the `caffeinate` process assertion plus QoS/frame-pacing changes above.

Release DMG method:
- Remove and recreate `V4/build/macos/dmg-staging` from scratch.
- Copy only `V4/dist/macos/PrimusCentral.app` into staging.
- Add `Applications` as a symlink to `/Applications`; do not copy the real `/Applications` folder.
- Create `V4/dist/macos/PrimusCentral-<version>-macOS-arm64.dmg` with `hdiutil create -format UDZO`.
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
