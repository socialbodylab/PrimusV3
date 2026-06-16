# Board Upload README

This guide is for uploading PrimusV3 firmware to receiver boards. The active firmware track is **V3.6**, located in `V3_6/Arduino/`. All commands assume your terminal is at the repository root:

```bash
cd /path/to/PrimusV3
```

There are two firmware types:

| Firmware | Hardware | Profiles | Purpose |
|---|---|---|---|
| **LED receiver** | Huzzah32, ESP32 Feather V2, ESP32-S3 Reverse TFT | `-v1` `-v2` `-v3` | NeoPixel / NeoPXL8 LED output |
| **Radius (audio)** | Huzzah32 (headless), ESP32-S3 Reverse TFT | `-rv1` `-rv2` | WAV playback via Music Maker FeatherWing |

---

## Automated Setup (Recommended)

Install Python 3 manually first, then run:

```bash
python3 setup_primus.py
```

The setup script checks what is already installed and only fills in missing pieces: creates/checks `.venv`, installs or reuses Arduino CLI, configures the ESP32 Arduino core, and installs/checks the Arduino libraries needed by the selected profiles.

```bash
python3 setup_primus.py --check          # inspect without installing
python3 setup_primus.py --profiles v2    # install for one profile only
```

Useful setup flags:

| Flag | Use |
|---|---|
| `--check` | Report setup status without installing anything |
| `--profiles v1,v2,v3,rv1,rv2` | Limit which profiles are prepared (defaults to all) |
| `--skip-arduino` | Only create/check the Python environment |
| `--skip-venv` | Skip local `.venv` setup |
| `--arduino-cli /path/to/arduino-cli` | Use a specific Arduino CLI executable |
| `--force` | Refresh setup artifacts where possible |

---

## Manual Setup (Fallback)

### 1. Install Required Tools

#### macOS

```bash
brew install arduino-cli python
```

#### Linux

```bash
sudo apt update
sudo apt install -y curl ca-certificates python3

mkdir -p "$HOME/.local/bin"
curl -fsSL https://raw.githubusercontent.com/arduino/arduino-cli/master/install.sh | BINDIR="$HOME/.local/bin" sh
export PATH="$HOME/.local/bin:$PATH"
echo 'export PATH="$HOME/.local/bin:$PATH"' >> "$HOME/.profile"
```

Most Linux systems also require serial port permissions:

```bash
sudo usermod -aG dialout "$USER"
```

Log out and back in after changing the `dialout` group.

#### Windows

The upload script is easiest to run from WSL:

```powershell
wsl --install
```

Then follow the Linux commands above. Git Bash also works if `arduino-cli` and `python3` are on the PATH.

Verify the tools are available:

```bash
arduino-cli version
python3 --version
```

### 2. Configure Arduino CLI for ESP32

```bash
arduino-cli config init || true
arduino-cli config add board_manager.additional_urls https://espressif.github.io/arduino-esp32/package_esp32_index.json
arduino-cli core update-index
arduino-cli core install esp32:esp32
```

### 3. Install Board Libraries

Run the install command for the profile(s) you plan to use:

```bash
# LED receiver profiles
cd V3_6/Arduino && ./upload.sh -v1 --install
cd V3_6/Arduino && ./upload.sh -v2 --install
cd V3_6/Arduino && ./upload.sh -v3 --install

# Radius audio profiles
cd V3_6/Arduino && ./upload.sh -rv2 --install
cd V3_6/Arduino && ./upload.sh -rv1 --install
```

---

## Board Profiles

### LED Receiver Profiles

These flash `V3_6/Arduino/primusV3_receiver/`.

| Flag | Board | FQBN | Upload speed |
|---|---|---|---|
| `-v1` | Adafruit Huzzah32 / ESP32 Feather | `featheresp32` | 115200 |
| `-v2` | Adafruit Feather ESP32 V2 | `adafruit_feather_esp32_v2` | 115200 |
| `-v3` | Adafruit Feather ESP32-S3 Reverse TFT | `adafruit_feather_esp32s3_reversetft` | 921600 |

Required Arduino libraries by profile:

| Profile | Libraries |
|---|---|
| `-v1` | Adafruit NeoPixel |
| `-v2` | Adafruit NeoPixel |
| `-v3` | Adafruit NeoPXL8, Adafruit ST7735 and ST7789 Library, Adafruit GFX Library |

**Default WiFi**: `OPERADEV` / `torrentoflight` (see [WiFi Credentials](#wifi-credentials) below to override).

### Radius Audio Profiles

These flash `V3_6/Arduino/radiusV2/`.

| Flag | Board | FQBN | Upload speed |
|---|---|---|---|
| `-rv2` | Adafruit Feather ESP32-S3 Reverse TFT | `adafruit_feather_esp32s3_reversetft` | 921600 |
| `-rv1` | Adafruit Huzzah32 (headless, no display) | `featheresp32` | 460800 |

Required Arduino libraries (all profiles):

| Library | Purpose |
|---|---|
| Adafruit VS1053 | WAV playback via Music Maker FeatherWing |
| ArduinoJson | Parsing `/cues.json` from SD card |
| SimpleFTPServer | FTP server for SD card file management |

**Default WiFi**: `OPERADEV` / `torrentoflight` — same as the LED receiver. Use `-ssid` / `-pw` flags to override at flash time (see [WiFi Credentials](#wifi-credentials) below).

---

## WiFi Credentials

Both firmware types default to `OPERADEV` / `torrentoflight`. To compile for a different network without editing source files, pass `-ssid` and `-pw` flags to `upload.sh`:

```bash
# LED receiver — flash for RUR network
cd V3_6/Arduino && ./upload.sh -v3 -ssid "RUR" -pw "rurrurrur" --auto

# Radius — flash for RUR network
cd V3_6/Arduino && ./upload.sh -rv2 -ssid "RUR" -pw "rurrurrur" --auto
cd V3_6/Arduino && ./upload.sh -rv1 -ssid "RUR" -pw "rurrurrur" --auto
```

Credential flags work with all upload modes:

```bash
./upload.sh -rv2 -ssid "RUR" -pw "rurrurrur" --compile
./upload.sh -rv2 -ssid "RUR" -pw "rurrurrur" --auto
./upload.sh -rv2 -ssid "RUR" -pw "rurrurrur" --all
./upload.sh -rv2 -ssid "RUR" -pw "rurrurrur" /dev/cu.usbmodemXXXX
```

These values are compiled into the binary for that build only. They do not modify `config.h`. Quote SSIDs or passwords that contain spaces or shell-special characters.

---

## Find Connected Boards

Plug boards in over USB, then list detected ESP32-like serial ports:

```bash
cd V3_6/Arduino && ./upload.sh --ports
```

Typical port names:

| OS | Example |
|---|---|
| macOS | `/dev/cu.usbserial-XXXX`, `/dev/cu.usbmodemXXXX` |
| Linux | `/dev/ttyUSB0`, `/dev/ttyACM0` |
| Windows | `COM3`, `COM4` |

If no board appears, check that you are using a USB data cable (not charge-only). V1/V2 Huzzah32 boards may need the Silicon Labs CP210x USB-to-UART driver.

---

## Upload Commands

### One connected board

```bash
cd V3_6/Arduino && ./upload.sh -v3 --auto      # LED receiver V3.1
cd V3_6/Arduino && ./upload.sh -rv2 --auto     # Radius V2 (display)
cd V3_6/Arduino && ./upload.sh -rv1 --auto     # Radius V1 (headless)
```

`--auto` compiles first, then uploads to the single detected ESP32 port.

### Multiple boards of the same type

```bash
cd V3_6/Arduino && ./upload.sh -v3 --all
cd V3_6/Arduino && ./upload.sh -rv2 --all
```

`--all` compiles once, then uploads sequentially to every detected ESP32-like port. Run `--ports` first to confirm which ports will be targeted.

### Explicit ports

```bash
cd V3_6/Arduino && ./upload.sh -rv2 /dev/cu.usbmodemXXXX
cd V3_6/Arduino && ./upload.sh -v1 /dev/cu.usbserial-XXXX /dev/cu.usbserial-YYYY
```

### Compile only (no upload)

```bash
cd V3_6/Arduino && ./upload.sh -v1 --compile
cd V3_6/Arduino && ./upload.sh -v2 --compile
cd V3_6/Arduino && ./upload.sh -v3 --compile
cd V3_6/Arduino && ./upload.sh -rv2 --compile
cd V3_6/Arduino && ./upload.sh -rv1 --compile
```

---

## Arduino IDE Fallback

The upload script is the recommended path. If you need to use Arduino IDE:

### LED receiver

Open: `V3_6/Arduino/primusV3_receiver/primusV3_receiver.ino`

Add the Espressif package index in Preferences:

```
https://espressif.github.io/arduino-esp32/package_esp32_index.json
```

Install libraries from Library Manager:

| Profile | Libraries |
|---|---|
| `v1`, `v2` | Adafruit NeoPixel |
| `v3` | Adafruit NeoPXL8, Adafruit ST7735 and ST7789 Library, Adafruit GFX Library |

Select board and upload speed:

| Profile | Arduino IDE board | Upload speed |
|---|---|---|
| `v1` | Adafruit ESP32 Feather / Huzzah32 | 115200 |
| `v2` | Adafruit Feather ESP32 V2 | 115200 |
| `v3` | Adafruit Feather ESP32-S3 Reverse TFT | 921600 |

The firmware defaults to the V3.1 profile. For V1 or V2, temporarily define the matching profile near the top of `config.h`:

```cpp
#define PRIMUS_PROFILE_V1   // or PRIMUS_PROFILE_V2
```

Remove the temporary definition before building for another profile.

### Radius firmware

Open: `V3_6/Arduino/radiusV2/radiusV2.ino`

Install libraries from Library Manager:

- Adafruit VS1053
- ArduinoJson
- SimpleFTPServer

Select board and upload speed:

| Profile | Arduino IDE board | Upload speed | Extra build flag |
|---|---|---|---|
| `rv2` | Adafruit Feather ESP32-S3 Reverse TFT | 921600 | *(none — default)* |
| `rv1` | Adafruit ESP32 Feather / Huzzah32 | 460800 | `TARGET_BOARD=2` |

For `rv1`, add this in Arduino IDE Preferences → "Additional build flags":

```
-DTARGET_BOARD=2
```

SimpleFTPServer also requires two build flags that the upload script sets automatically. For Arduino IDE, add all three together:

```
-DTARGET_BOARD=2 -DDEFAULT_FTP_SERVER_NETWORK_TYPE_ESP32=6 -DDEFAULT_STORAGE_TYPE_ESP32=5
```

For `rv2`, only the FTP flags are needed:

```
-DDEFAULT_FTP_SERVER_NETWORK_TYPE_ESP32=6 -DDEFAULT_STORAGE_TYPE_ESP32=5
```

---

## Quick Reference

```bash
# List connected boards
cd V3_6/Arduino && ./upload.sh --ports

# ── LED receiver ────────────────────────────────────────────────
# Compile only
./upload.sh -v3 --compile

# Flash one board (V3.1 for RUR router)
./upload.sh -v3 -ssid "RUR" -pw "rurrurrur" --auto

# Flash all boards of the same type
./upload.sh -v3 -ssid "RUR" -pw "rurrurrur" --all

# ── Radius audio ────────────────────────────────────────────────
# Flash one Radius V2 (display) for RUR network
./upload.sh -rv2 -ssid "RUR" -pw "rurrurrur" --auto

# Flash one Radius V1 (headless) for RUR network
./upload.sh -rv1 -ssid "RUR" -pw "rurrurrur" --auto

# Compile only
./upload.sh -rv2 --compile
./upload.sh -rv1 --compile
```

---

## Further Reading

- [V3_6/FIRMWARE_DEVELOPMENT.md](V3_6/FIRMWARE_DEVELOPMENT.md) — firmware profiles, pins, protocol, and validation
- [DEVELOPER_COMMANDS.md](DEVELOPER_COMMANDS.md) — sender startup, test suite, WAV file tools
- [API_REFERENCE.md](API_REFERENCE.md) — Art-Net opcodes, HTTP API, audio sync protocol
