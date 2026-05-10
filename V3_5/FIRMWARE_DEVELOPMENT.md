# V3.5 Firmware Development

This document is the working reference for future V3.5 receiver firmware changes.

## Source Tree

Active firmware lives in:

```text
V3_5/Arduino/primusV3_receiver/
├── config.h                 # Board profiles, pins, output types, protocol constants
├── primusV3_receiver.ino    # WiFi, Art-Net parsing, LED output, telemetry
├── display.h                # TFT display implementation or no-op adapter
└── buttons.h                # D0/D1 button implementation or no-op adapter
```

Historical V1/V2 firmware in `V3_5/previousHardware/` is reference material only. Do not add runtime compatibility for the old V1 OSC or old V2 brightness-byte protocols unless that becomes an explicit product requirement.

## Build Profiles

V3.5 uses one source tree with compile-time board profiles. The profile is selected by `upload.sh`, which passes one of these macros:

| Profile | Build macro | FQBN | Upload speed |
| --- | --- | --- | --- |
| `v1` | `PRIMUS_PROFILE_V1` | `esp32:esp32:featheresp32` | `115200` |
| `v2` | `PRIMUS_PROFILE_V2` | `esp32:esp32:adafruit_feather_esp32_v2` | `115200` |
| `v3` | `PRIMUS_PROFILE_V3_1` | `esp32:esp32:adafruit_feather_esp32s3_reversetft` | `921600` |

Examples:

```sh
./V3_5/Arduino/upload.sh --ports
./V3_5/Arduino/upload.sh -v1 --compile
./V3_5/Arduino/upload.sh -v3 --auto
./V3_5/Arduino/upload.sh -v2 /dev/cu.usbserial-XXXX
./V3_5/Arduino/upload.sh -v3 /dev/cu.usbmodemXXXX
./V3_5/Arduino/upload.sh -v2 --baud 230400 /dev/cu.usbserial-XXXX
```

### Upload Script Flags

`upload.sh` can list likely ESP32 serial devices, compile profiles, and upload firmware. Upload commands always compile first, then upload, matching the Arduino IDE Upload workflow; `--compile` is the verify-only path. Use `--ports` before uploading to see candidates. Use `--auto` when exactly one ESP32-like serial device is attached; the script refuses to guess when zero or multiple candidates are found. Use `--all` when every detected ESP32-like candidate should receive the same selected profile. If no serial port is supplied, the script keeps the same single-device auto-detection behavior for compatibility, but explicit `--auto` is preferred.

| Flag / argument | Meaning |
| --- | --- |
| `-v1` | Build for the V1 Huzzah32 profile. Long form: `--board v1`. Alias: `--board v1_huzzah`. |
| `-v2` | Build for the V2 ESP32 Feather profile. Long form: `--board v2`. Alias: `--board v2_feather`. |
| `-v3` | Build for the V3.1 Reverse TFT profile. Long form: `--board v3`. Legacy aliases: `--board v3_1`, `--board v31`, `--board v3_1_reverse_tft`. This is the default when no board flag is supplied. |
| `--compile` | Compile only. Do not upload. This is the Arduino IDE Verify-style path. |
| `--install` | Install/check the libraries required by the selected board, then exit. |
| `--ports`, `--list-ports` | List likely ESP32 serial ports and exit without compiling or uploading. |
| `--auto`, `-auto` | Select the only detected ESP32-like serial port. Fails if no candidates or multiple candidates are found. |
| `--all`, `-all`, `--all-ports` | Select every detected ESP32-like serial port and upload the selected profile to each one sequentially. If Arduino CLI identifies exact selected-board matches, only those exact matches are used; otherwise all ESP32-like candidates are used. |
| `--baud <rate>` | Override the selected board's default upload speed. Alias: `--speed`. |
| `/dev/cu...` | Optional explicit serial port. Provide one or more paths when multiple boards are connected or auto-detection is ambiguous. |
| `-h`, `--help` | Print the script's short usage block. |

Common upload commands:

```sh
./V3_5/Arduino/upload.sh -v1 /dev/cu.usbserial-XXXX
./V3_5/Arduino/upload.sh -v2 /dev/cu.usbserial-XXXX
./V3_5/Arduino/upload.sh -v2 --all
./V3_5/Arduino/upload.sh -v3 /dev/cu.usbmodemXXXX
```

## Board Profile Responsibilities

Each profile in `config.h` defines:

- A short profile code used in discovery, such as `v1`, `v2`, or `v31`.
- A human-readable label used in logs and sender UI.
- LED backend selection: direct NeoPixel or NeoPXL8.
- Whether TFT display and D0/D1 buttons are present.
- Default outputs, pins, universes, and output types.

Current defaults:

| Profile | Driver | Output 0 | Output 1 | Default types |
| --- | --- | --- | --- | --- |
| `v1` | Direct NeoPixel | GPIO32 | GPIO12 | `small_grid`, `long_strip` |
| `v2` | Direct NeoPixel | GPIO32 | GPIO12 | `small_grid`, `short_strip` |
| `v3` | NeoPXL8 | FeatherWing output 6 / GPIO14 | FeatherWing output 7 / GPIO15 | `short_strip`, `long_strip` |

## LED Backend Abstraction

`primusV3_receiver.ino` should route pixel operations through shared helpers rather than writing directly to a concrete LED object in application logic.

Expected pattern:

- Profile-specific allocation/initialization happens near setup.
- Per-pixel writes go through the shared strip write helper.
- Show/flush calls go through the shared show helper.
- Test mode, ArtDmx handling, hello flashes, and blackout logic should not know whether the board is using direct NeoPixel or NeoPXL8.

This keeps V1/V2 direct GPIO and V3.1 NeoPXL8 behavior aligned.

## Display And Button Optionality

V1 and V2 boards do not have the V3.1 TFT or D0/D1 buttons. `display.h` and `buttons.h` must continue to compile as no-op adapters for those profiles.

Rules:

- Do not include TFT-only libraries for screenless profiles.
- Keep public display/button function names stable so `primusV3_receiver.ino` stays profile-neutral.
- Add screen behavior only behind profile capability checks.

## No-Screen Connection Indicators

V1 and V2 need an on-board WiFi connection indicator because they do not have a TFT.

| Profile | Indicator | Connected state | Disconnected state |
| --- | --- | --- | --- |
| `v1` | `LED_BUILTIN` | On | Off |
| `v2` | Onboard NeoPixel on GPIO0, power GPIO2 | Green | Off |
| `v3` | TFT display | `WiFi OK` screen text | `No WiFi` / error screen |

The indicator should reflect `WiFi.status() == WL_CONNECTED`. Keep sender activity, FPS, and Art-Net receive state separate from this simple board-level connection signal.

## Output Type Table

The firmware output type enum must match the sender's `LOOK_OUTPUT_TYPES` index order exactly.

| ID | Firmware enum | Sender key | Pixels | Layout |
| --- | --- | --- | --- | --- |
| 0 | `OUTPUT_OFF` | `none` | 0 | none |
| 1 | `OUTPUT_SHORT_STRIP` | `short_strip` | 30 | linear |
| 2 | `OUTPUT_LONG_STRIP` | `long_strip` | 72 | linear |
| 3 | `OUTPUT_GRID` | `grid` | 64 | 8x8 grid |
| 4 | `OUTPUT_SMALL_GRID` | `small_grid` | 32 | 4x8 grid |
| 5 | `OUTPUT_EXTRA_LONG_STRIP` | `extra_long_strip` | 122 | linear |

When adding an output type:

1. Append the enum value in `config.h`.
2. Append the corresponding row in `OUTPUT_TYPE_TABLE[]`.
3. Update `MAX_LEDS_PER_PORT` if needed.
4. Add the sender type in `V3_5/sender/state.py` `OUTPUT_TYPES`.
5. Append the sender key to `LOOK_OUTPUT_TYPES` at the matching index.
6. Add parser tests if discovery/output config behavior changes.
7. Compile all profiles.

Prefer append-only IDs. Reordering existing IDs will break persisted output configurations and discovery parsing.

## Art-Net And Custom Protocol

V3.5 receivers use standard Art-Net UDP 6454 plus existing Primus custom extensions.

| Packet | Opcode / Port | Receiver behavior |
| --- | --- | --- |
| ArtPoll | `0x2000` | Reply with ArtPollReply and capability-tagged Node Report. |
| ArtPollReply | `0x2100` | Advertises profile, output types, universes, and feature flags. |
| ArtDmx | `0x5000` | Writes RGB pixel bytes for the addressed universe. |
| ArtAddress | `0x6000` | Stores remote name in NVS/preferences. |
| ArtOutputConfig | `0x8100` | Stores selected output type IDs. |
| ArtIPConfig | `0x8200` | Stores static IP/DHCP configuration. |
| FPS telemetry | UDP `6455` magic `PFP` | Reports receive/render FPS to sender. |

## Discovery Node Report

The V3.5 Node Report keeps the V3.1 `PV3CAP1` shape and adds a parser-safe board segment:

```text
PV3CAP1|port:type_id:universe|B:profile|F:features
```

Example V1 report:

```text
#0001 [0000] OK|PV3CAP1|0:4:0|1:2:1|B:v1|F:RIOH
```

Feature flags:

| Flag | Meaning |
| --- | --- |
| `R` | Remote rename via ArtAddress |
| `I` | IP config via ArtIPConfig |
| `O` | Runtime output config via ArtOutputConfig |
| `H` | Hello/identify flash |

The sender must continue accepting older V3.1 `PV3CAP1` reports that do not include `B:<profile>`.

## Persistence

The firmware stores mutable receiver settings in ESP32 NVS/preferences:

- Device name
- Output type selections
- Static IP/DHCP settings

V3.5 uses its own persistence namespace so it does not collide with older firmware assumptions.

## Adding A Board Profile

1. Add a profile macro branch in `config.h`.
2. Define profile code, label, output driver, display/button availability, and defaults.
3. Add the FQBN, upload speed, and required libraries in `Arduino/upload.sh`.
4. Keep display/buttons no-op compatible if the new board lacks those peripherals.
5. Compile with `--compile` and then test upload/discovery/hello on hardware.
6. Update `hardwareCompatibility.md`, this file, and sender parser tests if a new profile code is introduced.

## Validation Checklist

Run before committing firmware changes:

```sh
./V3_5/Arduino/upload.sh -v1 --compile
./V3_5/Arduino/upload.sh -v2 --compile
./V3_5/Arduino/upload.sh -v3 --compile
```

Hardware smoke test:

1. Upload the correct profile to the physical board.
2. Start `python3 V3_5/sender/run.py --no-browser --port 0`.
3. Call `/api/discover` or use the web UI Discover button.
4. Confirm profile label, firmware `3.5`, universes, output types, and `RIOH` flags.
5. Add/connect the device.
6. Trigger Hello and confirm the expected physical output flashes.
7. Disconnect/blackout before ending the test.
8. Remove generated `V3_5/sender/.primus_state.json` before committing.
