# V3.6 Firmware Development

This document is the working reference for future V3.6 receiver firmware changes.

## Source Tree

Active firmware lives in:

```text
V3_6/Arduino/primusV3_receiver/
├── config.h                 # Board profiles, pins, output types, protocol constants
├── primusV3_receiver.ino    # WiFi, Art-Net parsing, LED output, telemetry
├── display.h                # TFT display implementation or no-op adapter
└── buttons.h                # D0/D1 button implementation or no-op adapter
```

Historical V1/V2 firmware in `V3_6/previousHardware/` is reference material only. Do not add runtime compatibility for the old V1 OSC or old V2 brightness-byte protocols unless that becomes an explicit product requirement.

## Build Profiles

V3.6 uses one source tree with compile-time board profiles. The profile is selected by `upload.sh`, which passes one of these macros:

| Profile | Build macro | FQBN | Upload speed |
| --- | --- | --- | --- |
| `v1` | `PRIMUS_PROFILE_V1` | `esp32:esp32:featheresp32` | `115200` |
| `v2` | `PRIMUS_PROFILE_V2` | `esp32:esp32:adafruit_feather_esp32_v2` | `115200` |
| `v3` | `PRIMUS_PROFILE_V3_1` | `esp32:esp32:adafruit_feather_esp32s3_reversetft` | `921600` |

Examples:

```sh
./V3_6/Arduino/upload.sh --ports
./V3_6/Arduino/upload.sh --ports-json
./V3_6/Arduino/upload.sh -v1 --compile
./V3_6/Arduino/upload.sh -v3 --auto
./V3_6/Arduino/upload.sh -v2 /dev/cu.usbserial-XXXX
./V3_6/Arduino/upload.sh -v3 --name "StageLeft" --auto
./V3_6/Arduino/upload.sh -v2 -ssid "PrimusRouter" -pw "router-password" --auto
./V3_6/Arduino/upload.sh -v1 --static-ip 192.168.1.50 --gateway 192.168.1.1 --subnet 255.255.255.0 --auto
./V3_6/Arduino/upload.sh -v1 --dhcp --auto
./V3_6/Arduino/upload.sh -v3 /dev/cu.usbmodemXXXX
./V3_6/Arduino/upload.sh -v2 --baud 230400 /dev/cu.usbserial-XXXX
```

### Upload Script Flags

`upload.sh` can list likely ESP32 serial devices, compile profiles, override default WiFi credentials for a build, and upload firmware. Upload commands always compile first, then upload, matching the Arduino IDE Upload workflow; `--compile` is the verify-only path. Use `--ports` before uploading to see candidates. Use `--auto` when exactly one ESP32-like serial device is attached; the script refuses to guess when zero or multiple candidates are found. Use `--all` when every detected ESP32-like candidate should receive the same selected profile. If no serial port is supplied, the script keeps the same single-device auto-detection behavior for compatibility, but explicit `--auto` is preferred.

| Flag / argument | Meaning |
| --- | --- |
| `-v1` | Build for the V1 Huzzah32 profile. Long form: `--board v1`. Alias: `--board v1_huzzah`. |
| `-v2` | Build for the V2 ESP32 Feather profile. Long form: `--board v2`. Alias: `--board v2_feather`. |
| `-v3` | Build for the V3.1 Reverse TFT profile. Long form: `--board v3`. Legacy aliases: `--board v3_1`, `--board v31`, `--board v3_1_reverse_tft`. This is the default when no board flag is supplied. |
| `--compile` | Compile only. Do not upload. This is the Arduino IDE Verify-style path. |
| `--install` | Install/check the libraries required by the selected board, then exit. |
| `-name <name>`, `--name <name>`, `--device-name <name>` | Override `DEVICE_SHORT_NAME` for this build without editing `config.h`. Max 17 characters. This is force-applied on boot and replaces any saved Rename/NVS short name. |
| `-ssid <name>`, `--ssid <name>` | Override `DEFAULT_WIFI_SSID` for this build without editing `config.h`. The sender Firmware tab requires SSID and password overrides together. |
| `-pw <password>`, `--pw <password>`, `--password <password>` | Override `DEFAULT_WIFI_PASSWORD` for this build without editing `config.h`. Passwords are redacted in sender job output. |
| `--static-ip <ip>` | Store a static IP in receiver Preferences on boot for this build. Must be used with `--gateway` and `--subnet`. |
| `--gateway <ip>` | Gateway to store with `--static-ip`. |
| `--subnet <ip>` | Subnet mask to store with `--static-ip`. |
| `--dhcp` | Clear saved static IP settings in receiver Preferences on boot. Cannot be combined with `--static-ip`. |
| `--ports`, `--list-ports` | List likely ESP32 serial ports and exit without compiling or uploading. |
| `--ports-json`, `--list-ports-json` | List likely ESP32 serial ports as JSON for the sender web UI. |
| `--auto`, `-auto` | Select the only detected ESP32-like serial port. Fails if no candidates or multiple candidates are found. |
| `--all`, `-all`, `--all-ports` | Select every detected ESP32-like serial port and upload the selected profile to each one sequentially. If Arduino CLI identifies exact selected-board matches, only those exact matches are used; otherwise all ESP32-like candidates are used. |
| `--baud <rate>` | Override the selected board's default upload speed. Alias: `--speed`. |
| `/dev/cu...` | Optional explicit serial port. Provide one or more paths when multiple boards are connected or auto-detection is ambiguous. |
| `-h`, `--help` | Print the script's short usage block. |

Common upload commands:

```sh
./V3_6/Arduino/upload.sh -v1 /dev/cu.usbserial-XXXX
./V3_6/Arduino/upload.sh -v2 /dev/cu.usbserial-XXXX
./V3_6/Arduino/upload.sh -v3 --name "StageLeft" /dev/cu.usbmodemXXXX
./V3_6/Arduino/upload.sh -v2 -ssid "PrimusRouter" -pw "router-password" --auto
./V3_6/Arduino/upload.sh -v1 --static-ip 192.168.1.50 --gateway 192.168.1.1 --subnet 255.255.255.0 /dev/cu.usbserial-XXXX
./V3_6/Arduino/upload.sh -v1 --dhcp /dev/cu.usbserial-XXXX
./V3_6/Arduino/upload.sh -v2 --all
./V3_6/Arduino/upload.sh -v3 /dev/cu.usbmodemXXXX
```

### Sender Firmware Tab

The V3.6 sender web UI includes a Firmware tab. It wraps `upload.sh` through local JSON API jobs and keeps this script as the source of truth for board profiles, library installation, compile flags, WiFi overrides, and upload behavior.

The UI is intentionally focused on the common flashing path:

- Choose the firmware version (`v1`, `v2`, or `v3`).
- Refresh available USB devices and select one detected receiver, or choose all available devices.
- Independently enable a default device-name override, WiFi SSID/password overrides, and static/DHCP IP overrides.
- Install firmware tools when Arduino CLI is missing.
- Compile or upload, then watch the output window.

When enabled, the device-name override is treated as explicit overwrite intent: the receiver stores the compiled short name into NVS on boot, replacing any older name saved through the Rename workflow. WiFi credential overrides also compile a force flag that clears stale ESP32 station credentials before connecting with the supplied SSID/password. Static IP overrides write the supplied IP/gateway/subnet into receiver Preferences on boot, while DHCP overrides clear saved static IP settings. The upload script still handles ESP32 core/library checks during compile and upload. The standalone `--install` CLI flag remains available for command-line maintenance.

Firmware jobs run one at a time because Arduino core installation, library installation, compile caches, and serial uploads can conflict when launched concurrently. The UI redacts WiFi passwords from job status and output.

Packaged PrimusCentral builds include the receiver firmware source and `upload.sh`, but they do not bundle Arduino CLI, ESP32 board packages, or downloaded library caches. When the Firmware panel runs `setup_tools`, the sender downloads Arduino CLI into a managed tools directory, configures ESP32 board support with `arduino-cli.yaml` in that same directory, and runs `upload.sh --install` for the supported board profiles. Source checkouts still use `.tools/` by default; packaged apps use app data, for example `~/Library/Application Support/PrimusV3/V3_6/tools/` on macOS. Use `PRIMUSV3_TOOLS_DIR` to force a temporary tools directory for installer testing.

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

| Profile | Indicator | Connected static state | Connected DHCP state | Disconnected state |
| --- | --- | --- | --- | --- |
| `v1` | `LED_BUILTIN` | Solid on | Blink on/off | Off |
| `v2` | Onboard NeoPixel on GPIO0, power GPIO2 | Solid red | Blinking red | Off |
| `v3` | TFT display | `WiFi STATIC` screen text, static IP in serial/debug data | `WiFi DHCP` screen text, DHCP in serial/debug data | `No WiFi` / error screen |

The indicator should reflect `WiFi.status() == WL_CONNECTED` plus whether static IP settings were successfully applied for the current WiFi attempt. Keep sender activity, FPS, and Art-Net receive state separate from this simple board-level connection signal. At startup, all profiles print the target SSID, password, selected device name, IP mode, static IP data when present, output configuration, and connected network details to `Serial` for field debugging; the firmware never waits for Serial to be attached.

## Output Type Table

The firmware output type enum must match the sender's `LOOK_OUTPUT_TYPES` index order exactly.

| ID | Firmware enum | Sender key | Pixels | Layout |
| --- | --- | --- | --- | --- |
| 0 | `OUTPUT_OFF` | `none` | 0 | none |
| 1 | `OUTPUT_SHORT_STRIP` | `short_strip` | 30 | linear |
| 2 | `OUTPUT_LONG_STRIP` | `long_strip` | 72 | linear |
| 3 | `OUTPUT_GRID` | `grid` | 64 | 8x8 grid |
| 4 | `OUTPUT_SMALL_GRID` | `small_grid` | 32 | 8x4 grid |
| 5 | `OUTPUT_EXTRA_LONG_STRIP` | `extra_long_strip` | 122 | linear |

When adding an output type:

1. Append the enum value in `config.h`.
2. Append the corresponding row in `OUTPUT_TYPE_TABLE[]`.
3. Update `MAX_LEDS_PER_PORT` if needed.
4. Add the sender type in `V3_6/sender/state.py` `OUTPUT_TYPES`.
5. Append the sender key to `LOOK_OUTPUT_TYPES` at the matching index.
6. Add parser tests if discovery/output config behavior changes.
7. Compile all profiles.

Prefer append-only IDs. Reordering existing IDs will break persisted output configurations and discovery parsing.

## Art-Net And Custom Protocol

V3.6 receivers use standard Art-Net UDP 6454 plus existing Primus custom extensions.

| Packet | Opcode / Port | Receiver behavior |
| --- | --- | --- |
| ArtPoll | `0x2000` | Reply with ArtPollReply and capability-tagged Node Report. |
| ArtPollReply | `0x2100` | Advertises profile, output types, universes, and feature flags. |
| ArtDmx | `0x5000` | Writes RGB pixel bytes for the addressed universe. |
| ArtAddress | `0x6000` | Stores remote name in NVS/preferences. |
| ArtOutputConfig | `0x8100` | Stores selected output type IDs. |
| ArtIPConfig | `0x8200` | Stores static IP/DHCP configuration. |
| FPS telemetry | UDP `6455` magic `PFP` | Reports receive/render FPS to sender. |

V3.6 dynamic brightness does not change this packet table. The sender scales RGB bytes before ArtDmx transmission; receivers keep NeoPixel/NeoPXL8 hardware brightness locked at 255 and write the received RGB values directly to the configured output buffers. Do not reintroduce the historical V2 leading brightness byte unless it becomes a deliberate protocol requirement.

## WiFi Reliability: setSleep After Connect

The ESP32 Arduino WiFi stack resets modem sleep to the default (`WIFI_PS_MIN_MODEM`) during the WPA association/authentication phase, silently overriding any `WiFi.setSleep(false)` call made before `WiFi.begin()`. With modem sleep active, the radio periodically goes dark between beacon intervals — UDP packets that arrive during that window are dropped. For Art-Net and audio status reporting this produces intermittent packet loss that is hard to distinguish from a network problem.

The fix is to call `WiFi.setSleep(false)` **after** the connection is established, not before `WiFi.begin()`. In Radius firmware this is done inside `checkWifiConnection()` at the point where `wifiConnected` transitions from false to true:

```cpp
WiFi.setSleep(false);  // must be set after connect — connection process resets it
```

Calling it before `WiFi.begin()` as well is harmless and keeps the intent visible at startup, but the post-connect call is the one that actually takes effect.

The LED receiver firmware (`primusV3_receiver.ino`) currently only calls `WiFi.setSleep(false)` before `WiFi.begin()`. It has the same latent issue, but because LED receivers stay powered on for the duration of a show the connection process runs only once and the effect has not been observed in practice. Apply the post-connect call there if intermittent ArtDmx drop-outs are reported on LED nodes.

## Discovery Node Report

The V3.6 Node Report keeps the V3.1 `PV3CAP1` shape and adds parser-safe board and IP-mode segments:

```text
PV3CAP1|port:type_id:universe|B:profile|IP:D|F:features
PV3CAP1|port:type_id:universe|B:profile|IP:S|F:features
```

Example V1 report:

```text
#0001 [0000] OK|PV3CAP1|0:4:0|1:2:1|B:v1|IP:S|F:RIOH
```

`IP:D` means the receiver is using DHCP. `IP:S` means it has saved static IP settings; the ArtPollReply IP field remains the current address. Keep this token compact because Art-Net Node Report is limited to 64 bytes.

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

V3.6 intentionally keeps the V3.5 persistence namespace (`primus35`) so upgraded receivers preserve saved device names, output type selections, and static IP/DHCP settings. Change this only with an explicit migration/reset plan.

Firmware upload overrides have narrower force semantics than a full device reset. Supplying `--name` writes that name into the saved `shortName` key on boot. Supplying WiFi credentials clears stored ESP32 station credentials before `WiFi.begin(...)`. Supplying `--static-ip` writes static IP settings into Preferences, and supplying `--dhcp` removes those static IP Preferences keys. These overrides do not erase output-type settings. Add a separate refurbish/reset workflow if old nodes need all saved receiver settings cleared.

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
./V3_6/Arduino/upload.sh -v1 --compile
./V3_6/Arduino/upload.sh -v2 --compile
./V3_6/Arduino/upload.sh -v3 --compile
```

Hardware smoke test:

1. Upload the correct profile to the physical board.
2. Start `python3 V3_6/sender/run.py --no-browser --port 0`.
3. Call `/api/discover` or use the web UI Discover button.
4. Confirm profile label, firmware `3.5`, universes, output types, and `RIOH` flags.
5. Add/connect the device.
6. Trigger Hello and confirm the expected physical output flashes.
7. Disconnect/blackout before ending the test.
8. Remove generated `V3_6/sender/.primus_state.json` before committing.
