# V5 Unified Backend Architecture

One Python process serves three apps. PrimusCentral (LED show control),
RadiusCentral (audio), and DeviceManager (monitoring/config/firmware) are
launchers onto frontends of the same server — one HTTP server, one device
list, one telemetry listener, one registry entry. This document describes the
system as it is; the history of how it got here is in [CHANGES.md](CHANGES.md).

```
PrimusCentral.app   RadiusCentral.app   DeviceManager.app      (launchers)
      │                   │                   │
      └────────── attach or start ───────────┘
                        │
              one server process (run_primus.py)
   ┌───────────────────────────────────────────────────────┐
   │  HTTP server (server.py)                              │
   │    /primus   /radius   /devices   + /api/* (111)      │
   │  ControllerState (state.py)                           │
   │    devices[] — Primus and Radius records              │
   │    animation tick → ArtDmx   audio/FTP cmd surface    │
   │  PrimusTelemetryListener — UDP 6455                   │
   │    demux PST/PBT/PFP (Primus) + PTR/PRS (Radius)      │
   │  OSC listener (Primus cues) · firmware jobs · netlog  │
   └───────────────────────────────────────────────────────┘
          │ Show lane          │ Setup lane        ▲ Watch lane
          │ 6454 ArtDmx        │ 6457 config       │ 6455 telemetry
          │ 6456 ArtAudioCmd   │ + FTP gate        │
          ▼                    ▼                   │
      ESP32 receivers (Primus LED · Radius audio), FTP data on TCP 21
```

## Process model

- `run.py` is the single entry point. `--product primus` starts the unified
  server with `/primus` as the default frontend; `--product radius` flips the
  process to the `primus` product with `/radius` as the default frontend and
  delegates to `run_primus.main()`; `run_devices.py` is the DeviceManager
  launcher (`--frontend devices`, plus `--lan` for the Mobile View).
- `server.py` hosts the JSON API and the static Alpine.js frontends
  (no build step). HTTP/1.1 with keep-alive. `GET /` serves the default
  frontend for the active product directly (no redirect).
- **`ControllerState` is the one device list.** Primus records carry an
  `ArtNetSender` and output tables; Radius records are tagged
  `is_radius: true`, never get a sender, and are excluded from the DMX tick by
  explicit guards. The audio/FTP command surface (`send_audio_command`,
  `fire_audio_cue`, `ftp_*`) lives on `ControllerState`, so all
  `/api/audio/*` routes work on the shared server.
- `GET /api/state` returns the Primus shape; `GET /api/state?product=radius`
  returns the radius shape — **all devices, indices aligned with the unified
  list** (the Radius UI filters client-side). Device indices therefore mean
  the same thing in every frontend.
- **`RadiusState` is legacy.** It runs only under
  `PRIMUSV3_RADIUS_STANDALONE=1` (kept for tests and as a fallback) and has
  not been kept feature-current. Don't extend it.

## The animation tick

`state.py` runs the animation loop at `state.fps` (default 30) with
macOS-specific timing help: a `caffeinate` process assertion, user-interactive
thread QoS, and low-latency frame pacing with a spin tail (see
[PACKAGING.md](PACKAGING.md) — these are load-bearing for packaged FPS; do not
remove them, and do not resurrect the old `objc_msgSend` bridge that crashed
the app). Pixel building happens under the state lock; UDP sends happen
outside it. Per-frame memoization dedupes identical wired output across
devices. `/api/performance` exposes rolling timings and counters.

The tick's relationship to devices is the system's core safety invariant:

> **Connecting a device is what arms DMX to it.** A connected Primus device
> receives frames every tick — including keepalive blackouts when idle —
> which fights any external console driving the same node. Therefore
> `/api/devices/sync` (background discovery, every 20 s from every frontend)
> **never** connects anything, on any backend. Connect is an explicit
> operator action (`/api/connect`, `/api/connect_all`). This invariant
> replaced the old `monitor_only` mode outright.

One-off setup actions (hello, output config, IP config) use transient sends
and never create standing output. Radius devices are connected-by-default
because for them the flag gates one-shot audio commands, not a stream.

## Telemetry

One `PrimusTelemetryListener` binds UDP 6455 (`0.0.0.0`) and demuxes by magic:

| Magic | From | Content |
|---|---|---|
| `PST` | Primus 3.14+ | 28-byte unified status (fps, flags, battery, lock state) |
| `PBT` | Primus V1 pre-3.14 | legacy battery packet |
| `PFP` | both | 7-byte FPS/packet-rate (Radius always reports fps 0) |
| `PTR` | Radius | track name + playback state (byte-frozen) |
| `PRS` | Radius 4.16+ | 17-byte unified status (flags, RSSI, battery) |

Byte layouts live in [FIRMWARE_REFERENCE.md](FIRMWARE_REFERENCE.md). Merge
precedence: `PST` beats the legacy packets; `PRS` layers on (Radius never
sends PST); `PTR` overlays track state. Entries go stale after 12 s;
"receiver online" means seen within 3 s. Devices are identified by source IP.

The socket is single-owner — that fact is *why* RadiusCentral had to become a
frontend rather than a second process. If the bind fails, the listener falls
back to an ephemeral port and telemetry silently reads offline; the fix is to
find and stop the other process (`run.py --server-status` / `--stop-server`).

Primus nodes send telemetry only after a target is set
(`POST /api/set_device_telemetry_target`); there is no broadcast fallback.
The target is explicit and persisted so third-party ArtDmx (EOS) can never
redirect monitoring. Radius nodes latch the sender IP from real command
packets (never from ArtPoll, so passive discovery tools can't steal the
stream).

## Launcher contract

The apps are launchers; before attaching to an existing server each one must
answer: is a Central running, can it serve *my product*, can it serve *my
capabilities*? `central_launcher.evaluate_server()` is where that happens.
A mismatch must never silently attach — packaged apps have no console, so a
silent wrong decision is indistinguishable from a failed launch.

- The registry (`central_server.json`, in shared PrimusV3 app data) records
  host, port, pid, `products` (the unified backend registers
  `["primus","radius"]`), `monitor_only`, `lan_enabled`, `app_version`.
  `GET /api/runtime` advertises the same and is the liveness probe;
  `GET /api/server/status` carries the richer operational detail
  (`live_output`, client sessions, uptime) so `/api/runtime` can stay
  shape-stable for old clients.
- `try_attach_before_start(..., need_product=, needs_output=, on_mismatch=)`:
  the handler returns `"attach"`, `"start"`, or `"abort"`; with no handler the
  default is to refuse, not attach. A backend with no product information is a
  loud mismatch (`MISMATCH_UNKNOWN_PRODUCT`). Dialogs are stdlib-only
  (`launcher_dialog.py`; `PRIMUSV3_NO_DIALOGS=1` forces the non-blocking
  fallback for scripts/CI).
- Attach calls `reserve_ui_session()` first, so the running server counts the
  new client before its browser window exists and can't auto-quit in the gap.
- `POST /api/server/stop` refuses with 409 while output is live unless
  `{"force": true}` — one app can never black out a show another is running.

## Window / UI lifecycle (packaged apps)

- Each frontend runs in its own dedicated Chromium app window with its own
  profile directory and icon. Attach launches use a fresh profile subdir every
  time (Chromium's single-instance handoff drops `--app` URLs otherwise), and
  window liveness is judged by live processes, never marker files.
- Frontends heartbeat `POST /api/ui/heartbeat` every 2 s with a per-window
  session id. When all sessions are gone and nothing is live, the server
  releases any zombie mixer preview and quits after a short grace period.
- If output **is** live with no window, the server reopens its window (at most
  every 30 s) instead of running as an invisible resident.
- Auto-quit and `/api/server/stop` consume the same `live_output_fn`
  (Primus playback source active OR `radius_has_live_playback()` from PTR),
  composed once in `run_primus.py`. Both fail toward "live" on error.

## Persistence

- `paths.py` decides the data directory: env overrides
  (`PRIMUSV3_DATA_DIR`, `RADIUSV5_DATA_DIR`), app data when packaged
  (`~/Library/Application Support/PrimusV3/V5/sender/` on macOS), else the
  source tree.
- `.primus_state.json`: devices (including `device_uid`, capabilities,
  management state, per-output config), device groups, Primus show-info.
- `.radius_state.json`: Radius show-info (character/performer), and — written
  by the legacy standalone backend only — a devices list that the unified
  backend imports read-only at startup.
- `show_info_store.py` is the single decision point for which file a device's
  show info lands in (`is_radius` routes to the radius file).
- On first launch of a packaged RadiusCentral against the unified tree,
  legacy `RadiusV3` app data (state, cue sheet, audio library) is copied —
  never moved — into the PrimusV3 tree (`run.py::_migrate_radius_app_data`).
- Restore is discovery-verified: saved devices are matched by IP then unique
  name against a boot-time sweep; offline devices come back as saved records,
  and a saved `is_radius` record is forced back to radius capabilities even if
  its saved capability dict was lost (otherwise it would be given an
  `ArtNetSender` and streamed DMX keepalives).

## Firmware families

| Family | Profiles | Sketch | Upload script | Capability tag |
|---|---|---|---|---|
| Primus | `v1`, `v2`, `v3` | `Arduino/primusV3_receiver/` | `Arduino/upload.sh` | `PV3CAP1\|…` |
| Radius | `radius_v1`, `radius_v2` | `Arduino/radius_receiver/` | `Arduino/radius_upload.sh` | `PVRAD1\|…` |

Firmware upload jobs (`firmware.py`, `/api/firmware/*`) are product-scoped per
app; DeviceManager passes `scope=mixed` to see all five profiles in one panel.
Node capability parsing lives in `artnet.py` (`parse_node_capabilities`);
[FIRMWARE_REFERENCE.md](FIRMWARE_REFERENCE.md) is the byte-level contract.

## Network model

UDP lanes (Show/Setup/Watch) are documented in
[PORTS_AND_LANES.md](PORTS_AND_LANES.md). Sender-side network settings
(`network_settings.py`, `/api/network/*`) manage the host's Art-Net interface
selection, SSID profiles, and the editable lane-port defaults; host static-IP
apply is macOS-only and escalates through a GUI prompt.

HTTP binds loopback by default. `--lan` (injected by `run_devices.py` for the
Mobile/Tablet View) binds `0.0.0.0` — there is **no auth anywhere** by policy
(trusted, isolated show network), so widening any bind is a security decision;
see [REMOTE_BACKEND_NOTES.md](REMOTE_BACKEND_NOTES.md) before changing this.

## Design rules that explain the code

- **No external Python dependencies in the sender.** Stdlib only — Art-Net,
  OSC, FTP, HTTP are all hand-rolled. The single biggest constraint.
- **Table-driven output types** on both sides (`OUTPUT_TYPES` /
  `LOOK_OUTPUT_TYPES` in Python ↔ `OutputType` enum / `OUTPUT_TYPE_TABLE` in
  C++, matched by index). Custom opcodes live in the 0x8000+ range.
- **Brightness is sender-side RGB scaling only.** Receiver driver stays at
  255; the V2 brightness-byte protocol is intentionally dead.
- **Frontends are origin-relative.** Every fetch goes through a bare-path
  `api()` helper; no hardcoded hosts, no CORS surface. Keep it that way.
- The backend is authoritative for device config: UI drafts go through HTTP →
  a Setup-lane mutation → ACK/NACK → readback; the UI renders what came back,
  not what it sent.

## What still needs work

See [CHANGES.md — What still needs work](CHANGES.md#what-still-needs-work)
for the current list (lane-resolution divergence, the `G:` token hazard,
standalone-path drift, the no-auth/`--lan` tension, silent `OSError`
swallowing in persistence). The forward-looking design notes for running this
backend on a dedicated machine are in
[REMOTE_BACKEND_NOTES.md](REMOTE_BACKEND_NOTES.md), including standing rules
for interim work (no new `127.0.0.1` literals, no new fast polling, no new
signalling on the focus socket).
