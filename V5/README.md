# PrimusV3 V5 — Unified Sender

V5 is the canonical track: **one Python backend, three apps**, both receiver
firmware families, and the packaging pipeline. This tree is the shared base
for all Primus and Radius work.

- **PrimusCentral** — LED show control (Look Designer, Cue Controller, ArtDmx)
- **RadiusCentral** — audio production (Audio, Audio Cues, Cue Map, Net Log)
- **DeviceManager** — performer-first monitoring, device config, mixed firmware upload

All three are frontends (`/primus`, `/radius`, `/devices`) of the same server
process, sharing one device list and one telemetry listener.

## Documentation index

| Read this for | Doc |
|---|---|
| **What changed at the 2026-08 unification, and what still needs work** | [CHANGES.md](CHANGES.md) |
| How the backend is put together | [ARCHITECTURE.md](ARCHITECTURE.md) |
| The complete HTTP API + external-integration guide | [API_REFERENCE.md](API_REFERENCE.md) |
| UDP ports and lanes (Show / Setup / Watch) | [PORTS_AND_LANES.md](PORTS_AND_LANES.md) |
| Firmware behavior, telemetry bytes, capability tags | [FIRMWARE_REFERENCE.md](FIRMWARE_REFERENCE.md) |
| Primus firmware internals, section by section | [PRIMUS_FIRMWARE_MAP.md](PRIMUS_FIRMWARE_MAP.md) |
| Mixed Primus/Radius monitoring and show identity | [RADIUS_INTEGRATION.md](RADIUS_INTEGRATION.md) |
| Building, signing, notarizing, DMGs | [PACKAGING.md](PACKAGING.md) |
| Firmware build profiles and hardware notes | [FIRMWARE_DEVELOPMENT.md](FIRMWARE_DEVELOPMENT.md) |
| Future remote-backend design notes + interim rules | [REMOTE_BACKEND_NOTES.md](REMOTE_BACKEND_NOTES.md) |

Historical planning/audit documents live in [docs/archive/](docs/archive/).
Release notes are the `0xxReleaseNotes.md` files in this directory.

## Quick start

```bash
# PrimusCentral
python3 V5/sender/run.py --product primus

# RadiusCentral (a frontend on the same unified backend)
python3 V5/sender/run.py --product radius

# DeviceManager (attaches to a running server, or starts its own)
python3 V5/sender/run_devices.py
```

Useful flags: `--port N` (`--port 0` for an ephemeral port), `--no-browser`.
If a server is already running, launchers attach to it — a server that can't
serve the requested product produces a dialog, never a silent attach. Recover
an orphaned server with:

```bash
python3 V5/sender/run.py --server-status
```

```bash
python3 V5/sender/run.py --stop-server
```

**Monitoring is passive.** Background sync discovers and refreshes devices but
never connects them — connecting is what arms DMX output (which would fight an
external console like EOS or TouchDesigner), so it is always an explicit
button/API action. This holds for every backend, whichever app started it.

**Mobile / Tablet View:** when DeviceManager starts its own backend it binds
the LAN and shows a QR code (Settings → Mobile / Tablet View) for a read-only
Monitor view on a phone — no internet needed. Attaching to an existing server
keeps it loopback-only.

## Tests

```bash
python3 -m py_compile V5/sender/*.py
python3 -m unittest discover -s V5/sender/tests
```

The suite is self-isolating (scratch state dirs, TEST-NET IPs, no bind on
UDP 6455) so it can run on a machine with a live show network and a running
Central. Keep new tests that way — see the `StateScratchMixin` pattern in
`tests/test_management_state.py`.

## Layout

```
V5/
  sender/                Python backend (stdlib only) + static web UIs
    run.py               Entry point for all three apps
    state.py             ControllerState: device list, tick, audio surface
    server.py            HTTP server: /primus /radius /devices + JSON API
    artnet.py            Art-Net framing, lane resolution, telemetry listener
    web/                 Alpine.js SPAs (no build step)
    tests/               Stdlib unittest suite
  Arduino/
    primusV3_receiver/   Primus LED firmware (profiles v1, v2, v3)
    upload.sh            Primus compile/upload
    radius_receiver/     Radius audio firmware (profiles radius_v1, radius_v2)
    radius_upload.sh     Radius compile/upload
  tools/osc_cue_sender/  OSC cue test sender
  build_sender_app.py    PyInstaller packaging (--product ... --dmg)
  build_firmware_bundle.py  Firmware GitHub release assets
```

`V5/Arduino/` is the canonical firmware location; the `V4/` and `V3_6/` trees
are historical references only.

## App data

All three apps share the unified backend's data directory:

| Run mode | Location |
|---|---|
| Source runs | `V5/sender/` (state files, `clips/`, `looks/`, `audio/`) |
| Packaged macOS | `~/Library/Application Support/PrimusV3/V5/sender/` |
| Packaged Windows | `%APPDATA%\PrimusV3\V5\sender\` |

On first launch, a packaged RadiusCentral copies legacy
`RadiusV3/V5/sender/` data (`.radius_state.json`, `audio_cues.json`,
`audio/`) into the unified tree — copied, never deleted. Overrides:
`PRIMUSV3_DATA_DIR`, `RADIUSV5_DATA_DIR`, `PRIMUSV3_USE_APP_DATA=1`
(`RADIUSV4_*` still accepted as aliases).

## Firmware quick commands

```bash
./V5/Arduino/upload.sh --ports
```

```bash
./V5/Arduino/upload.sh -v3 --auto
```

```bash
./V5/Arduino/radius_upload.sh -v1 --compile
```

```bash
./V5/Arduino/radius_upload.sh -v1 --auto
```

Upload commands compile first automatically. Use `--auto` only with exactly
one ESP32-like port connected; `--all` flashes every detected candidate with
the same profile. DeviceManager's Firmware tab drives the same scripts with
`scope=mixed` for all five board profiles; PrimusCentral and RadiusCentral
stay product-scoped.

Current firmware: **Primus 3.14.1** (`PV3CAP1`, features `RIOHBMSGL`/
`RIOHMSGL`) and **Radius 4.20** (`PVRAD1`, features `RIHASB`). Contracts and
byte layouts: [FIRMWARE_REFERENCE.md](FIRMWARE_REFERENCE.md).

## Packaging

Local unsigned builds:

```bash
python3 V5/build_sender_app.py --target macos --product primus --name PrimusCentral
```

```bash
python3 V5/build_sender_app.py --target macos --product radius --name RadiusCentral
```

```bash
python3 V5/build_sender_app.py --target macos --product devices --name DeviceManager
```

Signed release builds add `--sign-identity`, `--notary-profile`, and `--dmg`;
the full checklist (including LaunchServices FPS validation — never launch the
bare binary to measure) is in [PACKAGING.md](PACKAGING.md). Bundle IDs:
`com.socialbodylab.{PrimusCentral,RadiusCentral,DeviceManager}`. Since v0.99
all three apps ship together under one `v0.9x` tag.

## Push sync (Radius audio)

1. Import WAVs into the project library (Audio Cues panel).
2. Define cues with per-device play/loop actions.
3. **Sync All** stops playback, then FTP-uploads cue-referenced files missing
   from each node's SD. Progress via `GET /api/audio_sync/status`.

Pull sync and conflict resolution are intentionally not implemented.

## Compatibility policy

V5 changed source, packaging, app-data, and tooling paths — not the wire.
Receiver product names, NVS namespaces, capability tags, packet formats, and
the custom Art-Net opcodes remain compatible with finalized V4, so existing
receivers and controllers interoperate without a protocol migration. The wire
contracts live in [FIRMWARE_REFERENCE.md](FIRMWARE_REFERENCE.md) and the
[API_REFERENCE.md](API_REFERENCE.md) appendix; the current migration state
(dual-listen, lane advertisement) is in
[PORTS_AND_LANES.md](PORTS_AND_LANES.md).
