# CLAUDE.md — PrimusV3 Agent Context

## What is this project?

PrimusV3 is a WiFi LED lighting controller for live performance costumes. A Python sender drives ESP32-S3 receiver nodes over Art-Net (UDP 6454). The sender has a built-in web UI, clip/look workflow, and effects engine. The receivers drive NeoPixels via NeoPXL8 on 3 physical outputs.

## Active version: V3.1

V3.1 is the active version under `V3_1/`. The original V3.0 single-file sender (`sender/led_controller.py`) is archived but still functional.

## Repository layout

### V3.1 Sender (`V3_1/sender/`)
- `run.py` — Entry point. Starts HTTP server, Art-Net listener, and animation loop.
- `state.py` — Core state management, animation loop (`tick()`), device tracking, playback source switching.
- `server.py` — HTTP server (port 8080). Serves static web UI and 27 JSON API endpoints.
- `effects.py` — 10 built-in effects computed per frame into pixel buffers.
- `clips.py` — Clip CRUD, preview computation. Clips stored as JSON in `V3_1/sender/clips/`.
- `mixer.py` — Look Mixer logic, crossfade between looks.
- `controller.py` — Cue Controller for sequential look playback with transitions.
- `artnet.py` — Art-Net protocol: ArtPoll, ArtPollReply, ArtDmx, ArtAddress, ArtOutputConfig.
- `web/` — Static web UI files (Alpine.js SPA):
  - `web/index.html` — Single-page app shell
  - `web/js/` — Alpine.js components (look-mixer.js, etc.)
  - `web/css/style.css` — All styling

### V3.1 Sender Data
- `V3_1/sender/clips/` — 114 preset clips as JSON files (38 per output type)
- `V3_1/sender/looks/` — Saved looks as JSON files
- `V3_1/sender/cues.json` — Cue list for the controller

### V3.0 Sender (archived)
- `sender/led_controller.py` — Original single-file Python sender (~1800 lines). Embedded HTML/JS/CSS web UI.

### Receiver Firmware
- `Arduino/primusV3_receiver/` — ESP32-S3 firmware. Shared by V3.0 and V3.1.
  - `config.h` — Source of truth for output types, pins, network config.
  - `primusV3_receiver.ino` — Main sketch: WiFi, Art-Net parsing, NeoPixel output.
  - `display.h` — TFT display screens.
  - `buttons.h` — Button input handling.
- `Arduino/upload.sh` — arduino-cli build/upload script.

### Docs
- `API_REFERENCE.md` — Full protocol and HTTP API documentation.
- `DEPLOYMENT_STRATEGY.md` — Packaging plan.

## V3.1 Concepts

- **Clip**: A saved effect configuration (effect, colors, speed, playback mode) for a specific output type. Stored as JSON.
- **Look**: A set of 3 output slots, each with a clip assignment. Defines what all devices display simultaneously.
- **Playback sources**: `designer` (live editing), `mixer` (crossfade between looks), `controller` (cue-driven sequential playback), `idle` (black/off).
- **Output types**: `short_strip` (30px), `long_strip` (72px), `grid` (8x8=64px).

## Critical sync points

The sender and receiver must agree on:
- **Output type IDs**: `LOOK_OUTPUT_TYPES` list (Python) indices = `OutputType` enum (C++) values
- **Pixel counts**: `OUTPUT_TYPES` dict (Python, in state.py) = `OUTPUT_TYPE_TABLE` (C++)
- **Custom opcode 0x8100**: ArtOutputConfig for runtime output type changes
- **FPS telemetry**: 7-byte `PFP` packets on UDP 6455

## How to build and run

**V3.1 Sender**: `python3 V3_1/sender/run.py` — opens web UI at http://localhost:8080
**V3.0 Sender**: `python3 sender/led_controller.py` — opens web UI at http://localhost:8080
**Firmware**: `cd Arduino && ./upload.sh` — auto-detects ESP32-S3 port, compiles, uploads

## Conventions

- No external Python dependencies. Stdlib only.
- Table-driven output types on both sides. Never hardcode pixel counts.
- V3.1 web UI is static files under `V3_1/sender/web/` (Alpine.js, no build step).
- Grid layout is always serpentine (even rows L->R, odd rows R->L).
- RGB color order, 3 bytes per pixel.
- Custom Art-Net opcodes use 0x8000+ range.
- Device names stored in ESP32 NVS via ArtAddress opcode.

## Effects

none, solid, pulse, linear, constrainbow, rainbow, knight_rider, chase, radial (grid), spiral (grid)

## V3.1 API endpoints (27 total)

**GET**: `/` (web UI), `/api/state`, `/api/clips`, `/api/clips/<id>`, `/api/looks`, `/api/looks/<id>`, `/api/cues`
**POST (devices)**: `/api/update`, `/api/connect`, `/api/disconnect`, `/api/connect_all`, `/api/disconnect_all`, `/api/discover`, `/api/add_discovered`, `/api/add_manual`, `/api/remove_device`, `/api/rename_node`, `/api/hello_device`, `/api/set_playback_source`
**POST (clips)**: `/api/clip/preview`, `/api/clips/save`, `/api/clips/save_single`
**POST (looks/mixer)**: `/api/looks/save`, `/api/mixer/preview`, `/api/device_groups/save`
**POST (cues)**: `/api/cues` (save), `/api/cues/go`
**DELETE**: `/api/clips/<id>`, `/api/looks/<id>`, `/api/device_groups/<id>`

## Hardware

- ESP32-S3 Reverse TFT Feather (Adafruit)
- NeoPXL8 level-shifted outputs on GPIO 16/17/18 (ports A2/A1/A0)
- 240x135 ST7789 TFT display
- D0 button: cycle screens, D1 button: toggle test mode
- Max 72 LEDs per port, 3 ports = 216 LEDs max per node
