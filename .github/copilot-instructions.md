# PrimusV3 — Copilot Instructions

## Project Overview

PrimusV3 is a WiFi-controlled LED lighting system for live performance costumes. It consists of:

1. **V3.6 Sender** (`V3_6/sender/`) — The active compatibility-track Python 3 sender with HTTP API, Art-Net transport, clip/look workflow, cue controller, OSC input, firmware upload panel, and a static Alpine.js web UI. Zero external dependencies.
2. **V3.6 Receiver firmware** (`V3_6/Arduino/primusV3_receiver/`) — Shared firmware with build profiles for V1 Huzzah32, V2 Feather, and V3.1 Reverse TFT hardware.
3. **Historical tracks** (`V3_5/`, `V3_1/`, `V3_0/`) — Older versions kept for reference. Do new sender, firmware, packaging, and documentation work in `V3_6/` unless the user explicitly asks for an older track.

## Architecture

### Sender (Python)

- **Active codepath**: `run.py`, `state.py`, `server.py`, `artnet.py`, `mixer.py`, `controller.py`, `sharing.py`, `firmware.py`, `network_settings.py`, and `web/` under `V3_6/sender/`.
- **HTTP server**: `http.server` on an auto-selected port. Serves the web UI at `/` and a JSON API under `/api/`.
- **Art-Net transport**: Standard UDP on port 6454. Supports ArtPoll, ArtPollReply, ArtDmx, ArtAddress, and custom ArtOutputConfig (0x8100) and ArtIPConfig (0x8200).
- **Discovery contract**: ArtPollReply Node Report carries `PV3CAP1|port:type_id:universe|B:profile|F:RIOH`, which the sender uses to determine hardware profile and advertised control capabilities. Older Primus firmware falls back to legacy detection.
- **Look architecture**: Animation state is computed once per frame as a Look (list of 2 active output slots), then sent to connected devices.
- **Brightness**: Sender-side Clip, Look, and Timeline segment brightness scaling only. Receiver LED driver brightness stays fixed at 255.
- **Persistence**: `.primus_state.json` stores output type selections, saved device names, and sender network settings across restarts.

### Receiver (Arduino/C++)

- **config.h**: Single source of truth for output types. `OUTPUT_TYPE_TABLE[]` defines pixel count, bytes-per-pixel, layout, and grid dimensions. The `OutputType` enum indices must match the sender's `LOOK_OUTPUT_TYPES` list.
- **primusV3_receiver.ino**: Main sketch — WiFi connection, Art-Net packet parsing, NeoPixel output, FPS telemetry, capability-tagged ArtPollReply broadcasting.
- **display.h**: TFT display management — connection screen, status screen, error screen. Uses `headerName()` for custom device name (stored in NVS).
- **buttons.h**: D0 (screen cycle) and D1 (test mode toggle) button handling.
- **upload.sh**: Build/upload script using `arduino-cli`.

## Key Constants That Must Stay in Sync

| Concept | Sender (`V3_6/sender/*`) | Receiver (`config.h`) |
|---------|-----|---------|
| Output type IDs | `LOOK_OUTPUT_TYPES` list indices | `OutputType` enum values |
| Output type pixels | `OUTPUT_TYPES` dict → `pixels` | `OUTPUT_TYPE_TABLE` → `pixels` |
| ArtOutputConfig opcode | `0x8100` | `ARTNET_OPCODE_OUTPUT_CONFIG = 0x8100` |
| ArtIPConfig opcode | `0x8200` | `ARTNET_OPCODE_IP_CONFIG = 0x8200` |
| Discovery capability tag | `PV3CAP1` parser in `V3_6/sender/artnet.py` | `NODE_CAPS_PREFIX` in `config.h` |
| Discovery feature flags | `R/H/I/O` capability parsing | `F:RIOH` emitted in ArtPollReply Node Report |
| Max LEDs per port | Not enforced | `MAX_LEDS_PER_PORT = 122` |
| FPS telemetry magic | `FPS_MAGIC = b"PFP"` | `PFP` in `sendFpsTelemetry()` |
| FPS telemetry port | `FPS_PORT = 6455` | `FPS_PORT = 6455` |

## Coding Conventions

- **No external dependencies** in the sender. Everything uses Python stdlib.
- **V3.6 web UI**: Static HTML/CSS/JS under `V3_6/sender/web/`. The 0.7 workshop profile is UI-only; do not remove output types from sender state, API, or firmware.
- **Table-driven output types**: Both sender and receiver derive pixel counts, layouts, and byte sizes from lookup tables. Never hardcode pixel counts — add/edit table rows instead.
- **Art-Net compliance**: Use standard opcodes where possible. Custom opcodes use the 0x8000+ range.
- **Capability-aware controls**: Rename, hello, IP config, and output config are exposed from discovery capabilities first, then legacy Primus fallback.
- **Grid pixel order**: Always serpentine (even rows L→R, odd rows R→L). The sender computes serpentine mapping; the receiver expects pre-mapped data.
- **RGB color order**: 3 bytes per pixel, always RGB. No RGBW support currently.

## Packaging

- Build on the target OS with `V3_6/build_sender_app.py`.
- macOS release docs: `V3_6/PACKAGING.md`
- Windows handoff: `V3_6/WINDOWS_BUILD.md`
- One-time notary credential setup: `V3_6/scripts/setup_notary_profile.sh`
- Packaged macOS FPS validation must launch through Finder/LaunchServices, not by running `Contents/MacOS/PrimusCentral` directly.

## Common Tasks

### Adding a new effect
1. Add the effect function and `EFFECTS` entry in `V3_6/sender/effects.py`
2. Thread any new effect parameters through `V3_6/sender/state.py` and `V3_6/sender/server.py` as needed
3. Add the corresponding UI controls in `V3_6/sender/web/`

### Adding a new output type
1. Add enum value in `config.h` → `OutputType`
2. Add row in `config.h` → `OUTPUT_TYPE_TABLE[]`
3. Add entry in `V3_6/sender/state.py` → `OUTPUT_TYPES` dict
4. Add name in `V3_6/sender/state.py` → `LOOK_OUTPUT_TYPES` list (index must match enum)

### Renaming a device
- Web UI sends `POST /api/rename_node` → sender sends ArtAddress packet → receiver stores in NVS, updates TFT, broadcasts ArtPollReply

### Device control discovery
- ArtPollReply Node Report carries `PV3CAP1|...|B:<profile>|F:RIOH`
- `R` = remote rename, `H` = identify flash, `I` = IP config, `O` = output config
- Sender UI/API should treat these as the source of truth, with legacy Primus fallback for older firmware

## File Structure

```
PrimusV3/
├── V3_6/
│   ├── Arduino/
│   │   ├── upload.sh
│   │   └── primusV3_receiver/
│   ├── sender/
│   │   ├── run.py
│   │   ├── state.py
│   │   ├── artnet.py
│   │   └── web/
│   ├── build_sender_app.py
│   ├── PACKAGING.md
│   └── WINDOWS_BUILD.md
├── V3_5/                                # Historical compatibility track
├── V3_1/                                # Previous modular track
├── V3_0/
│   └── sender/
│       └── led_controller.py           # Archived single-file sender
├── API_REFERENCE.md
└── .github/
    └── copilot-instructions.md          # This file
```
