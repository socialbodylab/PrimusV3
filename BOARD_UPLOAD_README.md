# Board Upload README

This guide is for someone who has already cloned the PrimusV3 repository and needs to upload V3.5 firmware to receiver boards for the first time.

All project commands below assume your terminal is at the repository root:

```bash
cd /path/to/PrimusV3
```

## Automated Setup (Recommended)

Install Python 3 manually first, then run:

```bash
python3 setup_primus.py
```

The setup script checks what is already installed and only fills in missing pieces where it can. It creates/checks `.venv`, confirms the sender has no external Python package requirements, installs or reuses Arduino CLI, configures the ESP32 Arduino core, and installs/checks the Arduino libraries needed by the selected board profiles.

To inspect a machine without installing anything:

```bash
python3 setup_primus.py --check
```

To set up only one board family, pass the profile list:

```bash
python3 setup_primus.py --profiles v2
```

After setup, these commands should work:

```bash
.venv/bin/python V3_5/sender/run.py
./V3_5/Arduino/upload.sh --ports
./V3_5/Arduino/upload.sh -v2 --auto
```

Useful setup flags:

| Flag | Use |
| --- | --- |
| `--check` | Report setup status without installing anything. |
| `--profiles v1,v2,v3` | Choose which board profiles to install/check Arduino libraries for. Defaults to all profiles. |
| `--skip-arduino` | Only create/check the Python environment. |
| `--skip-venv` | Skip local `.venv` setup. |
| `--arduino-cli /path/to/arduino-cli` | Use a specific Arduino CLI executable. |
| `--force` | Refresh setup artifacts where possible. |

If automatic Arduino CLI setup is not available on your platform, use the manual setup steps below.

## Manual Setup (Fallback)

### 1. Install Required Tools

The upload script is a Bash script that uses Arduino CLI and Python 3.

Choose the setup commands for your operating system.

#### macOS

Using Homebrew:

```bash
brew install arduino-cli python
```

#### Linux

On Debian/Ubuntu-style systems:

```bash
sudo apt update
sudo apt install -y curl ca-certificates python3

mkdir -p "$HOME/.local/bin"
curl -fsSL https://raw.githubusercontent.com/arduino/arduino-cli/master/install.sh | BINDIR="$HOME/.local/bin" sh
export PATH="$HOME/.local/bin:$PATH"
```

To keep Arduino CLI on your PATH for future terminals:

```bash
echo 'export PATH="$HOME/.local/bin:$PATH"' >> "$HOME/.profile"
```

Most Linux systems also require serial-port permissions before uploading:

```bash
sudo usermod -aG dialout "$USER"
```

Log out and back in after changing the `dialout` group.

#### Windows

The upload script is easiest to run from WSL. Install WSL, open an Ubuntu terminal, then follow the Linux commands above:

```powershell
wsl --install
```

Git Bash can also work if `arduino-cli` and `python3` are on the Git Bash PATH:

```powershell
winget install Git.Git
winget install Python.Python.3
winget install ArduinoSA.CLI
```

After installing, open a new terminal and verify the tools:

```bash
arduino-cli version
python3 --version
```

### 2. Configure Arduino CLI For ESP32

The receiver boards use the Espressif ESP32 Arduino core. Add the ESP32 package index and install the core once:

```bash
arduino-cli config init || true
arduino-cli config dump | grep -q "espressif.github.io/arduino-esp32" || \
  arduino-cli config add board_manager.additional_urls https://espressif.github.io/arduino-esp32/package_esp32_index.json
arduino-cli core update-index
arduino-cli core install esp32:esp32
```

If `config init` reports that a config file already exists, that is fine.

### 3. Install Board Libraries

The upload script can install/check the Arduino libraries required by each selected board profile.

Run the install command for the board type you plan to upload:

```bash
./V3_5/Arduino/upload.sh -v1 --install
./V3_5/Arduino/upload.sh -v2 --install
./V3_5/Arduino/upload.sh -v3 --install
```

Board profile choices:

| Flag | Board profile |
| --- | --- |
| `-v1` | V1 Adafruit Huzzah32 ESP32 Feather |
| `-v2` | V2 Adafruit ESP32 Feather V2 |
| `-v3` | V3.1 ESP32-S3 Reverse TFT Feather with NeoPXL8 FeatherWing |

### 4. Optional WiFi Credential Overrides

By default, the firmware uses the WiFi SSID and password in `V3_5/Arduino/primusV3_receiver/config.h`. To upload firmware for a different router without editing source files, pass credentials to the upload script:

```bash
./V3_5/Arduino/upload.sh -v2 -ssid "PrimusRouter" -pw "router-password" --auto
```

Credential flags work with compile-only, single-board, multi-board, and explicit-port uploads:

```bash
./V3_5/Arduino/upload.sh -v2 -ssid "PrimusRouter" -pw "router-password" --compile
./V3_5/Arduino/upload.sh -v2 -ssid "PrimusRouter" -pw "router-password" --all
./V3_5/Arduino/upload.sh -v2 -ssid "PrimusRouter" -pw "router-password" /dev/cu.usbserial-XXXX
```

These values are compiled into the firmware for that build only. They do not modify `config.h`. Quote SSIDs or passwords that contain spaces or shell-special characters. Be aware that commands typed directly into a terminal may be stored in shell history.

### 5. Optional Compile / Verify

Use `--compile` when you want to check that the firmware builds without uploading. This is like Arduino IDE Verify.

Pick the profile that matches your board:

```bash
./V3_5/Arduino/upload.sh -v1 --compile
./V3_5/Arduino/upload.sh -v2 --compile
./V3_5/Arduino/upload.sh -v3 --compile
```

This step is optional. Upload commands compile automatically before flashing, just like Arduino IDE Upload.

### 6. Find Connected Boards

Plug receiver boards in over USB, then list likely ESP32 serial ports:

```bash
./V3_5/Arduino/upload.sh --ports
```

Typical port names look like:

| OS | Example port |
| --- | --- |
| macOS | `/dev/cu.usbserial-XXXX`, `/dev/cu.usbmodemXXXX` |
| Linux | `/dev/ttyUSB0`, `/dev/ttyACM0` |
| Windows | `COM3`, `COM4` |

If no board appears, check that you are using a USB data cable. For V1/V2 boards, you may also need the Silicon Labs CP210x USB-to-UART driver from the board vendor.

### 7. Upload Firmware

#### One Connected Board

Use `--auto` when exactly one ESP32-like receiver is plugged in. This compiles first, then uploads:

```bash
./V3_5/Arduino/upload.sh -v2 --auto
```

Replace `-v2` with the matching board profile.

#### Multiple Boards Of The Same Type

Use `--all` when every detected ESP32-like serial port should receive the same profile. This compiles once, then uploads sequentially:

```bash
./V3_5/Arduino/upload.sh -v2 --all
```

Run `--ports` first. You do not need to run `--compile` separately before `--all`.

#### Chosen Ports Only

Use explicit ports when auto-detection is ambiguous or mixed board types are connected. This compiles once, then uploads sequentially to the ports you provide:

```bash
./V3_5/Arduino/upload.sh -v1 /dev/cu.usbserial-XXXX /dev/cu.usbserial-YYYY
./V3_5/Arduino/upload.sh -v2 /dev/ttyUSB0 /dev/ttyUSB1
./V3_5/Arduino/upload.sh -v3 COM3
```

## Arduino IDE Upload Fallback

The upload script is the recommended firmware upload path because it selects the correct board profile, checks libraries, chooses the upload speed, handles serial-port selection, and can compile temporary WiFi credential overrides without editing source files. If necessary, the V3.5 receiver firmware can still be uploaded through the Arduino IDE because it is a normal Arduino sketch.

Open this sketch in Arduino IDE:

```text
V3_5/Arduino/primusV3_receiver/primusV3_receiver.ino
```

In Arduino IDE, install the ESP32 board package. Add the Espressif package index in Preferences if it is not already configured:

```text
https://espressif.github.io/arduino-esp32/package_esp32_index.json
```

Install the required libraries from Library Manager:

| Board profile | Required libraries |
| --- | --- |
| `v1` | `Adafruit NeoPixel` |
| `v2` | `Adafruit NeoPixel` |
| `v3` | `Adafruit NeoPXL8`, `Adafruit ST7735 and ST7789 Library`, `Adafruit GFX Library` |

Select the matching board and upload speed:

| Profile | Arduino IDE board | Upload speed |
| --- | --- | --- |
| `v1` | Adafruit ESP32 Feather / Huzzah32-compatible ESP32 Feather | `115200` |
| `v2` | Adafruit Feather ESP32 V2 | `115200` |
| `v3` | Adafruit Feather ESP32-S3 Reverse TFT | `921600` |

### Board Profile Selection In Arduino IDE

The upload script passes one of these compile-time profile flags:

```text
-DPRIMUS_PROFILE_V1
-DPRIMUS_PROFILE_V2
-DPRIMUS_PROFILE_V3_1
```

When no profile flag is supplied, `config.h` defaults to the V3.1 Reverse TFT profile. This means Arduino IDE uploads work directly for V3.1 as long as the correct board, port, upload speed, and libraries are selected.

For V1 or V2 uploads from Arduino IDE, temporarily define the matching profile near the top of `V3_5/Arduino/primusV3_receiver/config.h`, before the default-profile block:

```cpp
#define PRIMUS_PROFILE_V1
```

or:

```cpp
#define PRIMUS_PROFILE_V2
```

Only one profile macro should be active at a time. Remove or change the temporary definition before building for another board profile.

The script's `-ssid` and `-pw` flags are not provided by Arduino IDE. When using the IDE fallback path, WiFi defaults come from `V3_5/Arduino/primusV3_receiver/config.h`, unless you configure custom IDE build flags yourself.

## Quick Reference

```bash
# List boards
./V3_5/Arduino/upload.sh --ports

# Compile only, like Arduino IDE Verify
./V3_5/Arduino/upload.sh -v2 --compile

# Compile with custom WiFi defaults
./V3_5/Arduino/upload.sh -v2 -ssid "PrimusRouter" -pw "router-password" --compile

# Upload one detected board; compiles first automatically
./V3_5/Arduino/upload.sh -v2 --auto

# Upload all detected boards of the same type; compiles first automatically
./V3_5/Arduino/upload.sh -v2 --all

# Upload chosen ports only; compiles first automatically
./V3_5/Arduino/upload.sh -v2 /dev/cu.usbserial-XXXX /dev/cu.usbserial-YYYY
```

More firmware details are in [V3_5/FIRMWARE_DEVELOPMENT.md](V3_5/FIRMWARE_DEVELOPMENT.md).