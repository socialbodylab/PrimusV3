# Primus V3.6

> **PrimusCentral shipping track:** New sender development, packaged apps (v0.81+), and PrimusCentral releases use [`../V4/`](../V4/) with `python3 V4/sender/run.py --product primus` and `python3 V4/build_sender_app.py --product primus`. This tree remains the V3.6 protocol/source reference and can still be run from source for comparison.

V3.6 is the compatibility track for running V1, V2, and V3.1 Primus receiver hardware from the current Primus web sender and Art-Net protocol.

The important design choice is that V1 and V2 hardware are not supported through their old runtime protocols. They must be reflashed with V3.6 firmware. After reflashing, every supported board generation speaks the same V3.6 Art-Net, discovery, output-config, IP-config, rename, hello, and FPS telemetry contracts.

V3.6 adds dynamic Clip, Look, and Timeline segment brightness in the sender. Receiver firmware keeps LED driver brightness locked at 255 and accepts ordinary RGB ArtDmx frames; the sender scales RGB pixel values before transport so brightness changes are smooth across V1, V2, and V3.1 profiles without reviving the old V2 brightness-byte protocol.

V3.6 also adds portable Clip and Look sharing bundles. Clips export as standalone JSON bundles, Looks export with their referenced Clips when available, and imports remap IDs as needed so shared files do not overwrite local show content.

> **Firmware consolidation:** New receiver firmware source and upload scripts are canonical under [`../V4/Arduino/`](../V4/Arduino/). This tree retains copies for the current PrimusCentral release line. See [`../V4/ARCHITECTURE.md`](../V4/ARCHITECTURE.md) for the unified backend roadmap.

## Documentation Map

| Document | Use it for |
| --- | --- |
| [../setup_primus.py](../setup_primus.py) | Automated first-time setup after Python 3 is installed. |
| [../BOARD_UPLOAD_README.md](../BOARD_UPLOAD_README.md) | First-time board upload setup, automated setup, and manual fallback commands. |
| [FIRMWARE_DEVELOPMENT.md](FIRMWARE_DEVELOPMENT.md) | Receiver firmware profiles, pins, output tables, Art-Net contracts, and firmware change checklist. |
| [SENDER_DEVELOPMENT.md](SENDER_DEVELOPMENT.md) | Python sender architecture, discovery metadata, output type synchronization, API behavior, and tests. |
| [ConnectionSettings.md](ConnectionSettings.md) | Sender network Settings workflow, show-router route selection, and Settings API methods. |
| [exteriorIntegration.md](exteriorIntegration.md) | Inbound OSC cue triggering for QLab and other show-control tools. |
| [PACKAGING.md](PACKAGING.md) | Build a one-click macOS app or Windows executable for the V3.6 sender/interface. |
| [WINDOWS_BUILD.md](WINDOWS_BUILD.md) | Windows 11 build handoff, permissions, networking, timing, firmware, and validation checklist for the 0.7 app. |
| [hardwareCompatibility.md](hardwareCompatibility.md) | Compact board/profile/pin/output reference. |
| [previousHardware/](previousHardware/) | Archived V1/V2 firmware and specs used only as historical reference. |

## Current Structure

```text
V3_6/
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
├── ConnectionSettings.md
├── exteriorIntegration.md
├── FIRMWARE_DEVELOPMENT.md
├── WINDOWS_BUILD.md
└── SENDER_DEVELOPMENT.md
```

## Supported Hardware Profiles

| Profile | Hardware | LED output backend | Default outputs |
| --- | --- | --- | --- |
| `v1` | Adafruit Huzzah32 ESP32 Feather | Direct NeoPixel on GPIO32/GPIO12 | `small_grid`, `long_strip` |
| `v2` | Adafruit ESP32 Feather V2 | Direct NeoPixel on GPIO32/GPIO12 | `small_grid`, `short_strip` |
| `v3` | ESP32-S3 Reverse TFT Feather + NeoPXL8 FeatherWing | NeoPXL8 outputs 6/7 | `short_strip`, `long_strip` |

## Quick Start

From the repository root, after installing Python 3 manually, run the automated setup once:

```sh
python3 setup_primus.py
```

Check an existing machine without installing anything:

```sh
python3 setup_primus.py --check
```

Compile only:

```sh
./V3_6/Arduino/upload.sh -v1 --compile
./V3_6/Arduino/upload.sh -v2 --compile
./V3_6/Arduino/upload.sh -v3 --compile
```

Upload to a detected board:

```sh
./V3_6/Arduino/upload.sh --ports
./V3_6/Arduino/upload.sh -v3 --auto
```

Upload with temporary WiFi credential overrides:

```sh
./V3_6/Arduino/upload.sh -v2 -ssid "PrimusRouter" -pw "router-password" --auto
```

Upload to multiple detected boards of the same profile:

```sh
./V3_6/Arduino/upload.sh -v2 --all
```

Upload to one or more explicit serial ports:

```sh
./V3_6/Arduino/upload.sh -v1 /dev/cu.usbserial-XXXX /dev/cu.usbserial-YYYY
./V3_6/Arduino/upload.sh -v2 /dev/cu.usbserial-XXXX
./V3_6/Arduino/upload.sh -v3 /dev/cu.usbmodemXXXX
```

Use `--ports` to list likely ESP32 serial devices before uploading. Upload commands compile automatically before flashing, so `--compile` is only needed for a verify-only pass. Use `-ssid` and `-pw` to override the firmware's default WiFi credentials for one build without editing source files. Use `--auto` when exactly one ESP32-like device is connected; the script refuses to guess when none or multiple candidates are found. Use `--all` only when every detected ESP32-like candidate should receive the selected profile.

Run the sender (historical V3.6 source tree — use [`../V4/`](../V4/) for current PrimusCentral work):

```sh
.venv/bin/python V3_6/sender/run.py
```

By default the interface uses `http://127.0.0.1:8080`, falling back to an auto-selected port only if 8080 is busy. Running `run.py` directly starts the server, replaces any previous V3.6 sender process, and opens the interface. When Chrome, Edge, Brave, or Chromium is available, the sender uses a fresh Primus-only app window so browser session restore cannot reopen duplicate old tabs; otherwise it falls back to the system default browser. Use `--no-browser` only for automated checks where no browser should be opened.

`run.py` is the only interface entry point. `controller.py` is a cue-controller module and does not launch the UI.

Run sender checks:

```sh
python3 -m py_compile V3_6/sender/*.py
python3 -m unittest discover -s V3_6/sender/tests
```

## Packaged macOS Release Baseline

The v0.65 release is the baseline for packaged macOS FPS behavior. The bug it fixed only reproduced when `PrimusCentral.app` was launched as a real app bundle through Finder or LaunchServices. Do not use `V3_6/dist/macos/PrimusCentral.app/Contents/MacOS/PrimusCentral` as the primary packaged-performance test path; direct binary execution bypasses the app-bundle scheduler behavior.

Build, sign, notarize, staple, and verify the app with the **V4** builder (current shipping track):

```sh
python3 V4/build_sender_app.py \
	--target macos \
	--product primus \
	--name PrimusCentral \
	--sign-identity "Developer ID Application: Nicholas Puckett (SAV2V7GXQ5)" \
	--notary-profile "PrimusCentral Notary" \
	--notary-timeout 1h
```

The release app is written to `V4/dist/macos/PrimusCentral.app`. The legacy V3.6 builder below remains for reference only:

```sh
python3 V3_6/build_sender_app.py \
	--target macos \
	--sign-identity "Developer ID Application: Nicholas Puckett (SAV2V7GXQ5)" \
	--notary-profile "PrimusCentral Notary" \
	--notary-timeout 1h
```

The release app keeps the visible name `PrimusCentral.app`, uses bundle ID `com.socialbodylab.PrimusCentral`, and is written to `V3_6/dist/macos/PrimusCentral.app`. Signing settings can also come from `PRIMUSV3_CODESIGN_IDENTITY`, `PRIMUSV3_NOTARY_PROFILE`, and `PRIMUSV3_NOTARY_TIMEOUT`.

Packaged macOS runtime timing uses three intentional overrides: a `caffeinate -dimsu -w <pid>` process assertion, user-interactive QoS for the animation and mixer/controller threads, and low-latency frame pacing. Set `PRIMUSV3_DISABLE_MACOS_ACTIVITY=1` only when intentionally disabling the `caffeinate` assertion for diagnostics.

Validate packaged FPS through LaunchServices, then inspect the sender performance API:

```sh
open -n V3_6/dist/macos/PrimusCentral.app --args --port 8097
curl -s http://127.0.0.1:8097/api/performance
```

For release DMGs, create a clean staging directory with only `PrimusCentral.app` and an `/Applications` symlink, notarize and staple the DMG itself, then generate the SHA-256 checksum after stapling. The full command checklist is in [PACKAGING.md](PACKAGING.md).

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

The initial V3.6 bring-up verified compile/upload/discovery/hello across connected V1, V2, and V3.1-style boards:

- V1 discovered as `V1 Huzzah32`, firmware `3.5`, capability flags `RIOH`.
- V2 discovered as `V2 Feather`, firmware `3.5`, capability flags `RIOH`.
- V3.1 discovered as `V3.1 Reverse TFT`, firmware `3.5`, capability flags `RIOH`.

Use this as a smoke-test baseline, not as a substitute for full show hardware testing.
