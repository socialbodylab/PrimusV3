# V3.5 Sender Development

This document is the working reference for future V3.5 Python sender and web UI changes.

## Source Tree

Active sender code lives in:

```text
V3_5/sender/
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
python3 V3_5/sender/run.py
python3 V3_5/sender/run.py --port 0
```

`run.py` is the canonical entry point and defaults to `http://127.0.0.1:8080`, with auto-port fallback if 8080 is busy. Running it directly starts the server, inbound OSC cue listener, replaces any previous V3.5 sender process, and opens the interface. Chromium-family browsers are launched with a fresh Primus-only app profile to avoid browser session-restore duplicate tabs; if no supported browser is available, startup falls back to the system default browser. `controller.py` contains cue-list logic and does not launch the interface.

Run checks:

```sh
python3 -m py_compile V3_5/sender/*.py
python3 -m unittest discover -s V3_5/sender/tests
```

The sender writes local runtime state to `V3_5/sender/.primus_state.json`. That file is generated during tests and should not be committed.

## Core Data Model

### Output Types

`state.py` owns the sender-side output type table:

- `OUTPUT_TYPES` maps sender keys to pixel count and layout.
- `LOOK_OUTPUT_TYPES` maps numeric type IDs to sender keys.

`LOOK_OUTPUT_TYPES` index order must match firmware `OutputType` enum values in `V3_5/Arduino/primusV3_receiver/config.h`.

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
- `parse_node_capabilities()` parses V3.5/V3.1 capability tags.
- `parse_node_outputs()` converts Node Report output tokens into sender output configs.

V3.5 Node Report example:

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

Firmware upload jobs wrap `V3_5/Arduino/upload.sh` and are source-run only in the first pass. The Firmware tab presents the simple path: choose firmware version, refresh/select an available USB device or all devices, independently enable default device-name and/or WiFi overrides, then compile or upload while watching the output window. The API still supports the script's maintenance actions where useful. It returns `409` when another firmware job is running, `400` for invalid action/profile/port data, and `503` when the upload script, `bash`, `python3`, or `arduino-cli` is unavailable. WiFi passwords must not appear in API responses or web UI output.

Sender network settings live in `network_settings.py` and persist under the `sender_network` key in `.primus_state.json`. Host IP apply/revert is macOS-only in the first implementation and uses stdlib `subprocess` with `/usr/sbin/networksetup`; no external Python packages are used. Art-Net discovery accepts the selected interface record, and `ArtNetSender` plus one-shot control helpers can bind outgoing UDP sockets to the selected source IP. Settings recommends active Ethernet/USB-Ethernet for the common show-router workflow, returns per-interface CIDR/usable-range summaries, and validates static sender profiles so the IP is a usable host and the gateway is in the same subnet. WiFi preferences and the controller/show-router network remain SSID-aware as an advanced path; placeholder SSID values such as `<redacted>` and `<data> 0x00` are ignored.

## Web UI Files

The UI is static Alpine.js:

```text
V3_5/sender/web/
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
python3 V3_5/sender/run.py --port 0
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
rm -f V3_5/sender/.primus_state.json
```

## Test Coverage

Current test coverage is focused on Art-Net capability parsing and discovery compatibility:

```text
V3_5/sender/tests/test_artnet_capabilities.py
```

Add tests when changing:

- Node Report parsing.
- Output token parsing.
- Hardware profile fallback behavior.
- Capability flag behavior.
- Output type IDs.
