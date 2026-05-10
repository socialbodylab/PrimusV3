# Primus V3.5

V3.5 is the compatibility track for running V1, V2, and V3.1 Primus receiver hardware from the current Primus web sender and Art-Net protocol.

The important design choice is that V1 and V2 hardware are not supported through their old runtime protocols. They must be reflashed with V3.5 firmware. After reflashing, every supported board generation speaks the same V3.5 Art-Net, discovery, output-config, IP-config, rename, hello, and FPS telemetry contracts.

## Documentation Map

| Document | Use it for |
| --- | --- |
| [FIRMWARE_DEVELOPMENT.md](FIRMWARE_DEVELOPMENT.md) | Receiver firmware profiles, pins, output tables, Art-Net contracts, and firmware change checklist. |
| [SENDER_DEVELOPMENT.md](SENDER_DEVELOPMENT.md) | Python sender architecture, discovery metadata, output type synchronization, API behavior, and tests. |
| [hardwareCompatibility.md](hardwareCompatibility.md) | Compact board/profile/pin/output reference. |
| [previousHardware/](previousHardware/) | Archived V1/V2 firmware and specs used only as historical reference. |

## Current Structure

```text
V3_5/
├── Arduino/
│   ├── upload.sh
│   └── primusV3_receiver/
│       ├── config.h
│       ├── primusV3_receiver.ino
│       ├── display.h
│       └── buttons.h
├── sender/
│   ├── run.py
│   ├── state.py
│   ├── artnet.py
│   ├── server.py
│   ├── web/
│   └── tests/
├── previousHardware/
├── hardwareCompatibility.md
├── FIRMWARE_DEVELOPMENT.md
└── SENDER_DEVELOPMENT.md
```

## Supported Hardware Profiles

| Profile | Hardware | LED output backend | Default outputs |
| --- | --- | --- | --- |
| `v1` | Adafruit Huzzah32 ESP32 Feather | Direct NeoPixel on GPIO32/GPIO12 | `small_grid`, `long_strip` |
| `v2` | Adafruit ESP32 Feather V2 | Direct NeoPixel on GPIO32/GPIO12 | `small_grid`, `short_strip` |
| `v3` | ESP32-S3 Reverse TFT Feather + NeoPXL8 FeatherWing | NeoPXL8 outputs 6/7 | `short_strip`, `long_strip` |

## Quick Start

Compile only:

```sh
./V3_5/Arduino/upload.sh -v1 --compile
./V3_5/Arduino/upload.sh -v2 --compile
./V3_5/Arduino/upload.sh -v3 --compile
```

Upload to a detected board:

```sh
./V3_5/Arduino/upload.sh --ports
./V3_5/Arduino/upload.sh -v3 --auto
```

Upload to multiple detected boards of the same profile:

```sh
./V3_5/Arduino/upload.sh -v2 --all
```

Upload to one or more explicit serial ports:

```sh
./V3_5/Arduino/upload.sh -v1 /dev/cu.usbserial-XXXX /dev/cu.usbserial-YYYY
./V3_5/Arduino/upload.sh -v2 /dev/cu.usbserial-XXXX
./V3_5/Arduino/upload.sh -v3 /dev/cu.usbmodemXXXX
```

Use `--ports` to list likely ESP32 serial devices before uploading. Upload commands compile automatically before flashing, so `--compile` is only needed for a verify-only pass. Use `--auto` when exactly one ESP32-like device is connected; the script refuses to guess when none or multiple candidates are found. Use `--all` only when every detected ESP32-like candidate should receive the selected profile.

Run the sender:

```sh
python3 V3_5/sender/run.py
```

By default the interface uses `http://127.0.0.1:8080`, falling back to an auto-selected port only if 8080 is busy. Running `run.py` directly starts the server, replaces any previous V3.5 sender process, and opens the interface. When Chrome, Edge, Brave, or Chromium is available, the sender uses a fresh Primus-only app window so browser session restore cannot reopen duplicate old tabs; otherwise it falls back to the system default browser. Use `--no-browser` only for automated checks where no browser should be opened.

`run.py` is the only interface entry point. `controller.py` is a cue-controller module and does not launch the UI.

Run sender checks:

```sh
python3 -m py_compile V3_5/sender/*.py
python3 -m unittest discover -s V3_5/sender/tests
```

## Contracts That Must Stay In Sync

These are the places most likely to break compatibility if edited on only one side:

| Contract | Firmware | Sender |
| --- | --- | --- |
| Output type IDs | `Arduino/primusV3_receiver/config.h` `OutputType` enum | `sender/state.py` `LOOK_OUTPUT_TYPES` |
| Pixel counts/layouts | `OUTPUT_TYPE_TABLE[]` | `OUTPUT_TYPES` |
| ArtOutputConfig opcode | `ARTNET_OPCODE_OUTPUT_CONFIG = 0x8100` | `send_output_config()` in `sender/artnet.py` |
| ArtIPConfig opcode | `ARTNET_OPCODE_IP_CONFIG = 0x8200` | `send_ip_config()` in `sender/artnet.py` |
| Discovery tag | `PV3CAP1`, `B:<profile>`, `F:RIOH` in Node Report | `parse_node_capabilities()` and `parse_node_outputs()` |
| FPS telemetry | `PFP` packets on UDP 6455 | `FpsListener` |

## Known Development Notes

- Runtime state files such as `sender/.primus_state.json` are generated during local tests and should not be committed.
- V1 and V2 old firmware remain in `previousHardware/` as reference only.
- The sender currently has one active look/output-type selection that is broadcast to connected devices when output config is sent. Mixed hardware can be discovered and controlled, but a future per-device or per-profile output routing pass is needed if V1/V2/V3.1 should keep different native output shapes live at the same time.
- V1/V2 direct NeoPixel profiles default to lower upload speed (`115200`) because those serial adapters were more reliable at that rate during bring-up.

## Initial Hardware Bring-Up Notes

The initial V3.5 bring-up verified compile/upload/discovery/hello across connected V1, V2, and V3.1-style boards:

- V1 discovered as `V1 Huzzah32`, firmware `3.5`, capability flags `RIOH`.
- V2 discovered as `V2 Feather`, firmware `3.5`, capability flags `RIOH`.
- V3.1 discovered as `V3.1 Reverse TFT`, firmware `3.5`, capability flags `RIOH`.

Use this as a smoke-test baseline, not as a substitute for full show hardware testing.
