# CLAUDE.md - PrimusV3 Agent Context

## What is this project?

PrimusV3 is a WiFi LED lighting controller for live performance costumes. A Python sender drives ESP32 receiver nodes over Art-Net (UDP 6454). The sender has a built-in web UI, clip/look workflow, cue controller, OSC input, firmware upload panel, and effects engine. The current V3.6 track supports reflashed V1, V2, and V3.1 hardware with one shared Art-Net protocol.

## Active version: V5 (PrimusCentral + RadiusCentral + DeviceManager)

**V5 is the canonical sender and packaging track** under `V5/`. It was copied from the complete finalized V4 flexible-device-control tree at `5ca259cb8ec94610d2a41c72f3fd54e3cf425202`. V4 and V3.6 remain historical/source references; do new sender, firmware, packaging, and documentation work in `V5/` unless the user explicitly asks for an older track.

### PrimusCentral (LED clip/look/cue workflow)

- Launch: `python3 V5/sender/run.py --product primus`
- Package: `python3 V5/build_sender_app.py --target macos --product primus --name PrimusCentral`
- Web UI: `V5/sender/web/index-primus.html` (served at `/` or `/primus`)
- State: `V5/sender/` clips, looks, cues, `.primus_state.json`
- Packaged app data: `~/Library/Application Support/PrimusV3/V5/sender/` (macOS) or `%APPDATA%\PrimusV3\V5\sender\` (Windows)
- Firmware: `V5/Arduino/primusV3_receiver/` + `upload.sh` (profiles `-v1`, `-v2`, `-v3`)

### RadiusCentral (audio workflow)

- Launch: `python3 V5/sender/run.py` or `python3 V5/sender/run.py --product radius`
- Package: `python3 V5/build_sender_app.py --target macos --product radius --name RadiusCentral`
- Web UI: `V5/sender/web/index.html` (served at `/radius`)
- State: `V5/sender/radius_state.py` (device, audio, FTP only — no clips/looks/cues)
- App data: `RadiusV3/V5/sender/` (`.radius_state.json`)
- Firmware: `V5/Arduino/radius_receiver/` + `radius_upload.sh` (profile `radius_v1`, HUZZAH32 + Music Maker)
- Radius opcodes: `0x8300` ArtAudioCmd, `0x8301` ArtFtpCmd; shared `0x8200` ArtIPConfig; capability tag `PVRAD1|B:v1|IP:D|F:RA`
- Track telemetry: UDP 6455 magic `PTR` for current filename

### DeviceManager (network monitoring, device config, and firmware app)

DeviceManager is not a separate backend — it is a third frontend served by the same unified server that hosts PrimusCentral, always running against the `primus` product. It exists to give a stage manager a live, monitoring-first view of every receiver on the network, plus device configuration and firmware upload, without the show-control workflow (Look Designer, Cue Controller) getting in the way.

- Launch: `python3 V5/sender/run_devices.py` (attaches to an already-running PrimusCentral/DeviceManager server instead of starting a second one; falls back to starting its own `primus`-product server if none is running) — or `python3 V5/sender/run.py --product primus --frontend devices`.
- Package: `python3 V5/build_sender_app.py --target macos --product devices --name DeviceManager` (bundle id `com.socialbodylab.DeviceManager`).
- Web UI: `V5/sender/web/index-devices.html` + `V5/sender/web/js/app-devices.js` (served at `/devices`). Reuses the same shared `V5/sender/web/js/device-conn.js` store as PrimusCentral/RadiusCentral for all device actions (connect, rename, hello, IP config, output/receive-mode config, groups) — extend that file additively; do not change existing function signatures, since Primus and Radius both depend on them.
- **Monitoring is automatic, not manual.** `app-devices.js` runs a recurring `POST /api/devices/sync` every 20 seconds (`autoSyncNetwork` in `device-conn.js`) to discover reachable devices in the background — there is no user-facing Connect/Disconnect control in this app. Live FPS/battery telemetry comes from the UDP 6455 listener and is already present in `/api/state` for any known device regardless of connect state (connect only gates whether the sender actively drives DMX output to that device, which is irrelevant to monitoring). **Mixed monitoring:** on the `primus` backend, sync also discovers `PVRAD1` Radius nodes alongside Primus receivers. Radius records carry `is_radius: true`, never receive ArtDmx, and show simplified monitor cards. Radius character/performer names persist in `.radius_state.json` via `show_info_store.py`. See `V5/RADIUS_INTEGRATION.md`.
- **`ControllerState.monitor_only`** is the safety mechanism that makes it safe to run DeviceManager on the same network as a show already being driven by another sender or console (e.g. EOS): `_sync_network_devices` in `server.py` skips `connect_all()` entirely when this flag is set, so devices found by the periodic sync above are never auto-connected and the per-frame Art-Net send loop never streams DMX — including idle keepalive frames — to them. `/api/connect` and `/api/connect_all` also return `409` outright in this mode. The flag is set via `--monitor-only`, which `run_devices.py` injects automatically whenever it starts a fresh backend of its own; it is inert (never even reaches `ControllerState`) when DeviceManager instead attaches to an already-running Central server, since that server is the legitimate show control and was constructed without the flag. One-off setup actions (Hello, output type, virtual resolution) still work under `monitor_only` — they open a transient connection just long enough to send that single config packet, then release it, so they never turn into standing DMX output. `GET /api/runtime` reports the current `monitor_only` value so the UI can show a "Monitor Only" indicator.
- **Mobile / Tablet View** lets a phone or tablet on the same network see a live, read-only copy of the Monitor tab (status, battery, FPS, IP/universe, plus the Hello button) by scanning a QR code from Settings > "Mobile / Tablet View" — no internet connection needed on either device. This requires DeviceManager's own fresh backend to bind the HTTP server to the LAN interface instead of loopback-only: `run_devices.py` auto-injects a new `--lan` flag (same pattern as `--monitor-only`) that `run_primus.py` turns into a `0.0.0.0` bind instead of `127.0.0.1`; `GET /api/runtime` reports the resulting `lan_enabled` state so the UI can show the QR code (built client-side from `/api/network/status`'s `source_ip` plus a vendored, dependency-free QR encoder at `V5/sender/web/js/qrcode.js`) or explain why it's unavailable. Like `--monitor-only`, this is inert when DeviceManager attaches to an already-running Central server instead of starting its own (that server stays loopback-only). The mobile view itself (`/devices?mode=mobile`) is a curated UI restriction, not a new auth boundary — firmware/network config endpoints are unaffected, consistent with this project's no-auth-anywhere posture on a trusted local show network.
- Cards are grouped into three status sections — **Attention** (transport error or low/faulted battery), **Online** (`receiver_online`), **Offline / Unconfirmed** — with a summary strip (online/total, low battery, error counts) above the grid. Card field order: Character Name (heading, always editable — shows an "Add…" placeholder when unset rather than falling back to the device name), Performer Name (subheading, same "Add…" placeholder pattern), Device (technical) name (its own row directly under Performer Name, always shown, labeled "Device"), status pill + battery + Hello, IP + universe, Receive Mode, Outputs + virtual resolution, then a simple product tag (`monitorProductLabel()` — "Primus" or "Radius", not the specific hardware/board version) plus firmware version in the footer. Character Name, Performer Name, and Device Name are three independent fields — none of them substitutes for another, so a freshly flashed device with no show info yet still has a visible way to set all three. Each card collapses by default to just the always-visible fields (heading/subheading/device name, status cluster, IP + universe, footer) via the `dm-expand-toggle` chevron in the heading (`isCardExpanded`/`toggleCardExpanded` in `app-devices.js`, keyed by device index like the other per-card UI state) — Receive Mode, Outputs, the static-IP config panel, and Remove only render once a card is expanded, so more devices fit on screen at a glance.
- **Bulk actions** are scoped to an existing device group (create/manage groups from PrimusCentral's own UI; DeviceManager only filters by them): Bulk Rename applies a `{n}`-numbered pattern across the group with a preview before committing; Bulk Apply sets an output type or receive-mode/base-universe (with an optional per-device universe increment) across the group. Both are client-side loops over the existing single-device endpoints (`bulkRenamePreview/Apply`, `bulkApplyOutputType`, `bulkApplyReceiveMode` in `device-conn.js`) — no new backend endpoints. Bulk static IP is intentionally not offered (would cause IP collisions).
- **Firmware** and **Settings** are the second and third top-level tabs (Monitor/Firmware/Settings). Firmware reuses PrimusCentral's existing `firmware.js` component and backend (`firmware.py`, `/api/firmware/*`), laid out as a linear step flow (version/profile → device/port → collapsible overrides → compile/upload → log) instead of PrimusCentral's dense side-by-side grid. DeviceManager enables mixed Primus/Radius upload via `scope=mixed` (family toggle + per-family board profiles; receive-mode overrides only for Primus). Settings reuses PrimusCentral's `settings.js` Alpine component and `/api/network/*` endpoints unchanged — it is a self-contained component with no Primus-specific logic — regrouped into three sections (Network Interface, Sender IP, Advanced) instead of PrimusCentral's flat two-column grid.
- `monitorHardwareLabel(entity)` in `device-conn.js` reports "Unconfirmed hardware" instead of a specific board name when a device's capability `profile` is `pv3cap1-legacy`/`primus-legacy` — those profiles mean the receiver never returned a real board-code capability tag and the backend (`parse_node_capabilities` in `artnet.py`) is guessing V3.1 hardware from a generic "primusv3" name match, which is not reliable for older/legacy firmware on V1 or V2 boards. PrimusCentral's own `hardwareLabel(entity)` is unchanged and still shows the guessed board name.

See `V5/README.md` and `V5/PACKAGING.md` for quick start and release details.

### V3.6 reference track (`V3_6/`)

V3.5, V3.1, and V3.0 remain historical references. The `V3_6/` tree still documents the V3.6 Art-Net protocol and can be run from source (`python3 V3_6/sender/run.py`) for comparison, but **do not build new PrimusCentral releases from `V3_6/build_sender_app.py`** — use V5 with `--product primus` instead.

V3.6 adds sender-side Clip, Look, and Timeline segment brightness. Receiver LED driver brightness stays fixed at 255; the sender scales RGB pixel values before ArtDmx transport. Do not revive the old V2 brightness-byte protocol or receiver `setBrightness()` for show dimming.

V3.6 also adds portable Clip and Look sharing bundles through `sharing.py`: `GET /api/clips/:id/export`, `GET /api/looks/:id/export`, and `POST /api/import_bundle`. Look imports remap Clip IDs and clear saved `device_ips` so shared files do not overwrite local content or target someone else's receiver IPs.

The 0.7 workshop release defaults the browser UI to a workshop profile that hides some output choices and renames the workshop kit: `small_grid` = Badge, `short_strip` = Collar, `extra_long_strip` = Belt, `none` = None. This is UI-only; do not remove output types from sender state, API, or firmware. Full UI can be restored with `?ui=full` or `?profile=full`; return with `?ui=workshop` or `?profile=workshop`. The browser stores the choice in `localStorage` as `primusUiProfile`.

## Repository layout

### V5 Unified Sender (`V5/sender/`) — canonical track

- `run.py` — Entry point for PrimusCentral (`--product primus`), RadiusCentral (`--product radius`), and DeviceManager (`--product primus --frontend devices`, or `run_devices.py`).
- `state.py` — Core runtime state, output tables, animation tick, device tracking, brightness scaling, Art-Net send loop, `/api/performance` diagnostics, and macOS thread QoS helpers.
- `server.py` — HTTP server. Serves static web UI and JSON API endpoints.
- `effects.py`, `clips.py`, `mixer.py`, `controller.py`, `sharing.py` — Primus clip/look/cue workflow.
- `firmware.py`, `network_settings.py`, `osc_control.py`, `artnet.py`, `paths.py` — Shared infrastructure.
- `web/` — Static Alpine.js UI (`index-primus.html`, `index.html`, `index-devices.html`, shared CSS/JS).
- `tests/` — Stdlib unittest coverage.

### V5 Sender Data

- **PrimusCentral source runs:** `V5/sender/clips/`, `looks/`, `cues.json`, `.primus_state.json`
- **PrimusCentral packaged:** `~/Library/Application Support/PrimusV3/V5/sender/` (macOS) or `%APPDATA%\PrimusV3\V5\sender\` (Windows)
- **RadiusCentral packaged:** `~/Library/Application Support/RadiusV3/V5/sender/`

### Receiver Firmware (canonical: `V5/Arduino/`)

- `V5/Arduino/primusV3_receiver/` — Shared Primus firmware with `-v1`, `-v2`, and `-v3` upload profiles.
- `V5/Arduino/upload.sh` — Primus compile/upload script.
- `V5/Arduino/radius_receiver/` + `radius_upload.sh` — Radius audio firmware.
- `V4/Arduino/` and `V3_6/Arduino/` remain historical; new firmware changes should land in `V5/Arduino/`.

### V3.6 Reference Sender (`V3_6/sender/`) — historical/source only

Same module layout as V4 Primus path, but not used for current PrimusCentral releases. Packaged V3.6 app data lived under `PrimusV3/V3_6/sender/`.

### Docs
- `README.md` - Project overview, V5 quick start, packaging marker summary.
- `V5/README.md` - V5 documentation index, PrimusCentral and RadiusCentral quick start.
- `V5/PACKAGING.md` - App packaging, signing, notarization, DMG creation, and packaged FPS validation.
- `API_REFERENCE.md` - Network protocol, HTTP API, sharing endpoints, performance diagnostics, packaging touchpoints.
- `V3_6/README.md` - Historical V3.6 protocol/source reference.
- `V3_6/FIRMWARE_DEVELOPMENT.md` - Firmware profiles, pins, protocol contracts, and validation.
- `V3_6/SENDER_DEVELOPMENT.md` - Sender architecture, discovery metadata, API behavior, and tests.

## Critical sync points

The sender and receiver must agree on:
- **Output type IDs**: `LOOK_OUTPUT_TYPES` list (Python) indices = `OutputType` enum (C++) values.
- **Pixel counts**: `OUTPUT_TYPES` dict (Python, in `state.py`) = `OUTPUT_TYPE_TABLE` (C++).
- **Custom opcode 0x8100**: ArtOutputConfig for runtime output type changes.
- **Custom opcode 0x8110**: ArtReceiveConfig for split/combined universe layout.
- **Custom opcode 0x8130**: ArtVirtualResolution for per-output virtual send pixel counts (firmware 3.11+).
- **Custom opcode 0x8200**: ArtIPConfig for static IP / DHCP configuration.
- **Discovery capability tag**: `PV3CAP1|F:RIOHM|B:<profile>|IP:D|U:S:0|...` in ArtPollReply Node Report (`U:C:N` for combined mode; trailing `...` is the per-output `port:type:universe[:virtual]` tuples, with the optional fourth field being virtual pixel count on firmware 3.11+). Firmware **3.12+** put `F:` (feature flags) right after the `PV3CAP1` prefix instead of last — the Node Report is a hard 64-byte Art-Net field, and with 2 outputs + a 3-digit base universe + combined mode + a static IP the full token set can exceed that, so whatever comes last risks silent truncation. `F:` gates nearly every capability the sender can act on (rename, hello, IP config, output config, receive mode, battery, show info), so losing it is far worse than losing the lower-stakes per-output tuples, which now come last instead.
- **Feature flags**: `R` rename, `H` identify flash, `I` IP config, `O` output config, `M` receive mode config.
- **FPS telemetry**: 7-byte `PFP` packets on UDP 6455.
- **Brightness**: sender-side RGB scaling only; no receiver brightness channel.
- **Virtual resolution**: sender renders at full physical resolution; Art-Net transport uses `virtual_pixels` per output (Badge default 1); receiver upscales to physical LEDs.

## How to run and test

**PrimusCentral (canonical):**

```bash
python3 V5/sender/run.py --product primus
python3 V5/sender/run.py --product primus --port 0
python3 V5/sender/run.py --product primus --no-browser --port 0
python3 -m py_compile V5/sender/*.py
python3 -m unittest discover -s V5/sender/tests
```

**RadiusCentral:**

```bash
python3 V5/sender/run.py --product radius
```

**V3.6 source reference (comparison only):**

```bash
python3 V3_6/sender/run.py
python3 -m unittest discover -s V3_6/sender/tests
```

Firmware (canonical `V5/Arduino/`):

```bash
./V5/Arduino/upload.sh --ports
./V5/Arduino/upload.sh -v1 --compile
./V5/Arduino/upload.sh -v2 --compile
./V5/Arduino/upload.sh -v3 --compile
./V5/Arduino/upload.sh -v3 --auto
./V5/Arduino/upload.sh -v2 --all
./V5/Arduino/upload.sh -v2 -ssid "PrimusRouter" -pw "router-password" --auto
```

Use `--auto` only when exactly one ESP32-like serial port is connected. Use `--all` only when every detected ESP32-like candidate should receive the same board profile. Upload commands compile automatically before flashing.

## Packaging and release marker

Shipped PrimusCentral releases (v0.81+) are built from **V4** with `--product primus`. The v0.65 release is an important packaged macOS performance marker from the earlier V3_6 line. It fixed an FPS drop where source `run.py` and direct binary execution reached about 30 FPS, but a real `.app` LaunchServices/Finder launch dropped to about 15-20 FPS. Future packaged FPS validation must launch the app through Finder or LaunchServices, not by running `PrimusCentral.app/Contents/MacOS/PrimusCentral` directly.

Validated macOS release identity:
- App name: `PrimusCentral.app`
- Bundle ID: `com.socialbodylab.PrimusCentral`
- Developer ID identity: `Developer ID Application: Nicholas Puckett (SAV2V7GXQ5)`
- Notary profile: `PrimusCentral Notary`
- Build output: `V5/dist/macos/PrimusCentral.app`

Build, sign, notarize, staple, and verify the app:

```bash
python3 V5/build_sender_app.py \
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
open -n V5/dist/macos/PrimusCentral.app --args --port 8097
curl -s http://127.0.0.1:8097/api/performance
```

Do not reintroduce the raw Objective-C `objc_msgSend`/`ctypes` app-activity bridge; it previously crashed the packaged app with SIGSEGV. The safe project approach is the `caffeinate` process assertion plus QoS/frame-pacing changes above.

Release DMG method:
- Remove and recreate `V5/build/macos/dmg-staging` from scratch.
- Copy only `V5/dist/macos/PrimusCentral.app` into staging.
- Add `Applications` as a symlink to `/Applications`; do not copy the real `/Applications` folder.
- Create `V5/dist/macos/PrimusCentral-<version>-macOS-arm64.dmg` with `hdiutil create -format UDZO`.
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
- Device-control UI is capability-aware: rename, hello, IP config, output config, receive mode, and virtual send resolution (`Send px`) are enabled from discovery capabilities, with legacy Primus fallback for older firmware.
- Grid layout is always serpentine (even rows left-to-right, odd rows right-to-left).
- RGB color order is always 3 bytes per pixel.
- Custom Art-Net opcodes use the 0x8000+ range.
- Device names are stored in ESP32 NVS via ArtAddress.
- Static IP configuration is stored in ESP32 NVS via custom ArtIPConfig opcode 0x8200. Defaults to DHCP.

## Effects

none, solid, pulse, linear, constrainbow, rainbow, noise, static_noise, sparkle_noise, knight_rider, chase, radial (grid), spiral (grid)

## V3.6 API endpoints

**GET**: `/`, `/api/runtime`, `/api/state`, `/api/performance`, `/api/network/status`, `/api/clips`, `/api/clips/<id>`, `/api/clips/<id>/export`, `/api/looks`, `/api/looks/<id>`, `/api/looks/<id>/export`, `/api/cues`, `/api/integrations/osc`, `/api/firmware/status`, `/api/firmware/jobs/<id>`

**POST (devices)**: `/api/update`, `/api/connect`, `/api/disconnect`, `/api/connect_all`, `/api/disconnect_all`, `/api/discover`, `/api/add_discovered`, `/api/add_manual`, `/api/remove_device`, `/api/rename_node`, `/api/hello_device`, `/api/set_device_ip`, `/api/revert_device_dhcp`, `/api/set_device_output`, `/api/set_device_receive_mode`, `/api/set_device_virtual_resolution`, `/api/set_playback_source`, `/api/device_groups`

**POST (clips/looks/sharing)**: `/api/clip/preview`, `/api/clips/save`, `/api/clips/save_single`, `/api/import_bundle`, `/api/looks/save`, `/api/mixer/frame`, `/api/mixer/preview`, `/api/mixer/update`, `/api/mixer/stop_preview`

**POST (cues/controller/OSC/firmware/network)**: `/api/cues`, `/api/cues/go`, `/api/cues/stop`, `/api/cues/goto`, `/api/controller/activate`, `/api/controller/activate_many`, `/api/controller/deactivate_look`, `/api/controller/blackout`, `/api/integrations/osc`, `/api/firmware/jobs`, `/api/network/preferred_interface`, `/api/network/controller_connection`, `/api/network/ssid_profile`, `/api/network/apply_static_ip`, `/api/network/set_dhcp`

**DELETE**: `/api/clips/<id>`, `/api/looks/<id>`, `/api/device_groups/<id>`

## Hardware

- V1 Huzzah32: direct NeoPixel outputs on GPIO32/GPIO12, LED_BUILTIN WiFi indicator.
- V2 ESP32 Feather: direct NeoPixel outputs on GPIO32/GPIO12, onboard NeoPixel WiFi indicator.
- V3.1 Reverse TFT Feather: NeoPXL8 FeatherWing outputs 6/7 on GPIO14/GPIO15, 240x135 ST7789 TFT, D0/D1 buttons.
- Max 122 LEDs per port, 2 active ports per node.
