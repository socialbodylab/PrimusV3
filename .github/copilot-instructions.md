# PrimusV3 — Copilot Instructions

## Project Overview

PrimusV3 is a WiFi-controlled LED lighting system for live performance costumes. It consists of:

1. **V3.1 Sender** (`V3_1/sender/`) — The active modular Python 3 sender with HTTP API, Art-Net transport, clip/look workflow, and a static Alpine.js web UI. Zero external dependencies.
2. **V3.0 Sender** (`V3_0/sender/led_controller.py`) — Archived single-file sender, still useful for historical reference.
3. **Receiver firmware** (`V3_1/Arduino/primusV3_receiver/`) — ESP32-S3 Reverse TFT Feather firmware using NeoPXL8 FeatherWing fixed outputs 6 and 7 for the current 2-output hardware configuration.

## Architecture

### Sender (Python)

- **Active codepath**: `run.py`, `state.py`, `server.py`, `artnet.py`, `mixer.py`, `controller.py`, and `web/` under `V3_1/sender/`.
- **HTTP server**: `http.server` on an auto-selected port. Serves the web UI at `/` and a JSON API under `/api/`.
- **Art-Net transport**: Standard UDP on port 6454. Supports ArtPoll, ArtPollReply, ArtDmx, ArtAddress, and custom ArtOutputConfig (0x8100) and ArtIPConfig (0x8200).
- **Discovery contract**: ArtPollReply Node Report carries `PV3CAP1|port:type_id:universe|F:RIOH`, which the sender uses to determine advertised control capabilities. Older Primus firmware falls back to legacy detection.
- **Look architecture**: Animation state is computed once per frame as a Look (list of 2 active output slots in the current V3.1 receiver config), then sent to connected devices.
- **Persistence**: `.primus_state.json` stores output type selections and saved device names across restarts.

### Receiver (Arduino/C++)

- **config.h**: Single source of truth for output types. `OUTPUT_TYPE_TABLE[]` defines pixel count, bytes-per-pixel, layout, and grid dimensions. The `OutputType` enum indices must match the sender's `LOOK_OUTPUT_TYPES` list.
- **primusV3_receiver.ino**: Main sketch — WiFi connection, Art-Net packet parsing, NeoPixel output, FPS telemetry, capability-tagged ArtPollReply broadcasting.
- **display.h**: TFT display management — connection screen, status screen, error screen. Uses `headerName()` for custom device name (stored in NVS).
- **buttons.h**: D0 (screen cycle) and D1 (test mode toggle) button handling.
- **upload.sh**: Build/upload script using `arduino-cli`.

## Key Constants That Must Stay in Sync

| Concept | Sender (`V3_1/sender/*`) | Receiver (`config.h`) |
|---------|-----|---------|
| Output type IDs | `LOOK_OUTPUT_TYPES` list indices | `OutputType` enum values |
| Output type pixels | `OUTPUT_TYPES` dict → `pixels` | `OUTPUT_TYPE_TABLE` → `pixels` |
| ArtOutputConfig opcode | `0x8100` | `ARTNET_OPCODE_OUTPUT_CONFIG = 0x8100` |
| ArtIPConfig opcode | `0x8200` | `ARTNET_OPCODE_IP_CONFIG = 0x8200` |
| Discovery capability tag | `PV3CAP1` parser in `V3_1/sender/artnet.py` | `NODE_CAPS_PREFIX` in `config.h` |
| Discovery feature flags | `R/H/I/O` capability parsing | `F:RIOH` emitted in ArtPollReply Node Report |
| Max LEDs per port | Not enforced | `MAX_LEDS_PER_PORT = 72` |
| FPS telemetry magic | `FPS_MAGIC = b"PFP"` | `PFP` in `sendFpsTelemetry()` |
| FPS telemetry port | `FPS_PORT = 6455` | `FPS_PORT = 6455` |

## Coding Conventions

- **No external dependencies** in the sender. Everything uses Python stdlib.
- **V3.1 web UI**: Static HTML/CSS/JS under `V3_1/sender/web/`. V3.0 keeps the older embedded single-file UI.
- **Table-driven output types**: Both sender and receiver derive pixel counts, layouts, and byte sizes from lookup tables. Never hardcode pixel counts — add/edit table rows instead.
- **Art-Net compliance**: Use standard opcodes where possible. Custom opcodes use the 0x8000+ range.
- **Capability-aware controls**: Rename, hello, IP config, and output config are exposed from discovery capabilities first, then legacy Primus fallback.
- **Grid pixel order**: Always serpentine (even rows L→R, odd rows R→L). The sender computes serpentine mapping; the receiver expects pre-mapped data.
- **RGB color order**: 3 bytes per pixel, always RGB. No RGBW support currently.

## Common Tasks

### Adding a new effect
1. Add the effect function and `EFFECTS` entry in `V3_1/sender/effects.py`
2. Thread any new effect parameters through `V3_1/sender/state.py` and `V3_1/sender/server.py` as needed
3. Add the corresponding UI controls in `V3_1/sender/web/`

### Adding a new output type
1. Add enum value in `config.h` → `OutputType`
2. Add row in `config.h` → `OUTPUT_TYPE_TABLE[]`
3. Add entry in `V3_1/sender/state.py` → `OUTPUT_TYPES` dict
4. Add name in `V3_1/sender/state.py` → `LOOK_OUTPUT_TYPES` list (index must match enum)

### Renaming a device
- Web UI sends `POST /api/rename_node` → sender sends ArtAddress packet → receiver stores in NVS, updates TFT, broadcasts ArtPollReply

### Device control discovery
- ArtPollReply Node Report carries `PV3CAP1|...|F:RIOH`
- `R` = remote rename, `H` = identify flash, `I` = IP config, `O` = output config
- Sender UI/API should treat these as the source of truth, with legacy Primus fallback for older firmware

## File Structure

```
PrimusV3/
├── V3_1/
│   ├── Arduino/
│   │   ├── upload.sh                    # Build/upload script (arduino-cli)
│   │   └── primusV3_receiver/
│   │       ├── primusV3_receiver.ino    # Main firmware sketch
│   │       ├── config.h                 # Output types, pins, network config
│   │       ├── display.h                # TFT display screens
│   │       └── buttons.h                # Button input handling
│   └── sender/
│       ├── run.py                       # Entry point + HTTP server startup
│       ├── state.py                     # Runtime state and device management
│       ├── artnet.py                    # Art-Net transport + capability parsing
│       └── web/                         # Static Alpine.js UI
├── V3_0/
│   ├── Arduino/
│   │   ├── upload.sh
│   │   └── primusV3_receiver/
│   └── sender/
│       └── led_controller.py           # Archived single-file sender
├── API_REFERENCE.md                     # Full network protocol docs
├── DEPLOYMENT_STRATEGY.md               # Packaging and distribution plan
└── .github/
    └── copilot-instructions.md          # This file
```
