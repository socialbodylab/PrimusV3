# CLAUDE.md — PrimusV3 Agent Context

## What is this project?

PrimusV3 is a WiFi LED lighting controller for live performance costumes. A Python sender drives ESP32-S3 receiver nodes over Art-Net (UDP 6454). The sender has a built-in web UI and effects engine. The receivers drive NeoPixels via NeoPXL8 on 3 physical outputs.

## Repository layout

- `sender/led_controller.py` — Single-file Python sender (~1800 lines). Embedded HTML/JS/CSS web UI, HTTP server (port 8080), Art-Net engine, 10 built-in effects, Look architecture. Zero external deps.
- `Arduino/primusV3_receiver/` — ESP32-S3 Reverse TFT Feather firmware. `config.h` is the source of truth for output types. `display.h` manages the TFT. `buttons.h` handles physical buttons.
- `Arduino/upload.sh` — arduino-cli build/upload script.
- `API_REFERENCE.md` — Full protocol documentation.
- `DEPLOYMENT_STRATEGY.md` — Packaging plan.

## Critical sync points

The sender and receiver must agree on:
- **Output type IDs**: `LOOK_OUTPUT_TYPES` list (Python) indices = `OutputType` enum (C++) values
- **Pixel counts**: `OUTPUT_TYPES` dict (Python) = `OUTPUT_TYPE_TABLE` (C++)
- **Custom opcode 0x8100**: ArtOutputConfig for runtime output type changes
- **FPS telemetry**: 7-byte `PFP` packets on UDP 6455

## How to build and run

**Sender**: `python3 sender/led_controller.py` — opens web UI at http://localhost:8080
**Firmware**: `cd Arduino && ./upload.sh` — auto-detects ESP32-S3 port, compiles, uploads

## Conventions

- No external Python dependencies. Stdlib only.
- Table-driven output types on both sides. Never hardcode pixel counts.
- Embedded web UI — HTML/CSS/JS are Python string literals in led_controller.py.
- Grid layout is always serpentine (even rows L→R, odd rows R→L).
- RGB color order, 3 bytes per pixel.
- Custom Art-Net opcodes use 0x8000+ range.
- Device names stored in ESP32 NVS via ArtAddress opcode.

## Effects

none, solid, pulse, linear, constrainbow, rainbow, knight_rider, chase, radial (grid), spiral (grid)

## API endpoints

GET `/` (web UI), GET `/api/state` (full state JSON)
POST: `/api/update`, `/api/connect`, `/api/disconnect`, `/api/connect_all`, `/api/disconnect_all`, `/api/discover`, `/api/add_discovered`, `/api/remove_device`, `/api/rename_node`

## Hardware

- ESP32-S3 Reverse TFT Feather (Adafruit)
- NeoPXL8 level-shifted outputs on GPIO 16/17/18 (ports A2/A1/A0)
- 240×135 ST7789 TFT display
- D0 button: cycle screens, D1 button: toggle test mode
- Max 72 LEDs per port, 3 ports = 216 LEDs max per node
