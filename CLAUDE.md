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
- **RadiusCentral runs on the unified backend.** `run.py --product radius` flips the process to the `primus` product with default frontend `/radius` and delegates to `run_primus.main()` (same launcher pattern as DeviceManager). One server process hosts all three frontends, holds one device list (`ControllerState`, with `is_radius` records), and owns the single Watch-lane listener on 6455. `PRIMUSV3_RADIUS_STANDALONE=1` is the escape hatch back to the legacy separate `RadiusState` backend (kept for tests and fallback).
- `ControllerState` carries the full lane-aware Radius audio/FTP surface (`send_audio_command`, `ftp_*`, `fire_audio_cue`, `radius_has_live_playback`), so every audio route works on the shared server. `GET /api/state?product=radius` returns the radius-shaped view via `ControllerState.get_radius_json()` — ALL devices, indices aligned with the unified list; the UI filters on `is_radius`.
- Package: `python3 V5/build_sender_app.py --target macos --product radius --name RadiusCentral`
- Web UI: `V5/sender/web/index.html` (served at `/radius`); shows a blocking banner if the backend does not answer with the radius shape.
- App data: unified under `PrimusV3/V5/sender/` — on first launch `run.py` copies legacy `RadiusV3/V5/sender/` data (`.radius_state.json`, `audio_cues.json`, `audio/`) across, and `ControllerState.restore_devices()` imports device lists saved by the old standalone backend.
- Firmware: `V5/Arduino/radius_receiver/` + `radius_upload.sh` (profiles `radius_v1` HUZZAH32 + Music Maker, `radius_v2` S3 ReverseTFT). Firmware **4.20** is canonical: features `RIHASB`, Node Report `F:` first with whole-token guard, `build_opt.h` disables unused NimBLE roles to fit flash (do not delete it). Ledger: 4.17 pause holds position (`playback_state=2`; 4.16's pause self-restarted loops), 4.18 filenames 32→64 chars everywhere, 4.19 volume-cache invalidation when muting behind it (fixed silent sequential playback), 4.20 decoder soft-reset on explicit stop/track-switch (fixed slow playback). Volume byte maps onto the codec's full 127 dB attenuation — usable range ~50–100; UIs clamp.
- Radius opcodes: `0x8300` ArtAudioCmd, `0x8301` ArtFtpCmd, `0x8220` ArtLanePorts; shared `0x8200` ArtIPConfig, `0x8210` ArtShowInfo; capability tag `PVRAD1|B:v1|F:RIHASB|IP:D|V:4.20`
- Telemetry on UDP 6455: `PTR` (current filename + playback state, byte-frozen) and, firmware 4.16+, the 17-byte `PRS` status packet (sequence, uptime, flags incl. SD/FTP/playing/Marius, RSSI, battery from the HUZZAH32 A13 VBAT/2 divider — one ADC sample/s with EMA, never blocking the VS1053 feed). `PrimusTelemetryListener` demuxes PST/PBT/PFP/PTR/PRS; exact byte layouts in `V5/FIRMWARE_REFERENCE.md`.

**Launcher contract (all three apps).** There is one backend process; the apps are launchers onto its frontends. Before attaching, a launcher must answer three questions, and `central_launcher.evaluate_server()` is where that happens: is a Central running, can it serve *my product*, and can it serve *my capabilities* (drive output). A mismatch must never silently attach — packaged apps are windowed with no console, so a silent decision is indistinguishable from a failed launch. Key pieces:

- `launcher_dialog.py` — stdlib-only native dialogs (`osascript` on macOS, `MessageBoxW` on Windows, print+default fallback). Set `PRIMUSV3_NO_DIALOGS=1` to force the non-blocking fallback in scripts and CI.
- `try_attach_before_start(..., need_product=, needs_output=, on_mismatch=)` — the handler returns `"attach"`, `"start"`, or `"abort"`. With no handler the default is to refuse, not attach.
- PrimusCentral still offers **Restart in full mode / Open read-only / Cancel** when it finds a `monitor_only` backend — but only legacy packaged servers register that flag now (see the passive-sync note below); against current servers the dialog never appears.
- RadiusCentral needs a backend whose `products` include `radius`; the unified backend qualifies, an old primus-only server does not.
- Attach calls `reserve_ui_session()` so the running Central counts the new client before its browser exists and cannot auto-quit in that gap.
- The registry (`central_server.json`) records capabilities — `monitor_only`, `lan_enabled`, `app_version`, and `products` (the unified backend registers `["primus", "radius"]`) — not just host/port. `/api/runtime` and `/api/server/status` advertise the same `products` list; `evaluate_server()` accepts when `need_product` is in it, and treats a backend with no product information as a loud mismatch (`MISMATCH_UNKNOWN_PRODUCT`).
- Both the auto-shutdown monitor and `POST /api/server/stop` read the same `server.live_output_fn`, so they can never disagree about whether quitting is safe. The unified predicate is composed: `playback_source` (Primus show output) OR `ControllerState.radius_has_live_playback()` (any Radius device reporting playback via PTR) — failing toward "live" on error.
- Operator control: `python3 V5/sender/run.py --server-status` and `--stop-server [--force]`. This is the supported way to clear an orphaned server holding the port.

**RESOLVED (2026-08-12) — RadiusCentral now shares the one backend.** The former limitation (RadiusCentral silently attaching to a Primus backend; two processes fighting over UDP 6455) was removed by making RadiusCentral a **third frontend on the unified backend**, exactly like DeviceManager:

- One process, one device list: `ControllerState` models Radius devices (`is_radius` records, never given an `ArtNetSender`) and carries the full audio/FTP command surface, so `/radius` and every `/api/audio/*` route are served correctly from the shared server. `RadiusState` remains only for the `PRIMUSV3_RADIUS_STANDALONE=1` escape hatch and its tests.
- One 6455 listener: `PrimusTelemetryListener` demuxes all magics (`PST`/`PBT`/`PFP` Primus, `PTR`/`PRS` Radius). The port conflict is gone by construction.
- Loud launcher: `evaluate_server()` checks the backend's `products` list; a backend that cannot serve the requested product (or will not say what it serves) produces a dialog offering **Restart shared server / Cancel** — never a silent attach. The Radius UI additionally verifies `/api/state?product=radius` answers with `product: "radius"` and shows a blocking banner otherwise.
- The Radius frontend addresses devices by the same indices as the other frontends (`get_radius_json()` returns all devices, radius-shaped), so `{device: di}` API calls mean the same thing in every app.

### DeviceManager (network monitoring, device config, and firmware app)

DeviceManager is not a separate backend — it is a third frontend served by the same unified server that hosts PrimusCentral, always running against the `primus` product. It exists to give a stage manager a live, monitoring-first view of every receiver on the network, plus device configuration and firmware upload, without the show-control workflow (Look Designer, Cue Controller) getting in the way.

- Launch: `python3 V5/sender/run_devices.py` (attaches to an already-running PrimusCentral/DeviceManager server instead of starting a second one; falls back to starting its own `primus`-product server if none is running) — or `python3 V5/sender/run.py --product primus --frontend devices`.
- Package: `python3 V5/build_sender_app.py --target macos --product devices --name DeviceManager` (bundle id `com.socialbodylab.DeviceManager`).
- Web UI: `V5/sender/web/index-devices.html` + `V5/sender/web/js/app-devices.js` (served at `/devices`). Reuses the same shared `V5/sender/web/js/device-conn.js` store as PrimusCentral/RadiusCentral for all device actions (connect, rename, hello, IP config, output/receive-mode config, groups) — extend that file additively; do not change existing function signatures, since Primus and Radius both depend on them.
- **Monitoring is automatic, not manual.** `app-devices.js` runs a recurring `POST /api/devices/sync` every 20 seconds (`autoSyncNetwork` in `device-conn.js`) to discover reachable devices in the background — there is no user-facing Connect/Disconnect control in this app. Live FPS/battery telemetry comes from the UDP 6455 listener and is already present in `/api/state` for any known device regardless of connect state (connect only gates whether the sender actively drives DMX output to that device, which is irrelevant to monitoring). **Mixed monitoring:** on the `primus` backend, sync also discovers `PVRAD1` Radius nodes alongside Primus receivers. Radius records carry `is_radius: true`, never receive ArtDmx, and show simplified monitor cards. Radius character/performer names persist in `.radius_state.json` via `show_info_store.py`. See `V5/RADIUS_INTEGRATION.md`.
- **Monitoring is passive by construction — there is no monitor-only mode anymore (2026-08-12).** `_sync_network_devices` in `server.py` never calls `connect_all()` for any backend: sync is discovery + refresh only. Connecting is what arms DMX to a device (the tick then streams frames including keepalive blackouts, which would fight an external console like EOS or TouchDesigner — the production color source), so it is always an explicit operator action (`/api/connect`, Connect All in PrimusCentral, used for tests/demos). This one invariant replaced the old `ControllerState.monitor_only` mode and its restart-in-full-mode launcher choreography: every backend behaves identically no matter which app started it, so all three apps coexist with external control data by default. The `--monitor-only` CLI flag and its 409s on `/api/connect` remain accepted for scripts/back-compat, but `run_devices.py` no longer injects it and nothing in the suite depends on it. One-off setup actions (Hello, output type, virtual resolution) use transient connections as before and never turn into standing DMX output.
- **Mobile / Tablet View** lets a phone or tablet on the same network see a live, read-only copy of the Monitor tab (status, battery, FPS, IP/universe, plus the Hello button) by scanning a QR code from Settings > "Mobile / Tablet View" — no internet connection needed on either device. This requires DeviceManager's own fresh backend to bind the HTTP server to the LAN interface instead of loopback-only: `run_devices.py` auto-injects a new `--lan` flag (same pattern as `--monitor-only`) that `run_primus.py` turns into a `0.0.0.0` bind instead of `127.0.0.1`; `GET /api/runtime` reports the resulting `lan_enabled` state so the UI can show the QR code (built client-side from `/api/network/status`'s `source_ip` plus a vendored, dependency-free QR encoder at `V5/sender/web/js/qrcode.js`) or explain why it's unavailable. Like `--monitor-only`, this is inert when DeviceManager attaches to an already-running Central server instead of starting its own (that server stays loopback-only). The mobile view itself (`/devices?mode=mobile`) is a curated UI restriction, not a new auth boundary — firmware/network config endpoints are unaffected, consistent with this project's no-auth-anywhere posture on a trusted local show network.
- **Monitor is grouped by performer, not by product or status.** Most performers wear both a Primus and a Radius device; each performer gets a heading (name, character label, device count, worst-status rollup pill, Edit identity button) with their devices side by side — Primus first, then Radius. Devices without a performer name live in a separate **Unassigned** section (assigning a performer via the card's inline edit moves them into their group — the one re-sort that is intended feedback). **Position is stable by construction:** ordering uses only performer name (localeCompare), product role, and a stable device key (`device_uid` from the ArtPollReply MAC, falling back to IP) — battery level, `receiver_online` flapping, transport errors, and sync order can never reorder cards. Status is expressed in place: per-card status pill, left-border tint (`.dm-card-attention/-online/-offline`), the heading rollup, the summary strip, and an "Attention only" filter toggle. The performer-level **Edit identity** panel writes Character + Performer to all of that performer's devices in one save (one `POST /api/device_show_info` per device, with datalists of existing names; sort frozen while open). Card field order within a card is unchanged: Character Name (heading, "Add…" placeholder), Performer Name (subheading), Device name row, status cluster, IP + universe, then expand-gated Receive Mode / Outputs / IP config / Remove via the `dm-expand-toggle` chevron (expand state keyed by the stable device key and reconciled every state fetch, not by array index).
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
- `V5/README.md` - **The documentation index.** Start here.
- `V5/CHANGES.md` - The 2026-08 unification milestone: what changed, why, and the honest still-needs-work list.
- `V5/ARCHITECTURE.md` - Unified backend as implemented (process model, tick, telemetry, launcher contract, lifecycle, persistence).
- `V5/API_REFERENCE.md` - **Canonical HTTP API** (all routes) + Art-Net integration guide + custom-opcode wire formats. Root `API_REFERENCE.md` is just a pointer now.
- `V5/PORTS_AND_LANES.md` - UDP lane model as implemented (Show/Setup/Watch, `L` flag, dual-listen state, recovery).
- `V5/FIRMWARE_REFERENCE.md` - Receiver firmware behavior, telemetry byte layouts, capability tags (both families).
- `V5/PRIMUS_FIRMWARE_MAP.md` - Primus firmware internals map.
- `V5/RADIUS_INTEGRATION.md` - Mixed Primus/Radius monitoring and show identity.
- `V5/PACKAGING.md` - App packaging, signing, notarization, DMG creation, and packaged FPS validation.
- `docs/archive/`, `V5/docs/archive/` - Historical handoffs, audits, and planning snapshots. Not authoritative.
- `V3_6/README.md`, `V3_6/FIRMWARE_DEVELOPMENT.md`, `V3_6/SENDER_DEVELOPMENT.md` - Historical V3.6 track reference.

## Critical sync points

The sender and receiver must agree on:
- **Output type IDs**: `LOOK_OUTPUT_TYPES` list (Python) indices = `OutputType` enum (C++) values.
- **Pixel counts**: `OUTPUT_TYPES` dict (Python, in `state.py`) = `OUTPUT_TYPE_TABLE` (C++).
- **Custom opcode 0x8100**: ArtOutputConfig for runtime output type changes.
- **Custom opcode 0x8110**: ArtReceiveConfig for split/combined universe layout.
- **Custom opcode 0x8130**: ArtVirtualResolution for per-output virtual send pixel counts (firmware 3.11+).
- **Custom opcode 0x8200**: ArtIPConfig for static IP / DHCP configuration.
- **Discovery capability tag**: `PV3CAP1|F:RIOHM|B:<profile>|IP:D|U:S:0|...` in ArtPollReply Node Report (`U:C:N` for combined mode; trailing `...` is the per-output `port:type:universe[:virtual]` tuples, with the optional fourth field being virtual pixel count on firmware 3.11+). Firmware **3.12+** put `F:` (feature flags) right after the `PV3CAP1` prefix instead of last — the Node Report is a hard 64-byte Art-Net field, and with 2 outputs + a 3-digit base universe + combined mode + a static IP the full token set can exceed that, so whatever comes last risks silent truncation. `F:` gates nearly every capability the sender can act on (rename, hello, IP config, output config, receive mode, battery, show info), so losing it is far worse than losing the lower-stakes per-output tuples, which now come last instead.
- **Feature flags**: `R` rename, `H` identify flash, `I` IP config, `O` output config, `M` receive mode config, `B` battery telemetry, `S` show info storage, `L` Setup-lane aware.
- **Lane ports (firmware 3.14+)**: Show 6454 / Setup 6457 / Watch 6455. A node advertises `SHOW:`/`MGMT:`/`TELE:` **only for a lane moved off its default** — the full 30-byte triple alone overflows the 64-byte Node Report and silently ate `IP:`, `U:`, `G:` and all per-output tuples. `L` in `F:` is what marks a node lane-aware, so `L` + no lane token means "on the documented defaults" and no `L` means pre-lane firmware whose Setup stays on the Show port. Node Report priority under pressure: `F:` → `B:` → `IP:` → `U:` → moved-lane tokens → per-output tuples → `G:` (last — but NOTE: the sender DOES parse `G:` and gates `management_supported` on it, so dropping it silently disables all 0x8140 management; known issue, see `V5/CHANGES.md`). Every token is appended only if it fits whole — a truncated `|MGMT:645` parses as a plausible port and would black-hole all Setup traffic.
- **Primus telemetry**: firmware 3.14+ sends the 28-byte `PST` unified status packet (fps, packet rate, flags, battery, lock state) on UDP 6455, unicast only after a telemetry target is set via mgmt op `0x11` — no broadcast fallback. The 7-byte `PFP` and 9-byte `PBT` packets are legacy (pre-3.14) and still parsed.
- **Radius telemetry**: `PTR` (byte-frozen: magic, state, nameLen, filename) and the 17-byte `PRS` status packet (firmware 4.16+: version, sequence u16 BE, uptime u32 BE, flags u16 BE, RSSI i8, battery power mode, battery mV u16 BE, battery pct) on UDP 6455, both parsed by `PrimusTelemetryListener` and `parse_prs_packet` in `artnet.py`. Radius feature string is `RIHASB` (`B` = battery).
- **Device identity**: ArtPollReply bytes 201-206 (MAC) become `device_uid` (`ip:<addr>` fallback) — the stable key for performer grouping and client-side card state; persisted across restarts.
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

Shipped PrimusCentral releases v0.81–v0.92 were built from **V4** with `--product primus`. **v0.97 is the first release built from V5**, for both PrimusCentral and DeviceManager. **Since v0.99 all three apps (PrimusCentral, RadiusCentral, DeviceManager) ship together under one `v0.9x` tag** with one `APP_VERSION` in `V5/sender/version.py` — pick the next free number in that single stream. (Historically PrimusCentral/DeviceManager shared `v0.9x` while RadiusCentral tagged separately as `RadiusCentral-v0.9x`; that split ended at v0.99.) The v0.65 release is an important packaged macOS performance marker from the earlier V3_6 line. It fixed an FPS drop where source `run.py` and direct binary execution reached about 30 FPS, but a real `.app` LaunchServices/Finder launch dropped to about 15-20 FPS. Future packaged FPS validation must launch the app through Finder or LaunchServices, not by running `PrimusCentral.app/Contents/MacOS/PrimusCentral` directly.

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
- V3.1 Reverse TFT Feather: direct NeoPixel outputs on A0/GPIO17 and A1/GPIO18, 240x135 ST7789 TFT, D0/D1 buttons, outputs WiFi-gated. (The NeoPXL8 FeatherWing path on GPIO14/15 still compiles behind `PRIMUS_DRIVER_NEOPXL8` but no current profile selects it.)
- Max 122 LEDs per port, 2 active ports per node.
