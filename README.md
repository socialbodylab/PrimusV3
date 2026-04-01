# PrimusV3

WiFi-controlled LED lighting system for live performance costumes. A Python sender drives ESP32-S3 receiver nodes over Art-Net.

## How It Works

```
┌──────────────┐    Art-Net UDP    ┌──────────────────┐
│  Sender      │  ──────────────►  │  Receiver Node   │
│  (Python)    │    port 6454      │  (ESP32-S3)      │
│              │  ◄──────────────  │                  │
│  Web UI      │   FPS telemetry   │  3× NeoPixel out │
│  :8080       │    port 6455      │  TFT display     │
└──────────────┘                   └──────────────────┘
```

The sender runs a web UI with a built-in effects engine. It computes animation frames and sends pixel data over Art-Net to one or more receiver nodes on the same WiFi network. Each node drives up to 3 NeoPixel outputs through level-shifted NeoPXL8.

## Quick Start

### Sender

```bash
python3 sender/led_controller.py
```

Opens a web UI at [http://localhost:8080](http://localhost:8080). No external dependencies — Python 3 stdlib only.

From the web UI you can:
- Discover receiver nodes on the network
- Connect/disconnect devices
- Choose output types (strip, grid, off) per port
- Apply effects with color and speed controls
- Rename devices
- Monitor live FPS from each node

### Firmware

```bash
cd Arduino
./upload.sh
```

Requires [arduino-cli](https://arduino.cc/pro/cli). The script auto-detects the board, installs libraries, compiles, and uploads. See `./upload.sh --help` for options.

**Other commands:**
```bash
./upload.sh --compile    # compile only, no upload
./upload.sh --install    # install required libraries only
./upload.sh /dev/cu.usbmodem14101  # specify port manually
```

## Hardware

- **Board:** [Adafruit ESP32-S3 Reverse TFT Feather](https://www.adafruit.com/product/5691)
- **LED driver:** NeoPXL8 (level-shifted, 3 outputs on GPIO 16/17/18 → A2/A1/A0)
- **Display:** Built-in 240×135 ST7789 TFT — shows device name, WiFi status, IP, RSSI, live FPS
- **Buttons:** D0 cycles display screens, D1 toggles test mode

### Output Types

| Type | Pixels | Layout |
|------|-------:|--------|
| Off | 0 | — |
| Short Strip | 30 | Linear |
| Long Strip | 72 | Linear |
| Grid 8×8 | 64 | Serpentine |

Output types are configurable at runtime from the web UI — no reflashing needed. Each node supports up to 3 outputs (one per port), each independently assignable.

## Effects

| Effect | Works On |
|--------|----------|
| Solid | All |
| Pulse | All |
| Linear | All |
| Constrainbow | All |
| Rainbow | All |
| Knight Rider | All |
| Chase | All |
| Radial | Grid only |
| Spiral | Grid only |

## Network Protocol

Standard Art-Net 4 over UDP, plus two custom extensions:

| Function | Port | Opcode |
|----------|------|--------|
| LED data (ArtDmx) | 6454 | 0x5000 |
| Discovery (ArtPoll/Reply) | 6454 | 0x2000/0x2100 |
| Device naming (ArtAddress) | 6454 | 0x6000 |
| Output config (custom) | 6454 | 0x8100 |
| FPS telemetry (custom) | 6455 | — |

Any Art-Net compatible software (TouchDesigner, MadMapper, etc.) can drive these nodes directly. See [API_REFERENCE.md](API_REFERENCE.md) for full protocol docs.

## Project Structure

```
PrimusV3/
├── sender/
│   └── led_controller.py           # Sender + web UI (single file, ~1800 lines)
├── Arduino/
│   ├── upload.sh                    # Build & upload script
│   └── primusV3_receiver/
│       ├── primusV3_receiver.ino    # Main firmware
│       ├── config.h                 # Output types, pins, network config
│       ├── display.h                # TFT display screens
│       └── buttons.h                # Button handling
├── API_REFERENCE.md                 # Full protocol documentation
├── DEPLOYMENT_STRATEGY.md           # Packaging & distribution plan
├── CLAUDE.md                        # Agent context (Claude)
└── .github/
    └── copilot-instructions.md      # Agent context (Copilot)
```

## Adding Output Types

Both sides use lookup tables — add one row each:

**config.h:**
```c
OUTPUT_RING = 4,  // add to OutputType enum
{ "Ring", 24, 3, LAYOUT_LINEAR, 0, 0 },  // add to OUTPUT_TYPE_TABLE
```

**led_controller.py:**
```python
"ring": {"pixels": 24, "layout": "linear"},  # add to OUTPUT_TYPES
LOOK_OUTPUT_TYPES = ["none", "short_strip", "long_strip", "grid", "ring"]
# Index must match enum value
```

## License

Private — not for redistribution.
