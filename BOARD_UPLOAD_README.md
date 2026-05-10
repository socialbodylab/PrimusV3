# Board Upload README

This guide is for someone who has already cloned the PrimusV3 repository and needs to upload V3.5 firmware to receiver boards for the first time.

All project commands below assume your terminal is at the repository root:

```bash
cd /path/to/PrimusV3
```

## 1. Install Required Tools

The upload script is a Bash script that uses Arduino CLI and Python 3.

Choose the setup commands for your operating system.

### macOS

Using Homebrew:

```bash
brew install arduino-cli python
```

### Linux

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

### Windows

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

## 2. Configure Arduino CLI For ESP32

The receiver boards use the Espressif ESP32 Arduino core. Add the ESP32 package index and install the core once:

```bash
arduino-cli config init || true
arduino-cli config dump | grep -q "espressif.github.io/arduino-esp32" || \
  arduino-cli config add board_manager.additional_urls https://espressif.github.io/arduino-esp32/package_esp32_index.json
arduino-cli core update-index
arduino-cli core install esp32:esp32
```

If `config init` reports that a config file already exists, that is fine.

## 3. Install Board Libraries

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

## 4. Compile Before Uploading

Compile once before flashing hardware. Pick the profile that matches your board:

```bash
./V3_5/Arduino/upload.sh -v1 --compile
./V3_5/Arduino/upload.sh -v2 --compile
./V3_5/Arduino/upload.sh -v3 --compile
```

## 5. Find Connected Boards

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

## 6. Upload Firmware

### One Connected Board

Use `--auto` when exactly one ESP32-like receiver is plugged in:

```bash
./V3_5/Arduino/upload.sh -v2 --auto
```

Replace `-v2` with the matching board profile.

### Multiple Boards Of The Same Type

Use `--all` when every detected ESP32-like serial port should receive the same profile:

```bash
./V3_5/Arduino/upload.sh -v2 --all
```

Run `--ports` first. `--all` compiles once, then uploads sequentially to each selected port.

### Chosen Ports Only

Use explicit ports when auto-detection is ambiguous or mixed board types are connected:

```bash
./V3_5/Arduino/upload.sh -v1 /dev/cu.usbserial-XXXX /dev/cu.usbserial-YYYY
./V3_5/Arduino/upload.sh -v2 /dev/ttyUSB0 /dev/ttyUSB1
./V3_5/Arduino/upload.sh -v3 COM3
```

## Quick Reference

```bash
# List boards
./V3_5/Arduino/upload.sh --ports

# Compile only
./V3_5/Arduino/upload.sh -v2 --compile

# Upload one detected board
./V3_5/Arduino/upload.sh -v2 --auto

# Upload all detected boards of the same type
./V3_5/Arduino/upload.sh -v2 --all

# Upload chosen ports only
./V3_5/Arduino/upload.sh -v2 /dev/cu.usbserial-XXXX /dev/cu.usbserial-YYYY
```

More firmware details are in [V3_5/FIRMWARE_DEVELOPMENT.md](V3_5/FIRMWARE_DEVELOPMENT.md).