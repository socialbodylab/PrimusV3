# Board Profiles — FQBNs, Cores, and Libraries

How to declare board profiles in your AUS script, plus a reference table of common Arduino-compatible boards.

## The anatomy of a profile

A profile pins four things:

1. **FQBN** — the `packager:arch:board_id` string `arduino-cli` uses to select the build target.
2. **Default baud** — the upload speed. Too high can fail on long USB cables; too low wastes time.
3. **Required libraries** — auto-installed on first run via `arduino-cli lib install`.
4. **Port-detection signals** — USB VIDs and keywords used to identify the board when auto-detecting.

Optionally: compiler `-D` defines, a human description, the board core (for auto-install), and the board-manager URL (for non-default cores).

## How to declare one

```bash
aus_register_board <name> \
  --fqbn "<fqbn>" \
  --baud <n> \
  --libs "<lib1> <lib2>" \
  --define "-DPROFILE_<NAME>" \
  --desc "<human description>" \
  --vids "<vid1>,<vid2>" \
  --keywords "<kw1>,<kw2>" \
  --default
```

Or use a preset via the scaffolder:

```bash
./new_aus_script.sh --name myboard --preset esp32-feather --output upload.sh
```

## Selecting at runtime

```bash
./upload.sh --board v2 --auto
./upload.sh --board feather-s3 --compile
```

Without `--board`, the profile marked `--default` (or the first registered) is used.

---

## Common boards reference

FQBNs use the format `packager:architecture:board_id`. The packager maps to a board-manager URL that the library auto-registers.

### ESP32 (Espressif arduino-esp32 core)

Packager: `esp32`. Core: `esp32:esp32`. Board-manager URL: `https://espressif.github.io/arduino-esp32/package_esp32_index.json`.

| Board | FQBN | Typical baud | Notes |
|---|---|---|---|
| Adafruit HUZZAH32 Feather | `esp32:esp32:featheresp32` | 115200 | CP210x USB-serial. |
| Adafruit Feather ESP32 V2 | `esp32:esp32:adafruit_feather_esp32_v2` | 115200 | 2025 redesign. |
| Adafruit Feather ESP32-S3 Reverse TFT | `esp32:esp32:adafruit_feather_esp32s3_reversetft` | 921600 | Native USB. |
| Adafruit Feather ESP32-S2 | `esp32:esp32:adafruit_feather_esp32s2` | 921600 | Native USB. |
| Adafruit ESP32 Feather V2 | `esp32:esp32:adafruit_feather_esp32_v2` | 115200 | |
| Espressif ESP32 Dev Module | `esp32:esp32:esp32` | 921600 | Generic; most breakout boards. |
| Espressif ESP32-S3 Dev Module | `esp32:esp32:esp32s3` | 921600 | |
| Espressif ESP32-C3 Dev Module | `esp32:esp32:esp32c3` | 460800 | RISC-V. |
| LilyGO TTGO T-Display | `esp32:esp32:ttgo-lora32-series` | 921600 | Check exact variant. |
| M5Stack Core / M5StickC | varies; usually `esp32:esp32:m5stack-core` or generic `esp32` | 921600 | |

**Common FQBN options** (append after the board id with `:`, comma-separated):
- `UploadSpeed=921600` (set automatically by AUS from `--baud`)
- `PartitionScheme=default`
- `FlashMode=qio`
- `PSRAM=disabled`

**Common libraries:** Adafruit NeoPixel, Adafruit GFX, WiFi (core), Preferences (core).

### ESP8266 (ESP8266 Community core)

Packager: `esp8266`. Core: `esp8266:esp8266`. Board-manager URL: `https://arduino.esp8266.com/stable/package_esp8266com_index.json`.

| Board | FQBN | Typical baud | Notes |
|---|---|---|---|
| NodeMCU 1.0 | `esp8266:esp8266:nodemcuv2` | 921600 | CH340 USB-serial. |
| Wemos D1 mini | `esp8266:esp8266:d1_mini` | 921600 | CH340. |
| ESP-12 | `esp8266:esp8266:generic` | 115200 | Bare module. |
| Adafruit Feather HUZZAH ESP8266 | `esp8266:esp8266:huzzah` | 115200 | CP210x. |

### AVR Arduino (classic)

Packager: `arduino`. Core: `arduino:avr`. Default board-manager URL (no extra registration needed).

| Board | FQBN | Typical baud | Notes |
|---|---|---|---|
| Arduino Uno | `arduino:avr:uno` | 115200 | ATmega328P, 16 MHz. |
| Arduino Nano | `arduino:avr:nano` | 57600 | ATmega328P. |
| Arduino Mega 2560 | `arduino:avr:mega` | 115200 | ATmega2560. |
| Arduino Leonardo | `arduino:avr:leonardo` | 115200 | Native USB; no reset button press. |
| Arduino Micro | `arduino:avr:micro` | 115200 | Native USB. |
| Arduino Pro Mini | `arduino:avr:pro` | 57600 | 5V/16MHz or 3.3V/8MHz variants. |

**AVR port-detection VIDs:** `2341` (Arduino), `2a03` (Arduino clone), `0403` (FTDI FT232), `1a86` (CH340).

**Common libraries:** many. Library auto-install works the same as ESP32.

### SAMD Arduino (ARM Cortex-M0+)

Packager: `arduino`. Core: `arduino:samd`. Default board-manager URL.

| Board | FQBN | Typical baud | Notes |
|---|---|---|---|
| Arduino Zero | `arduino:samd:arduino_zero_native` | 115200 | Native USB. |
| Arduino MKR1000 | `arduino:samd:mkr1000` | 115200 | |
| Arduino MKR WiFi 1010 | `arduino:samd:mkrwifi1010` | 115200 | |
| Arduino Nano 33 IoT | `arduino:samd:nano_33_iot` | 115200 | |
| Adafruit Feather M0 | `adafruit:samd:adafruit_feather_m0` | 115200 | Requires Adafruit board package. |

### RP2040 (earlephilhower arduino-pico core)

Packager: `rp2040`. Core: `rp2040:rp2040`. Board-manager URL: `https://github.com/earlephilhower/arduino-pico/releases/download/global/package_rp2040_index.json`.

| Board | FQBN | Typical baud | Notes |
|---|---|---|---|
| Raspberry Pi Pico | `rp2040:rp2040:rpipico` | 115200 | VID `2e8a`. |
| Raspberry Pi Pico W | `rp2040:rp2040:rpipicow` | 115200 | Has WiFi. |
| Adafruit Feather RP2040 | `rp2040:rp2040:adafruit_feather` | 115200 | |
| Arduino Nano RP2040 Connect | `rp2040:rp2040:nanorp2040connect` | 115200 | |

### Adafruit boards (adafruit packager)

Many Adafruit boards have both an Adafruit packager entry and a mainstream one. For boards like Feather M0/M4, you may need the Adafruit board package:

Board-manager URL: `https://github.com/adafruit/arduino-board-index/zipball/master`.

---

## Choosing port-detection VIDs and keywords

If `--auto` doesn't find your board, the profile's VID set or keyword list is too narrow. Override:

```bash
aus_register_board custom \
  --fqbn "mycore:arch:myboard" \
  --vids "1234,5678" \
  --keywords "myboard,custom,vendorname"
```

To find the right values, plug in your board and run:

```bash
./upload.sh --ports-json | python3 -m json.tool
```

Look for your board in the `ports` array — note its `vid` and any identifying strings in `label`/`protocol`. Add them to the profile.

The default VID set (ESP32-leaning) is: `10c4,1a86,303a,239a,0403`. These cover:
- `10c4` — Silicon Labs CP210x (most ESP32 dev boards)
- `1a86` — QinHeng CH340/CH910 (cheap ESP32 / ESP8266 / AVR clones)
- `303a` — Espressif native USB (ESP32-S3, ESP32-C3, ESP32-S2)
- `239a` — Adafruit
- `0403` — FTDI FT232 (classic Arduino, FTDI cables)

---

## Multiple profiles in one script

Common when the same firmware runs on multiple boards (different pinouts, different features):

```bash
aus_register_board v1 \
  --fqbn "esp32:esp32:featheresp32" \
  --define "-DPROFILE_V1" \
  --baud 115200 \
  --default

aus_register_board v2 \
  --fqbn "esp32:esp32:adafruit_feather_esp32s3_reversetft" \
  --define "-DPROFILE_V2" \
  --baud 921600
```

Then in firmware:

```c
#if defined(PROFILE_V1)
  #define LED_PIN 12
#elif defined(PROFILE_V2)
  #define LED_PIN 5
#endif
```

---

## Adding your own preset

Copy `assets/board_profiles/_template.txt` to `<your-board>.txt` and fill it in. The scaffolder will pick it up:

```bash
cp assets/board_profiles/_template.txt assets/board_profiles/myboard.txt
# edit myboard.txt...
./new_aus_script.sh --name myproject --preset myboard --output upload.sh
```

Preset format is plain `KEY=VALUE` lines:

```
NAME=default
FQBN=mycore:arch:myboard
BAUD=115200
LIBS=My Library One,My Library Two
DESC=My custom board
VIDS=1234,5678
KEYWORDS=keyword1,keyword2
```
