# V3.6 Sender Development

This document is the working reference for future V3.6 Python sender and web UI changes.

## Source Tree

Active sender code lives in:

```text
V3_6/sender/
├── run.py                  # Entry point, HTTP server startup, render loops
├── state.py                # Output tables, device state, playback source, Art-Net sends
├── artnet.py               # Art-Net packets, discovery, capability parsing, FPS telemetry
├── server.py               # HTTP API and static file server
├── firmware.py             # Source-checkout firmware upload jobs for the web UI
├── effects.py              # Effects and pixel transforms
├── clips.py                # Clip persistence and preview computation
├── mixer.py                # Look timeline frame computation
├── controller.py           # Cue list playback and crossfades
├── osc_control.py          # Inbound OSC parser/listener for cue triggers
├── web/                    # Static Alpine.js UI
└── tests/                  # Stdlib unittest smoke tests
```

The sender remains Python stdlib-only. Do not add package dependencies without an explicit packaging decision.

## Run And Test Commands

Run sender:

```sh
python3 V3_6/sender/run.py
python3 V3_6/sender/run.py --port 0
```

`run.py` is the canonical entry point and defaults to `http://127.0.0.1:8080`, with auto-port fallback if 8080 is busy. Running it directly starts the server, inbound OSC cue listener, replaces any previous V3.6 sender process, and opens the interface. Chromium-family browsers are launched with a fresh Primus-only app profile to avoid browser session-restore duplicate tabs; if no supported browser is available, startup falls back to the system default browser. `controller.py` contains cue-list logic and does not launch the interface.

Run checks:

```sh
python3 -m py_compile V3_6/sender/*.py
python3 -m unittest discover -s V3_6/sender/tests
```

The sender writes local runtime state to `V3_6/sender/.primus_state.json`. That file is generated during tests and should not be committed.

## Core Data Model

### Output Types

`state.py` owns the sender-side output type table:

- `OUTPUT_TYPES` maps sender keys to pixel count and layout.
- `LOOK_OUTPUT_TYPES` maps numeric type IDs to sender keys.

`LOOK_OUTPUT_TYPES` index order must match firmware `OutputType` enum values in `V3_6/Arduino/primusV3_receiver/config.h`.

Current order:

```python
LOOK_OUTPUT_TYPES = [
    "none",
    "short_strip",
    "long_strip",
    "grid",
    "small_grid",
    "extra_long_strip",
]
```

### Active Look

The sender currently computes one active look with two logical outputs. Output config updates are sent to connected devices from that shared active look.

V3.6 brightness is sender-side RGB scaling. Clips store `brightness` as a normalized `0.0` to `1.0` value, Looks store a final master `brightness`, and Timeline segments can set `brightness_override` or leave it `null` to use the Clip value. The web UI displays these values as `0` to `100%`. Existing clips and looks that omit brightness render at full brightness.

Rendering order is: compute the effect at full intensity, scale segment pixels by the segment override or Clip brightness, apply fades/crossfades, then scale the finished Look frame by Look brightness. Do not add firmware brightness bytes or receiver `setBrightness()` changes for show dimming.

Important mixed-hardware note: V1/V2/V3.1 devices can be discovered and controlled together, but the current sender does not yet maintain independent native output-type selections per hardware profile during live playback. Connecting all devices after changing the active look can push the same two output types to every connected receiver. Future work for true mixed-costume operation should add per-device or per-profile output routing.

### Cue Hierarchy

The phase-one UI hierarchy is Cues, then Looks, then Clips:

- Clips are single-output effect presets.
- Looks combine and manipulate Clips across the two logical output slots.
- Cues are production triggers that can fire multiple Looks at once, with each Look assignment targeting its saved Look target, all devices, a device group, or selected devices.

`controller.py` normalizes both assignment-based cues and older one-Look cues. New cues should use `assignments`, where each item is either `{"action":"look", "look_id":"...", "target_mode":"look"}` or `{"action":"blackout"}`. Top-level `look_id` remains for compatibility when a cue has exactly one Look assignment.

The Cue Controller web mode is a live manual button board. Entering it hides the network Devices sidebar, connects saved devices, and sends controller blackout before show operation begins. It does not expose sequential GO/NEXT controls, auto-follow setup, cue reordering, or a cue timeline; clicking a cue square directly fires that cue, and the only per-square control is Edit.

Inbound OSC control is implemented in `osc_control.py` and defaults to `127.0.0.1:53001`. It is stdlib-only and supports `/primus/cue/go`, `/primus/cue/goto` with an integer argument, `/primus/cue/name` with a cue-name argument, `/cue/goto`, `/cue/name`, `/primus/cue/<slug>`, QLab-friendly `/cue/<slug>/start`, `/primus/cue/stop`, and `/primus/blackout` with an optional fade-time argument. Cue name lookup is exact case-insensitive first, then unique slug fallback, where a slug is lowercase words joined with hyphens.

### Device Records

Device records include:

- `name`
- `ip`
- `base_universe`
- `connected`
- `capabilities`
- `hardware_profile`
- `hardware_label`
- `firmware_version`
- output records with `type`, `count`, `grid`, and `universe`

The UI reads these fields from `/api/state` and displays hardware/profile metadata on device cards and discovered nodes.

## Discovery And Capabilities

Discovery lives in `artnet.py`:

- `discover_artnet_nodes()` sends ArtPoll and optional unicast polls.
- `parse_node_capabilities()` parses V3.6/V3.1 capability tags.
- `parse_node_outputs()` converts Node Report output tokens into sender output configs.

V3.6 Node Report example:

```text
#0001 [0000] OK|PV3CAP1|0:4:0|1:2:1|B:v1|F:RIOH
```

Meaning:

- `PV3CAP1`: Primus capability contract.
- `0:4:0`: port 0 uses type ID 4 (`small_grid`) on universe 0.
- `1:2:1`: port 1 uses type ID 2 (`long_strip`) on universe 1.
- `B:v1`: board profile is V1.
- `F:RIOH`: rename, IP config, output config, and hello are supported.

Older V3.1-style reports without `B:<profile>` should still parse as known Primus nodes and default to the V3.1 hardware profile when the node identity indicates PrimusV3.

## HTTP API Areas To Know

Important device/control endpoints in `server.py`:

| Endpoint | Purpose |
| --- | --- |
| `GET /api/state` | Full app/device/playback state for the UI. |
| `POST /api/discover` | Art-Net discovery. |
| `POST /api/add_discovered` | Add a discovered Art-Net node. |
| `POST /api/add_manual` | Poll/add a device by IP. |
| `POST /api/connect` / `connect_all` | Connect sender and send output config if supported. |
| `POST /api/disconnect` / `disconnect_all` | Blackout and disconnect devices. |
| `POST /api/rename_node` | ArtAddress rename. |
| `POST /api/hello_device` | Identify flash through the live Art-Net output path. |
| `POST /api/set_device_ip` | Static IP config. |
| `POST /api/revert_device_dhcp` | Return device to DHCP. |
| `POST /api/update` | Designer/output type/effect settings. |
| `GET /api/cues` / `POST /api/cues` | Read or replace the cue list. Cues should use assignment-based payloads. |
| `POST /api/cues/go` / `POST /api/cues/goto` | Fire the next cue or a specific cue number through the controller source. |
| `POST /api/controller/blackout` | Send controller blackout, used when entering Cue Controller mode. |
| `GET /api/integrations/osc` | OSC listener settings, bound endpoint, recent message history, and cue trigger hints. |
| `POST /api/integrations/osc` | Enable/disable or rebind the inbound OSC listener. |
| `GET /api/firmware/status` | Firmware upload tooling availability and current/last job. |
| `POST /api/firmware/jobs` | Start a source-checkout firmware job: list ports, install, compile, or upload. |
| `GET /api/firmware/jobs/:id` | Poll a firmware job, including redacted output and structured port results. |
| `GET /api/network/status` | Sender host network interfaces, preferred/recommended Art-Net route, subnet/range summaries, and saved static/DHCP profiles. |
| `POST /api/network/preferred_interface` | Select or clear the sender interface used for Art-Net discovery and output sockets. |
| `POST /api/network/ssid_profile` | Save a sender static/DHCP profile for a WiFi SSID or wired service. |
| `POST /api/network/controller_connection` | Tag or clear the WiFi SSID used by the controller/show router. |
| `POST /api/network/apply_static_ip` | Apply a macOS static IP profile through an administrator prompt. |
| `POST /api/network/set_dhcp` | Revert a macOS network service to DHCP through an administrator prompt. |

Firmware upload jobs wrap `V3_6/Arduino/upload.sh` and are source-run only in the first pass. The Firmware tab presents the simple path: choose firmware version, refresh/select an available USB device or all devices, independently enable default device-name and/or WiFi overrides, then compile or upload while watching the output window. The API still supports the script's maintenance actions where useful. It returns `409` when another firmware job is running, `400` for invalid action/profile/port data, and `503` when the upload script, `bash`, `python3`, or `arduino-cli` is unavailable. WiFi passwords must not appear in API responses or web UI output.

Sender network settings live in `network_settings.py` and persist under the `sender_network` key in `.primus_state.json`. Host IP apply/revert is macOS-only in the first implementation and uses stdlib `subprocess` with `/usr/sbin/networksetup`; no external Python packages are used. Art-Net discovery accepts the selected interface record, and `ArtNetSender` plus one-shot control helpers can bind outgoing UDP sockets to the selected source IP. Settings recommends active Ethernet/USB-Ethernet for the common show-router workflow, returns per-interface CIDR/usable-range summaries, and validates static sender profiles so the IP is a usable host and the gateway is in the same subnet. WiFi preferences and the controller/show-router network remain SSID-aware as an advanced path; placeholder SSID values such as `<redacted>` and `<data> 0x00` are ignored.

## Web UI Files

The UI is static Alpine.js:

```text
V3_6/sender/web/
├── index.html
├── css/style.css
└── js/
    ├── app.js
    ├── look-mixer.js
    ├── look-controller.js
    ├── firmware.js
    └── settings.js
```

Device profile fields are surfaced in `index.html` and managed through the `conn` Alpine store in `app.js`.

Guidelines:

- Keep the UI dependency-free and static.
- Keep capability-aware controls disabled when the receiver does not advertise support.
- Display profile metadata from API state rather than inferring board generation from IP/name.
- Keep the Firmware tab visually aligned with the mixer/controller panels and use local API jobs instead of invoking upload commands from browser code.

### Workshop UI Profile

The 0.7 workshop release defaults the browser UI to a focused workshop profile in `web/js/app.js`. This is a cosmetic filter only: the sender state, API, saved files, and firmware keep the full output type table.

Workshop output names:

| Sender type | Workshop label |
| --- | --- |
| `small_grid` | Badge |
| `short_strip` | Collar |
| `extra_long_strip` | Belt |
| `none` | None |

The workshop profile hides `long_strip` and `grid` from ordinary selectors and clip browsing. Full functionality can be restored in the browser with `?ui=full` or `?profile=full`; return to the workshop profile with `?ui=workshop` or `?profile=workshop`. The selected profile is stored in browser `localStorage` as `primusUiProfile`.

Keep this as a UI profile unless the user explicitly asks for a protocol or firmware change.

## Adding Output Types

1. Update firmware `config.h` enum and `OUTPUT_TYPE_TABLE[]`.
2. Update sender `OUTPUT_TYPES` and `LOOK_OUTPUT_TYPES` in `state.py`.
3. Keep the numeric ID/index aligned.
4. Update `hardwareCompatibility.md` and `FIRMWARE_DEVELOPMENT.md`.
5. Add or update discovery parser tests in `sender/tests/`.
6. Re-run sender tests and all firmware profile compiles.

## Adding Profile Metadata

If a new firmware board profile is introduced:

1. Add the profile code/label in firmware `config.h`.
2. Ensure Node Report emits `B:<profile>`.
3. Add the profile label mapping in `artnet.py`.
4. Add parser test coverage in `test_artnet_capabilities.py`.
5. Surface any new profile-specific behavior through `/api/state`.

## Runtime Smoke Test

Use this to check a freshly flashed board from the command line:

```sh
python3 V3_6/sender/run.py --port 0
```

Then, in another terminal, replace the port with the printed URL:

```sh
curl -s -X POST http://127.0.0.1:<port>/api/discover -H 'Content-Type: application/json' -d '{}'
curl -s -X POST http://127.0.0.1:<port>/api/add_manual -H 'Content-Type: application/json' -d '{"ip":"192.168.1.8"}'
curl -s -X POST http://127.0.0.1:<port>/api/hello_device -H 'Content-Type: application/json' -d '{"device":0}'
curl -s -X POST http://127.0.0.1:<port>/api/disconnect_all -H 'Content-Type: application/json' -d '{}'
```

Before committing, remove generated runtime state:

```sh
rm -f V3_6/sender/.primus_state.json
```

## Audio Library Sync

The audio library sync system manages WAV files between the sender's local project library and Radius device SD cards. It supports three operations: **pull** (devices → sender), **push** (sender → devices), and **rescan** (inventory refresh only). All three run as background jobs tracked via `GET /api/audio_sync/status`.

### Project Audio Library

The library is a flat folder of WAV files managed by `audio_cues.py`. Checksums are SHA-256 and cached in `audio/.checksums.json` so files are not re-hashed on every request.

| Function | Description |
|---|---|
| `list_project_audio()` | Returns `[{name, size, checksum, path}]` for all files |
| `save_project_audio(filename, data)` | Writes a WAV to the library; raises if filename exists with a different checksum |
| `save_project_audio_temp(checksum, data)` | Saves a downloaded copy to a temp path keyed by checksum digest; used during pull conflict staging |
| `get_project_audio_path(filename)` | Returns absolute path or `None` |
| `get_project_audio_temp_path(checksum)` | Returns temp path or `None` |
| `delete_project_audio(filename)` | Removes from library; returns bool |
| `discard_project_audio_temp(checksum)` | Deletes a staged temp file |
| `load_audio_cues()` / `save_audio_cues(data)` | Cue sheet persistence (separate from library) |

### Stop Before Sync

All three job types send ArtAudioCmd cmd=0 (stop) to every `is_audio` device before opening any FTP connection, then sleep 300 ms. This clears the `sdBusy` flag on the VS1053 so FTP transfers proceed without stalling. Devices that are not playing audio are unaffected. The stop command is UDP/fire-and-forget; the 300 ms wait is sufficient for the VS1053 to drain its buffer and release the SD bus under normal conditions.

The UI must show a confirmation dialog before starting any sync job: "This will stop audio on all Radius devices."

### Push Job (sender → devices)

Implemented in `_run_sync_job()` in `server.py`. For each `is_audio` device:

1. FTP-list `/` on the device.
2. Collect filenames referenced by cues assigned to that device IP.
3. Upload each required file that is missing from the device, reading from the local library.
4. Track progress via the `progress_callback` parameter on `ftp_upload()`.

### Pull Job (devices → sender)

Implemented in `_run_pull_job()` in `server.py`.

1. Send stop + wait 300 ms.
2. FTP-list `/` on each connected `is_audio` device. Build `filename → [device_ip, …]`.
3. For each filename found on any device:
   - Download all copies (one per source device), updating `bytes_received` on each item via `progress_callback` on `ftp_download()`.
   - Compute SHA-256 checksum of each downloaded copy.
   - If a local library copy exists, include its checksum in the comparison.
   - Group all sources by checksum digest.
4. Apply the grouping result per filename:
   - **Single group, no local copy** → `save_project_audio()`; item status `done`.
   - **Single group, local matches** → no write needed; item status `confirmed`.
   - **Multiple groups** → `save_project_audio_temp()` for each unique checksum; add a conflict entry to the job.
5. Job reaches `status: "done"`. Conflict entries remain until resolved.

### Conflict Model

A conflict entry has one `filename` and two or more `groups`. Each group represents a unique file version:

```python
{
    "filename": "intro.wav",
    "groups": [
        {
            "checksum": "sha256:abc123...",
            "size": 2048000,
            "sources": [
                {"type": "local"},
                {"type": "device", "device_ip": "192.168.8.151", "device_name": "Radius-1"},
                {"type": "device", "device_ip": "192.168.8.153", "device_name": "Radius-3"},
            ],
            "temp_path": None,                          # None when this group IS the local copy
            "suggested_name": "intro.wav",
        },
        {
            "checksum": "sha256:def456...",
            "size": 1900000,
            "sources": [
                {"type": "device", "device_ip": "192.168.8.154", "device_name": "Radius-4"}
            ],
            "temp_path": "/path/to/audio/.tmp/def456.wav",
            "suggested_name": "intro_radius-4.wav",
        },
    ],
}
```

**Suggested name logic:** The group with the most sources gets the original filename (ties broken by preferring the group that includes the local copy). Each remaining group is named `<basename>_<first-source-device-name>.<ext>`, lower-cased with spaces replaced by hyphens.

### Resolve Flow

`POST /api/audio_sync/resolve` handles one conflict at a time. For each resolution:
- `"save"` → move the temp file into the library under `save_as`. Returns 409 if `save_as` already exists with a different checksum — the UI must prompt for a different name.
- `"discard"` → call `discard_project_audio_temp(checksum)`.

When all groups for a conflict are resolved, that entry is removed from the job. The active job is kept in the module-level `_sync_job` dict until a new job starts.

### Combined File List

`GET /api/project_audio` merges two sources:

1. **Local library** (`audio_cues.list_project_audio()`) — always current.
2. **Cached device inventory** — the module-level `_device_inventory` dict in `server.py`, populated by pull, push, and rescan jobs. Keyed by device IP; each entry holds a file list and a `scanned_at` timestamp.

The response includes `inventory_age_seconds` so the UI can display "last scanned N minutes ago" and offer a rescan button. Rescan (`POST /api/audio_sync/rescan`) FTP-lists all devices without downloading, then updates `_device_inventory` in place.

### Progress Tracking

Both push and pull job items carry byte-level progress:

```python
{
    "filename": "kick.wav",
    "device_ip": "192.168.8.151",
    "device_name": "Radius-1",
    "bytes_total": 1234567,
    "bytes_received": 614400,   # pull jobs
    "bytes_sent": 0,            # push jobs
    "status": "downloading",
}
```

`ftp_download()` in `artnet.py` accepts an optional `progress_callback(received, total)` that the job thread calls on each received chunk. The UI polls `GET /api/audio_sync/status` on a 500 ms interval and renders a per-file progress bar from `bytes_received / bytes_total`.

### Module Responsibilities

| Module | Responsibility |
|---|---|
| `audio_cues.py` | Library CRUD, checksum cache, temp file staging, cue sheet persistence |
| `artnet.py` | `ftp_download(ip, path, progress_callback)`, `ftp_upload(ip, path, data, progress_callback)`, `send_audio_cmd(ip, cmd)` |
| `server.py` | `_run_sync_job()` (push), `_run_pull_job()` (pull), `_run_rescan_job()`, `_device_inventory`, resolve handler |
| `web/audio-cues.js` | Pull button with confirm dialog, per-file progress bars, conflict resolution panel |

---

## Test Coverage

Current test coverage is focused on Art-Net capability parsing and discovery compatibility:

```text
V3_6/sender/tests/test_artnet_capabilities.py
```

Add tests when changing:

- Node Report parsing.
- Output token parsing.
- Hardware profile fallback behavior.
- Capability flag behavior.
- Output type IDs.
