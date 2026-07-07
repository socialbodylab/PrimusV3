# PrimusV3 V4 Unified Sender

V4 is the **canonical sender track** for PrimusV3. One Python tree builds **three apps**:

- **PrimusCentral** — LED clip/look/cue workflow (Look Designer, Cue Controller, ArtDmx)
- **RadiusCentral** — audio production workflow (Audio Cues, Cue Map, Net Log)
- **DeviceManager** — network monitoring, device config, and firmware upload, on the same `primus`-product backend as PrimusCentral

Shared: device discovery, firmware upload, and network settings. See [ARCHITECTURE.md](ARCHITECTURE.md).

## Quick start

**RadiusCentral (audio):**

```bash
python3 V4/sender/run.py
python3 V4/sender/run.py --product radius --no-browser --port 8098
```

**PrimusCentral (LED):**

```bash
python3 V4/sender/run.py --product primus
python3 V4/sender/run.py --product primus --no-browser --port 8090
```

**DeviceManager (monitoring, config, firmware):**

```bash
python3 V4/sender/run_devices.py
python3 V4/sender/run.py --product primus --frontend devices
```

DeviceManager attaches to an already-running PrimusCentral/DeviceManager server instead of starting a second one; if none is running it starts its own `primus`-product server.

```bash
python3 -m py_compile V4/sender/*.py
python3 -m unittest discover -s V4/sender/tests
```

## Layout

```
V4/
  sender/           Python backend + web UI
  tools/
    osc_cue_sender/  OSC cue test sender (PrimusCentral external control)
  Arduino/
    primusV3_receiver/   Primus LED firmware (profiles v1, v2, v3)
    upload.sh            Primus compile/upload script
    radius_receiver/     Radius V1 audio firmware
    radius_upload.sh     Radius compile/upload script
  build_sender_app.py  PyInstaller packaging (--product primus|radius)
  ARCHITECTURE.md      Unified backend roadmap
  assets/              App icon
  dist/                Build output
```

**Firmware canonical location:** `V4/Arduino/` holds both Primus and Radius receiver source. The V3_6 tree retains copies for the current PrimusCentral release line; new firmware changes should land here.

## OSC Cue Sender

Standalone utility for testing PrimusCentral OSC cue triggers. See [`tools/osc_cue_sender/README.md`](tools/osc_cue_sender/README.md).

```bash
python3 V4/tools/osc_cue_sender/run.py
python3 V4/tools/build_app.py --target macos
```

## App data

| Product | Source run state | Packaged macOS |
|---------|------------------|----------------|
| **Radius** | `.radius_state.json`, `audio_cues.json`, `audio/` | `~/Library/Application Support/RadiusV3/V4/sender/` |
| **Primus** | `.primus_state.json`, `clips/`, `looks/`, `cues.json` | `~/Library/Application Support/PrimusV3/V4/sender/` |

Override with `RADIUSV4_DATA_DIR`, `PRIMUSV3_DATA_DIR`, or `* _USE_APP_DATA=1`.

## Web UI modes

**PrimusCentral** (`--product primus`): Look Designer, Cue Controller, Firmware, Settings

**RadiusCentral** (`--product radius`): Audio, Audio Cues, Cue Map, Net Log, Firmware, Settings

**DeviceManager** (`--frontend devices`, `primus` backend): Monitor (auto-syncing device grid, bulk rename/apply), Firmware — no Look Designer/Cue Controller, no manual connect/disconnect

Each app serves its own frontend at `/primus`, `/radius`, or `/devices` on the **same unified server** — shared `/css/` and `/js/` assets, separate Alpine SPAs. DeviceManager reuses the same `device-conn.js` device-action store as PrimusCentral/RadiusCentral.

Shared: **Firmware** (product-specific profiles), **Settings** (network)

## Push sync workflow

1. Import WAV files into the project library (Audio Cues panel).
2. Define cues with per-device play/loop actions referencing library filenames.
3. Click **Sync All** — stops playback on connected nodes, then FTP-uploads missing files to each node's SD root.
4. Poll `GET /api/audio_sync/status` for per-file progress (UI modal handles this automatically).

Pull sync and conflict resolution are **not** implemented in V4 (push-only).

## Packaging

**RadiusCentral:**

```bash
python3 V4/build_sender_app.py --target macos --product radius --name RadiusCentral
```

**PrimusCentral (from V4 unified codebase):**

```bash
python3 V4/build_sender_app.py --target macos --product primus --name PrimusCentral
```

Windows release build:

```powershell
py V4\build_sender_app.py --target windows --product primus --windows-installer
```

Output: `V4/dist/macos/PrimusCentral.app`, `RadiusCentral.app`, or `V4\dist\windows\PrimusCentral.exe`
Bundle IDs: `com.socialbodylab.PrimusCentral` / `com.socialbodylab.RadiusCentral`

See [PACKAGING.md](PACKAGING.md) for signing and release details.

## Protocol

| Opcode | Name | Purpose |
|--------|------|---------|
| 0x6000 | ArtAddress | Rename via NVS |
| 0x8200 | ArtIPConfig | Static IP / DHCP |
| 0x8300 | ArtAudioCmd | play / loop / stop / pause / volume / test_tone / play_cue / loop_cue |
| 0x8301 | ArtFtpCmd | Start/stop FTP server |

**ArtAudioCmd commands:** 0=stop, 1=play, 2=loop, 3=pause, 4=volume, 5=test tone, 6=play cue number, 7=loop cue number. Optional filename (null-terminated ASCII, max 32 bytes) followed by optional uint16 LE duration seconds (0 = full file).

**Device cue map:** `/cues.json` on SD card (loaded at boot). Keys are cue numbers as strings; values are either a WAV filename string or `{"file": "name.wav", "duration": 30}`. Max 64 entries. Edited from the Cue Map panel or via `GET/POST /api/audio/cue_map`.

Capability tag: `PVRAD1|B:v1|IP:D|F:RA`

Track telemetry on UDP 6455: magic `PTR` + playback state + track name.

## Firmware

See [FIRMWARE_DEVELOPMENT.md](FIRMWARE_DEVELOPMENT.md) for protocol notes on both families.

**Primus LED** (NeoPixel costume nodes):

Firmware **3.11+** adds per-output **virtual send resolution** (ArtVirtualResolution `0x8130`): the sender downsamples ArtDmx to fewer RGB triplets (Badge defaults to 1), and the receiver upscales to physical LEDs. Configure per device in the PrimusCentral sidebar **Send px** field or via `POST /api/set_device_virtual_resolution`. See [API_REFERENCE.md](../API_REFERENCE.md) §5.2.

```bash
./V4/Arduino/upload.sh --board v3 --compile
./V4/Arduino/upload.sh -v3 --auto
```

**Radius audio** (VS1053 + SD):

```bash
./V4/Arduino/radius_upload.sh --board radius_v1 --compile
./V4/Arduino/radius_upload.sh --board radius_v1 -ssid "MyRouter" -pw "secret" --auto
```
