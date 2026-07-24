# PrimusV3 V5 Unified Sender

V5 is the **canonical sender track** for PrimusV3. It was materialized from the
complete tracked `V4/` tree at finalized flexible-device-control commit
`5ca259cb8ec94610d2a41c72f3fd54e3cf425202`; V4 remains available as a historical
reference. One Python tree builds **three apps**:

- **PrimusCentral** — LED clip/look/cue workflow (Look Designer, Cue Controller, ArtDmx)
- **RadiusCentral** — audio production workflow (Audio Cues, Cue Map, Net Log)
- **DeviceManager** — network monitoring, device config, and firmware upload, on the same `primus`-product backend as PrimusCentral

Shared: device discovery, firmware upload, and network settings. See [ARCHITECTURE.md](ARCHITECTURE.md).

## Quick start

**RadiusCentral (audio):**

```bash
python3 V5/sender/run.py
python3 V5/sender/run.py --product radius --no-browser --port 8098
```

**PrimusCentral (LED):**

```bash
python3 V5/sender/run.py --product primus
python3 V5/sender/run.py --product primus --no-browser --port 8090
```

**DeviceManager (monitoring, config, firmware):**

```bash
python3 V5/sender/run_devices.py
python3 V5/sender/run.py --product primus --frontend devices
```

DeviceManager attaches to an already-running PrimusCentral/DeviceManager server instead of starting a second one; if none is running it starts its own `primus`-product server in `monitor_only` mode, so it never auto-connects to or drives Art-Net output on discovered devices — safe to run on the same network as a show already being driven by another sender or console.

**Mixed Primus + Radius monitoring:** DeviceManager discovers both `PV3CAP1` Primus nodes and `PVRAD1` Radius nodes in the same grid. Radius devices are tagged `is_radius: true`, never receive ArtDmx, and use simplified monitor cards (no universe/receive-mode/output fields). Character and performer names for Radius devices persist in `.radius_state.json` via the shared `show_info_store.py` path. See [RADIUS_INTEGRATION.md](RADIUS_INTEGRATION.md).

**Mobile / Tablet View:** when DeviceManager starts its own fresh backend (the default `python3 V5/sender/run_devices.py` case above), it also binds the HTTP server to the local network (`0.0.0.0`) instead of loopback-only, so a phone or tablet on the same network can view a live, read-only copy of the Monitor tab. Scan the QR code under Settings > "Mobile / Tablet View" to open it — no internet connection is needed on either device. Expect a one-time OS firewall prompt the first time this runs. This does not apply when DeviceManager attaches to an already-running PrimusCentral/RadiusCentral server, which stays loopback-only.

```bash
python3 -m py_compile V5/sender/*.py
python3 -m unittest discover -s V5/sender/tests
```

## Layout

```
V5/
  sender/           Python backend + web UI
  tools/
    osc_cue_sender/  OSC cue test sender (PrimusCentral external control)
  Arduino/
    primusV3_receiver/   Primus LED firmware (profiles v1, v2, v3)
    radius_receiver/     Radius audio firmware (unified V1 + V2 sketch)
    upload.sh            Compile/upload script — all profiles (v1/v2/v3, rv1/rv2)
  build_sender_app.py  PyInstaller packaging (--product primus|radius)
  ARCHITECTURE.md      Unified backend roadmap
  assets/              App icon
  dist/                Build output
```

**Firmware canonical location:** `V5/Arduino/` holds both Primus and Radius receiver source. The V4 and V3_6 trees remain historical references; new firmware changes should land here.

## OSC Cue Sender

Standalone utility for testing PrimusCentral OSC cue triggers. See [`tools/osc_cue_sender/README.md`](tools/osc_cue_sender/README.md).

```bash
python3 V5/tools/osc_cue_sender/run.py
python3 V5/tools/build_app.py --target macos
```

## App data

| Product | Source run state | Packaged macOS |
|---------|------------------|----------------|
| **Radius** | `.radius_state.json`, `audio_cues.json`, `audio/` | `~/Library/Application Support/RadiusV3/V5/sender/` |
| **Primus** | `.primus_state.json`, `clips/`, `looks/`, `cues.json` | `~/Library/Application Support/PrimusV3/V5/sender/` |

Override with `RADIUSV5_DATA_DIR`, `PRIMUSV3_DATA_DIR`, `RADIUSV5_USE_APP_DATA=1`,
or `PRIMUSV3_USE_APP_DATA=1`. The former `RADIUSV4_*` variables remain accepted
as compatibility aliases.

## Web UI modes

**PrimusCentral** (`--product primus`): Look Designer, Cue Controller, Firmware, Settings

**RadiusCentral** (`--product radius`): Audio, Audio Cues, Cue Map, Net Log, Firmware, Settings. Device sidebar supports character/performer identity editing; show-info persists in `.radius_state.json`.

**DeviceManager** (`--frontend devices`, `primus` backend): Monitor (auto-syncing mixed Primus/Radius device grid, bulk rename/apply), Firmware (mixed Primus/Radius upload via `scope=mixed`), Settings — no Look Designer/Cue Controller, no manual connect/disconnect. Runs `monitor_only` whenever it starts its own backend. See [RADIUS_INTEGRATION.md](RADIUS_INTEGRATION.md).

Each app serves its own frontend at `/primus`, `/radius`, or `/devices` on the **same unified server** — shared `/css/` and `/js/` assets, separate Alpine SPAs. DeviceManager reuses the same `device-conn.js` device-action store as PrimusCentral/RadiusCentral.

Shared: **Firmware** (product-specific profiles in PrimusCentral/RadiusCentral; DeviceManager uses `scope=mixed` for all five board profiles), **Settings** (network)

For shared UIs and third-party tools, the same server now exposes explicit
Primus management JSON routes for authoritative `GET_CONFIG` refreshes, lock
state, descriptor-level updates, PST telemetry target control, production-mode
entry/unlock flow, and reusable output presets. See
[`../API_REFERENCE.md`](../API_REFERENCE.md) §3 and §8 for route names, request
shapes, and management/PST semantics.

### Flexible receiver setup

Management-v2 Primus receivers can be commissioned from either DeviceManager's
expanded card or the PrimusCentral device sidebar:

1. Keep both physical rows, A0 and A1, visible. Choose Off, a built-in output,
   a reusable preset, or open **Setup** for a custom strip/grid descriptor.
2. For grids, set rows/columns, row- or column-major traversal,
   progressive/serpentine wiring, start corner, and virtual pixels. The preview
   shows logical coordinates in physical wire order; ArtDmx bytes are never
   reordered by the receiver.
3. Set the PST target explicitly, normally with **Use sender IP**, and verify
   protocol/version, health/age, sequence/loss/reboot, and profile-appropriate
   battery status. Clearing the target disables telemetry; EOS/ArtDmx never
   selects a target automatically.
4. Enter production only after setup is verified. Production locks technical
   and show names, IP, outputs, receive mode/base universe, and telemetry while
   leaving Hello, ArtDmx, discovery, and monitoring active. V3 recovery is a
   physical D1 long-press; V1/V2 recovery uses the first 60 seconds after boot.

Built-in presets are read-only; user presets can be created, renamed, updated,
deleted with confirmation, and applied to either slot or a DeviceManager group.
Off remains recoverable through both the ordinary output selector and the Off
preset. An "Applied; awaiting refresh" result means the receiver ACKed but the
authoritative readback is pending, not that the write failed.

DeviceManager preserves monitor-only behavior: setup requests are one-shot and
never create standing DMX output. Mobile View stays read-only except Hello, and
Radius cards remain simplified with no Primus management controls.

## Push sync workflow

1. Import WAV files into the project library (Audio Cues panel).
2. Define cues with per-device play/loop actions referencing library filenames.
3. Click **Sync All** — stops playback on connected nodes, then FTP-uploads missing files to each node's SD root.
4. Poll `GET /api/audio_sync/status` for per-file progress (UI modal handles this automatically).

Pull sync and conflict resolution are **not** implemented in V5 (push-only).

## Packaging

**RadiusCentral:**

```bash
python3 V5/build_sender_app.py --target macos --product radius --name RadiusCentral
```

**PrimusCentral (from V5 unified codebase):**

```bash
python3 V5/build_sender_app.py --target macos --product primus --name PrimusCentral
```

Windows release build:

```powershell
py V5\build_sender_app.py --target windows --product primus --windows-installer
```

Output: `V5/dist/macos/PrimusCentral.app`, `RadiusCentral.app`, or `V5\dist\windows\PrimusCentral.exe`
Bundle IDs: `com.socialbodylab.PrimusCentral` / `com.socialbodylab.RadiusCentral`

See [PACKAGING.md](PACKAGING.md) for signing and release details.

## Protocol

| Opcode | Name | Purpose |
|--------|------|---------|
| 0x6000 | ArtAddress | Rename via NVS |
| 0x8200 | ArtIPConfig | Static IP / DHCP |
| 0x8210 | ArtShowInfo | Character/performer name (Radius 4.1+ and Primus 3.10+) |
| 0x8300 | ArtAudioCmd | play / loop / stop / pause / volume / test_tone / play_cue / loop_cue |
| 0x8301 | ArtFtpCmd | Start/stop FTP server |
| 0x8302 | ArtAudioStatus | Playback status from receiver (Radius V2 display path) |

**ArtAudioCmd commands:** 0=stop, 1=play, 2=loop, 3=pause, 4=volume, 5=test tone, 6=play cue number, 7=loop cue number. Optional filename (null-terminated ASCII, max 32 bytes) followed by optional uint16 LE duration seconds (0 = full file).

**Device cue map:** `/cues.json` on SD card (loaded at boot). Keys are cue numbers as strings; values are either a WAV filename string or `{"file": "name.wav", "duration": 30}`. Max 64 entries. Edited from the Cue Map panel or via `GET/POST /api/audio/cue_map`.

Capability tag: `PVRAD1|B:v1|IP:D|F:RIHAS` (V2 uses `B:v2`) where `R`=rename, `I`=IP config, `H`=hello/test-tone, `A`=audio, `S`=show info. Optional Marius tokens `MC:` / `MP:` on V2 when configured.

Track telemetry on UDP 6455: magic `PTR` + playback state + track name. FPS telemetry uses the shared `PFP` packet format on the same port.

## Firmware

See [FIRMWARE_DEVELOPMENT.md](FIRMWARE_DEVELOPMENT.md) for protocol notes on both families.

**Primus LED** (NeoPixel costume nodes):

Firmware **3.11+** adds per-output **virtual send resolution** (ArtVirtualResolution `0x8130`): the sender downsamples ArtDmx to fewer RGB triplets (Badge defaults to 1), and the receiver upscales to physical LEDs. Configure per device in the PrimusCentral sidebar **Send px** field or via `POST /api/set_device_virtual_resolution`. See [API_REFERENCE.md](../API_REFERENCE.md) §5.2.

```bash
./V5/Arduino/upload.sh --board v3 --compile
./V5/Arduino/upload.sh -v3 --auto
```

**Radius audio** (VS1053 + SD, unified V1/V2 sketch):

```bash
./V5/Arduino/upload.sh -rv1 --compile
./V5/Arduino/upload.sh -rv2 --compile
./V5/Arduino/upload.sh -rv1 -ssid "MyRouter" -pw "secret" --auto
```

DeviceManager mixed firmware upload uses `GET /api/firmware/status?scope=mixed` and `POST /api/firmware/jobs` with `"scope": "mixed"` to access all Primus and Radius board profiles from one panel. PrimusCentral and RadiusCentral keep product-scoped firmware panels unchanged.

## Compatibility policy

V5 changes source, package, app-data, and tooling paths only. Receiver product
names, `PrimusV3`/`RadiusV3` namespaces, firmware version semantics, capability
tags, packet formats, and custom Art-Net opcodes remain wire-compatible with the
finalized V4 implementation. This lets existing receivers and controllers
interoperate without a gratuitous protocol or NVS migration.

The bundled
[`FLEXIBLE_DEVICE_CONTROL_POSTMORTEM.md`](FLEXIBLE_DEVICE_CONTROL_POSTMORTEM.md)
and `.docx` are the finalized V4 implementation record copied from the source
commit; their V4 wording is intentionally historical.
