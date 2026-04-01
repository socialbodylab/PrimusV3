# PrimusV3 — Copilot Instructions

## Project Overview

PrimusV3 is a WiFi-controlled LED lighting system for live performance costumes. It consists of:

1. **Sender** (`sender/led_controller.py`) — A Python 3 application with an embedded web UI that controls LED nodes over Art-Net. Zero external dependencies.
2. **Receiver firmware** (`Arduino/primusV3_receiver/`) — ESP32-S3 Reverse TFT Feather firmware using NeoPXL8 for level-shifted NeoPixel output across 3 physical ports.

## Architecture

### Sender (Python)

- **Single file**: `led_controller.py` (~1800 lines) contains the HTTP server, Art-Net engine, effects engine, and the full HTML/CSS/JS web UI as embedded strings.
- **HTTP server**: `http.server` on port 8080. Serves the web UI at `/` and a JSON API under `/api/`.
- **Art-Net transport**: Standard UDP on port 6454. Supports ArtPoll, ArtPollReply, ArtDmx, ArtAddress, and custom ArtOutputConfig (0x8100).
- **Look architecture**: Animation state is computed once per frame as a "Look" (list of 3 output slots), then sent identically to all connected devices. Each slot has its own output type, effect, colors, speed, and parameters.
- **Effects**: Computed in `compute_look()`. Each effect is a function that fills a pixel buffer. Grid effects use x/y coordinates; strip effects use linear position.
- **Persistence**: `.primus_state.json` stores output type selections across restarts.

### Receiver (Arduino/C++)

- **config.h**: Single source of truth for output types. `OUTPUT_TYPE_TABLE[]` defines pixel count, bytes-per-pixel, layout, and grid dimensions. The `OutputType` enum indices must match the sender's `LOOK_OUTPUT_TYPES` list.
- **primusV3_receiver.ino**: Main sketch — WiFi connection, Art-Net packet parsing, NeoPixel output, FPS telemetry, ArtPollReply broadcasting.
- **display.h**: TFT display management — connection screen, status screen, error screen. Uses `headerName()` for custom device name (stored in NVS).
- **buttons.h**: D0 (screen cycle) and D1 (test mode toggle) button handling.
- **upload.sh**: Build/upload script using `arduino-cli`.

## Key Constants That Must Stay in Sync

| Concept | Sender (`led_controller.py`) | Receiver (`config.h`) |
|---------|-----|---------|
| Output type IDs | `LOOK_OUTPUT_TYPES` list indices | `OutputType` enum values |
| Output type pixels | `OUTPUT_TYPES` dict → `pixels` | `OUTPUT_TYPE_TABLE` → `pixels` |
| ArtOutputConfig opcode | `0x8100` | `ARTNET_OPCODE_OUTPUT_CONFIG = 0x8100` |
| Max LEDs per port | Not enforced | `MAX_LEDS_PER_PORT = 72` |
| FPS telemetry magic | `FPS_MAGIC = b"PFP"` | `PFP` in `sendFpsTelemetry()` |
| FPS telemetry port | `FPS_PORT = 6455` | `FPS_PORT = 6455` |

## Coding Conventions

- **No external dependencies** in the sender. Everything uses Python stdlib.
- **Embedded web UI**: HTML/CSS/JS is defined as Python string literals inside `led_controller.py`. The UI and server are one file.
- **Table-driven output types**: Both sender and receiver derive pixel counts, layouts, and byte sizes from lookup tables. Never hardcode pixel counts — add/edit table rows instead.
- **Art-Net compliance**: Use standard opcodes where possible. Custom opcodes use the 0x8000+ range.
- **Grid pixel order**: Always serpentine (even rows L→R, odd rows R→L). The sender computes serpentine mapping; the receiver expects pre-mapped data.
- **RGB color order**: 3 bytes per pixel, always RGB. No RGBW support currently.

## Common Tasks

### Adding a new effect
1. Add the effect name to the `EFFECTS` list in `led_controller.py`
2. Add a computation branch in `compute_look()` that fills the pixel buffer
3. If the effect has custom parameters, add them to the API update handler and the web UI controls

### Adding a new output type
1. Add enum value in `config.h` → `OutputType`
2. Add row in `config.h` → `OUTPUT_TYPE_TABLE[]`
3. Add entry in `led_controller.py` → `OUTPUT_TYPES` dict
4. Add name in `led_controller.py` → `LOOK_OUTPUT_TYPES` list (index must match enum)

### Renaming a device
- Web UI sends `POST /api/rename_node` → sender sends ArtAddress packet → receiver stores in NVS, updates TFT, broadcasts ArtPollReply

## File Structure

```
PrimusV3/
├── Arduino/
│   ├── upload.sh                    # Build/upload script (arduino-cli)
│   └── primusV3_receiver/
│       ├── primusV3_receiver.ino    # Main firmware sketch
│       ├── config.h                 # Output types, pins, network config
│       ├── display.h                # TFT display screens
│       └── buttons.h                # Button input handling
├── sender/
│   └── led_controller.py           # Sender + web UI (single file)
├── API_REFERENCE.md                 # Full network protocol docs
├── DEPLOYMENT_STRATEGY.md           # Packaging and distribution plan
└── .github/
    └── copilot-instructions.md      # This file
```
