# CLAUDE.md — PrimusV3 Agent Context

## What is this project?

PrimusV3 is a WiFi LED lighting controller for live performance costumes. A Python sender drives ESP32-S3 receiver nodes over Art-Net (UDP 6454). The sender has a built-in web UI, clip/look workflow, and effects engine. The receivers drive NeoPixels via NeoPXL8 on 3 physical outputs.

## Active versions

- **V3.1** — Active sender + receiver under `V3_1/`. The original V3.0 single-file sender (`sender/led_controller.py`) is archived but still functional.
- **V3.2** — Active audio receiver firmware under `V3_2/`. Firmware-only variant; there is no V3.2 sender yet. Audio nodes run V3.2 firmware and are controlled by the V3.1 sender for LED, plus direct Art-Net opcodes for audio and FTP.

## Repository layout

### V3.1 Sender (`V3_1/sender/`)
- `run.py` — Entry point. Starts HTTP server, Art-Net listener, and animation loop.
- `state.py` — Core state management, animation loop (`tick()`), device tracking, playback source switching.
- `server.py` — HTTP server (port 8080). Serves static web UI and 29 JSON API endpoints.
- `effects.py` — 10 built-in effects computed per frame into pixel buffers.
- `clips.py` — Clip CRUD, preview computation. Clips stored as JSON in `V3_1/sender/clips/`.
- `mixer.py` — Look Mixer logic, crossfade between looks.
- `controller.py` — Cue Controller for sequential look playback with transitions.
- `artnet.py` — Art-Net protocol: ArtPoll, ArtPollReply, ArtDmx, ArtAddress, ArtOutputConfig.
- `web/` — Static web UI files (Alpine.js SPA):
  - `web/index.html` — Single-page app shell
  - `web/js/` — Alpine.js components (look-mixer.js, look-controller.js, audio-panel.js)
  - `web/css/style.css` — All styling

### V3.1 Sender Data
- `V3_1/sender/clips/` — 114 preset clips as JSON files (38 per output type)
- `V3_1/sender/looks/` — Saved looks as JSON files
- `V3_1/sender/cues.json` — Cue list for the controller

### V3.0 Sender (archived)
- `sender/led_controller.py` — Original single-file Python sender (~1800 lines). Embedded HTML/JS/CSS web UI.

### Receiver Firmware (V3.1)
- `V3_1/Arduino/primusV3_receiver/` — ESP32-S3 firmware. Shared by V3.0 and V3.1.
  - `config.h` — Source of truth for output types, pins, network config.
  - `primusV3_receiver.ino` — Main sketch: WiFi, Art-Net parsing, NeoPixel output.
  - `display.h` — TFT display screens.
  - `buttons.h` — Button input handling.
- `V3_1/Arduino/upload.sh` — arduino-cli build/upload script.

### Audio Receiver Firmware (V3.2)
- `V3_2/Arduino/primusV3_audio_receiver/` — Extends V3.1 receiver with audio and FTP.
  - `config.h` — Adds `AUDIO_BOARD` compile-time switch, `ARTNET_OPCODE_AUDIO_CMD 0x8200`, `ARTNET_OPCODE_FTP_CMD 0x8201`.
  - `primusV3_audio_receiver.ino` — Main sketch: all V3.1 features plus audio and FTP orchestration.
  - `audio.h` — WAV playback behind a unified API (VS1053 or MAX98357 I2S, selected at compile time).
  - `ftp.h` — FTP server wrapper (SimpleFTPServer library). FTP starts off; started via Art-Net or D1 button.
  - `display.h` — Adds Audio screen and FTP screen to the V3.1 display.
  - `buttons.h` — Button input handling (unchanged from V3.1).
- `V3_2/Arduino/upload.sh` — arduino-cli build/upload script.

### Docs
- `API_REFERENCE.md` — Full protocol and HTTP API documentation.
- `DEPLOYMENT_STRATEGY.md` — Packaging plan.

## V3.1 Concepts

- **Clip**: A saved effect configuration (effect, colors, speed, playback mode) for a specific output type. Stored as JSON.
- **Look**: A set of 3 output slots, each with a clip assignment. Defines what all devices display simultaneously.
- **Playback sources**: `designer` (live editing), `mixer` (crossfade between looks), `controller` (cue-driven sequential playback), `idle` (black/off).
- **Output types**: `short_strip` (30px), `long_strip` (72px), `grid` (8x8=64px).

## V3.2 Concepts

- **Audio node**: A V3.2 receiver. Identical to a V3.1 node for LED purposes; additionally plays WAV files from SD card on Art-Net command.
- **SD bus mutex** (`sdBusy`): A boolean flag that prevents FTP and audio from accessing the SD card simultaneously. Set to `true` by audio playback, cleared when audio stops. FTP checks this flag before starting and refuses if set.
- **FTP lifecycle**: FTP is off at boot. It is started explicitly (Art-Net 0x8201 cmd=1, or D1 button on FTP screen) and stopped explicitly (Art-Net 0x8201 cmd=0, or audio command, or D1 button). There is no auto-start or auto-restart.
- **Audio board switch**: `#define AUDIO_BOARD` in `config.h` selects between `AUDIO_BOARD_MUSIC_MAKER` (VS1053, SPI) and `AUDIO_BOARD_BFF` (MAX98357, I2S) at compile time. The `audio.h` API is identical for both.
- **Audio commands (0x8200)**: cmd 0=stop, 1=play, 2=loop, 3=pause, 4=volume. Cmd 4 calls the hardware volume register without interrupting playback — used for live slider updates.
- **Audio UI**: The V3.1 sender has an "Audio" tab (`audio-panel.js`) that shows audio-capable devices, lists their SD card files via FTP, and provides play/loop/stop/pause controls and a live volume slider (throttled to 50 ms).

## Critical sync points

The sender and receiver must agree on:
- **Output type IDs**: `LOOK_OUTPUT_TYPES` list (Python) indices = `OutputType` enum (C++) values
- **Pixel counts**: `OUTPUT_TYPES` dict (Python, in state.py) = `OUTPUT_TYPE_TABLE` (C++)
- **Custom opcode 0x8100**: ArtOutputConfig for runtime output type changes
- **Custom opcode 0x8200**: ArtAudioCmd — 15-byte minimum packet, cmd/volume/filename
- **Custom opcode 0x8201**: ArtFtpCmd — 13-byte packet, cmd byte only
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

## V3.1 API endpoints (29 total)

**GET**: `/` (web UI), `/api/state`, `/api/clips`, `/api/clips/<id>`, `/api/looks`, `/api/looks/<id>`, `/api/cues`
**POST (devices)**: `/api/update`, `/api/connect`, `/api/disconnect`, `/api/connect_all`, `/api/disconnect_all`, `/api/discover`, `/api/add_discovered`, `/api/add_manual`, `/api/remove_device`, `/api/rename_node`, `/api/hello_device`, `/api/set_playback_source`
**POST (clips)**: `/api/clip/preview`, `/api/clips/save`, `/api/clips/save_single`
**POST (looks/mixer)**: `/api/looks/save`, `/api/mixer/preview`, `/api/device_groups/save`
**POST (cues)**: `/api/cues` (save), `/api/cues/go`
**POST (audio — V3.2 nodes only)**: `/api/audio/cmd`, `/api/audio/files`
**DELETE**: `/api/clips/<id>`, `/api/looks/<id>`, `/api/device_groups/<id>`

## Hardware

- ESP32-S3 Reverse TFT Feather (Adafruit)
- NeoPXL8 level-shifted outputs on GPIO 16/17/18 (ports A2/A1/A0)
- 240x135 ST7789 TFT display
- D0 button: cycle screens, D1 button: toggle test mode
- Max 72 LEDs per port, 3 ports = 216 LEDs max per node
