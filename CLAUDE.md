# CLAUDE.md — PrimusV3 Agent Context

## What is this project?

PrimusV3 is a WiFi LED lighting controller for live performance costumes. A Python sender drives ESP32 receiver nodes over Art-Net (UDP 6454). The sender has a built-in web UI, clip/look workflow, and effects engine. The current V3.5 track supports reflashed V1, V2, and V3.1 hardware with one shared Art-Net protocol.

## Active version: V3.5

V3.5 is the active compatibility track under `V3_5/`. V3.1 remains the previous modular track under `V3_1/`, and the original V3.0 single-file sender is archived but still functional.

## Repository layout

### V3.5 Sender (`V3_5/sender/`)
- `run.py` — Entry point. Starts HTTP server, Art-Net listener, and animation loop.
- `state.py` — Core state management, animation loop (`tick()`), device tracking, playback source switching.
- `server.py` — HTTP server (port 8080). Serves static web UI and 38 JSON API endpoints.
- `effects.py` — 10 built-in effects computed per frame into pixel buffers.
- `clips.py` — Clip CRUD, preview computation. Clips stored as JSON in `V3_5/sender/clips/`.
- `mixer.py` — Look Mixer logic, crossfade between looks.
- `controller.py` — Cue Controller for sequential look playback with transitions.
- `artnet.py` — Art-Net protocol: ArtPoll, ArtPollReply, ArtDmx, ArtAddress, ArtOutputConfig, ArtIPConfig, and capability-tag parsing from ArtPollReply Node Report.
- `web/` — Static web UI files (Alpine.js SPA):
  - `web/index.html` — Single-page app shell
  - `web/js/` — Alpine.js components (look-mixer.js, etc.)
  - `web/css/style.css` — All styling

### V3.5 Sender Data
- `V3_5/sender/clips/` — preset clips as JSON files
- `V3_5/sender/looks/` — Saved looks as JSON files
- `V3_5/sender/cues.json` — Cue list for the controller

### V3.0 Sender (archived)
- `sender/led_controller.py` — Original single-file Python sender (~1800 lines). Embedded HTML/JS/CSS web UI.

### Receiver Firmware
- `V3_5/Arduino/primusV3_receiver/` — shared V3.5 firmware with `-v1`, `-v2`, and `-v3` upload profiles.
  - `config.h` — Source of truth for output types, pins, network config.
  - `primusV3_receiver.ino` — Main sketch: WiFi, Art-Net parsing, NeoPixel output.
  - `display.h` — TFT display screens.
  - `buttons.h` — Button input handling.
- `V3_5/Arduino/upload.sh` — arduino-cli build/upload script.

### Docs
- `API_REFERENCE.md` — Full protocol and HTTP API documentation.
- `README.md` — Project overview, V3.5 launch/upload quick start, and documentation map.
- `V3_5/FIRMWARE_DEVELOPMENT.md` — Current firmware profile and upload workflow reference.
- `V3_5/SENDER_DEVELOPMENT.md` — Current sender architecture and API behavior reference.

## V3.5 Concepts

- **Clip**: A saved effect configuration (effect, colors, speed, playback mode) for a specific output type. Stored as JSON.
- **Look**: A set of 2 active output slots, each with a clip assignment. Defines what all devices display simultaneously.
- **Playback sources**: `designer` (live editing), `mixer` (crossfade between looks), `controller` (cue-driven sequential playback), `idle` (black/off).
- **Output types**: `short_strip` (30px), `long_strip` (72px), `grid` (8x8=64px), `small_grid` (4x8=32px), `extra_long_strip` (122px).

## Critical sync points

The sender and receiver must agree on:
- **Output type IDs**: `LOOK_OUTPUT_TYPES` list (Python) indices = `OutputType` enum (C++) values
- **Pixel counts**: `OUTPUT_TYPES` dict (Python, in state.py) = `OUTPUT_TYPE_TABLE` (C++)
- **Custom opcode 0x8100**: ArtOutputConfig for runtime output type changes
- **Custom opcode 0x8200**: ArtIPConfig for static IP / DHCP configuration
- **Discovery capability tag**: `PV3CAP1|...|B:<profile>|F:RIOH` in ArtPollReply Node Report
- **Feature flags**: `R` rename, `H` identify flash, `I` IP config, `O` output config
- **FPS telemetry**: 7-byte `PFP` packets on UDP 6455

## How to build and run

**V3.5 Sender**: `python3 V3_5/sender/run.py` — opens web UI at http://127.0.0.1:8080 by default
**V3.0 Sender**: `python3 V3_0/sender/led_controller.py` — opens web UI at http://localhost:8080
**Firmware**: `V3_5/Arduino/upload.sh -v1|-v2|-v3 [port ...]` or `--all` — compiles and uploads selected profile

## Conventions

- No external Python dependencies. Stdlib only.
- Table-driven output types on both sides. Never hardcode pixel counts.
- V3.5 web UI is static files under `V3_5/sender/web/` (Alpine.js, no build step).
- Device-control UI is capability-aware: rename, hello, IP config, and output config are enabled from discovery capabilities, with legacy Primus fallback for older firmware.
- Grid layout is always serpentine (even rows L->R, odd rows R->L).
- RGB color order, 3 bytes per pixel.
- Custom Art-Net opcodes use 0x8000+ range.
- Device names stored in ESP32 NVS via ArtAddress opcode.
- Static IP configuration stored in ESP32 NVS via custom ArtIPConfig opcode (0x8200). Defaults to DHCP.

## Effects

none, solid, pulse, linear, constrainbow, rainbow, knight_rider, chase, radial (grid), spiral (grid)

## V3.5 API endpoints

**GET**: `/` (web UI), `/api/state`, `/api/clips`, `/api/clips/<id>`, `/api/looks`, `/api/looks/<id>`, `/api/cues`
**POST (devices)**: `/api/update`, `/api/connect`, `/api/disconnect`, `/api/connect_all`, `/api/disconnect_all`, `/api/discover`, `/api/add_discovered`, `/api/add_manual`, `/api/remove_device`, `/api/rename_node`, `/api/hello_device`, `/api/set_device_ip`, `/api/revert_device_dhcp`, `/api/set_playback_source`
**POST (clips)**: `/api/clip/preview`, `/api/clips/save`, `/api/clips/save_single`
**POST (looks/mixer)**: `/api/looks/save`, `/api/mixer/frame`, `/api/mixer/preview`, `/api/mixer/update`, `/api/mixer/stop_preview`, `/api/device_groups`
**POST (cues/controller)**: `/api/cues` (save), `/api/cues/go`, `/api/cues/stop`, `/api/cues/goto`, `/api/controller/activate`, `/api/controller/blackout`
**DELETE**: `/api/clips/<id>`, `/api/looks/<id>`, `/api/device_groups/<id>`

## Hardware

- V1 Huzzah32: direct NeoPixel outputs on GPIO32/GPIO12, LED_BUILTIN WiFi indicator
- V2 ESP32 Feather: direct NeoPixel outputs on GPIO32/GPIO12, onboard NeoPixel WiFi indicator
- V3.1 Reverse TFT Feather: NeoPXL8 FeatherWing outputs 6/7 on GPIO14/GPIO15, 240x135 ST7789 TFT, D0/D1 buttons
- Max 122 LEDs per port, 2 active ports per node
