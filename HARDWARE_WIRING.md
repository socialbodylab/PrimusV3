# PrimusV3 Hardware Wiring — Radius V2

Breadboard wiring guide for the Radius V2 using the Adafruit ESP32-S3 Reverse TFT Feather and the Adafruit Audio BFF.

---

## Boards

| Board                        | Adafruit Product                               | Role                                     |
|------------------------------|------------------------------------------------|------------------------------------------|
| ESP32-S3 Reverse TFT Feather | [#5691](https://www.adafruit.com/product/5691) | Main controller (WiFi, Art-Net, display) |
| Audio BFF                    | [#5769](https://www.adafruit.com/product/5769) | MAX98357 I2S amplifier + microSD card    |

---

## Adafruit Audio BFF (#5769)

**Form factor:** QT Py / Xiao (7 pins per side). Designed to stack on the back of a QT Py, but wired manually to the Feather headers on a breadboard.

```
        Adafruit Audio BFF (#5769)
        ┌──────────────────────────────┐
        ║   [Speaker PicoBlade ±]      ║  ← JST speaker connector (pin 1 end)
        ╠═══╗                    ╔═══╣
L1   5V ║ ○ ║                    ║ ○ ║ SD_CS  R1
L2  GND ║ ○ ║                    ║ ○ ║ DIN    R2
L3 3.3V ║ ○ ║     MAX98357A      ║ ○ ║ LRCLK  R3
L4 MOSI ║ ○ ║                    ║ ○ ║ BCLK   R4
L5 MISO ║ ○ ║    [microSD slot]  ║ ○ ║ SDA    R5
L6  SCK ║ ○ ║                    ║ ○ ║ SCL    R6
L7   RX ║ ○ ║                    ║ ○ ║ TX     R7
        ╚═══╝                    ╚═══╝
```

**Pin descriptions:**

| BFF pin   | Function                   | Notes                              |
|-----------|----------------------------|------------------------------------|
| SD_CS     | SD card chip select        |                                    |
| DIN       | I2S audio data in          |                                    |
| LRCLK     | I2S word select (LR clock) |                                    |
| BCLK      | I2S bit clock              |                                    |
| MOSI      | SD card SPI data out       |                                    |
| MISO      | SD card SPI data in        |                                    |
| SCK       | SD card SPI clock          |                                    |
| VO+ / VO− | Speaker output             | 2-pin PicoBlade connector on board |

**Back of board — gain jumper:**

| Solder pad                      | Gain  |
|---------------------------------|-------|
| Top (connects GAIN → 5V)        | 6 dB  |
| Centre (default, GAIN floating) | 9 dB  |
| Bottom (connects GAIN → GND)    | 12 dB |

---

## Adafruit ESP32-S3 Reverse TFT Feather (#5691)

**Form factor:** Standard Feather (12-pin side + 16-pin side). TFT display faces the back/bottom of the board.

```
     Adafruit ESP32-S3 Reverse TFT Feather (#5691)
     ┌──────────────[USB-C]──────────────┐   ← pin 1 end
     │                                   │
L1   │  ○ VBAT                     RST ○ │   R1
L2   │  ○ EN                        3V ○ │   R2
L3   │  ○ VBUS (5V)                 3V ○ │   R3  ← AREF pad, tied to 3V
L4   │  ○ D13   GPIO13             GND ○ │   R4
L5   │  ○ D12   GPIO12   GPIO18     A0 ○ │   R5
L6   │  ○ D11   GPIO11   GPIO17     A1 ○ │   R6
L7   │  ○ D10   GPIO10   GPIO16     A2 ○ │   R7
L8   │  ○ D9    GPIO9    GPIO15     A3 ○ │   R8
L9   │  ○ D6    GPIO6    GPIO14     A4 ○ │   R9
L10  │  ○ D5    GPIO5    GPIO8      A5 ○ │   R10
L11  │  ○ SCL   GPIO4    GPIO36    SCK ○ │   R11
L12  │  ○ SDA   GPIO3    GPIO35   MOSI ○ │   R12
     │                   GPIO37   MISO ○ │   R13
     │                   GPIO38     RX ○ │   R14
     │                   GPIO39     TX ○ │   R15
     │                   GPIO43   TXD0 ○ │   R16  ← debug serial TX only
     │                                   │
     │  [STEMMA QT]  GND/3V/SDA/SCL      │  ← short edge near USB
     │  [240×135 TFT display, rear-facing]│
     └───────────────────────────────────┘
```

**Pins used internally (not broken out to headers):**

| Signal         | GPIO | Used for            |
|----------------|------|---------------------|
| TFT_CS         | 42   | Built-in display    |
| TFT_DC         | 40   | Built-in display    |
| TFT_RST        | 41   | Built-in display    |
| TFT_BACKLIGHT  | 45   | Built-in display    |
| TFT_I2C_POWER  | 7    | Display power rail  |
| NEOPIXEL       | 33   | Onboard RGB LED     |
| NEOPIXEL_POWER | 21   | NeoPixel power rail |

---

## Breadboard Wiring — Audio BFF → Feather

Radius nodes never carry NeoPXL8 / LED outputs — those are separate V3.1 (Primus) hardware. The BFF signals connect to the A-pin row, which is free on Radius nodes.

Position counting:
- **BFF** — L or R side, numbered from the **JST speaker connector end** (closest pin = 1)
- **Feather** — all used pins are on the right side, numbered from the **USB-C connector end** (closest pin = 1). Labels are on the underside when the board is mounted, so counting from USB-C is the reliable reference.

**Power**

| BFF Label | BFF Pos | Feather Label | Feather Pos |
|-----------|---------|---------------|-------------|
| 3.3V      | L3      | 3V            | R2          |
| GND       | L2      | GND           | R4          |

**I2S audio**

| BFF Label | BFF Pos | Signal      | Feather Label | Feather Pos |
|-----------|---------|-------------|---------------|-------------|
| BCLK      | R4      | Bit clock   | A3            | R8          |
| LRCLK     | R3      | Word select | A2            | R7          |
| DIN       | R2      | Data in     | A1            | R6          |

**SD card**

| BFF Label | BFF Pos | Signal      | Feather Label | Feather Pos |
|-----------|---------|-------------|---------------|-------------|
| SD_CS     | R1      | Chip select | A0            | R5          |
| MOSI      | L4      | SPI MOSI    | MOSI          | R12         |
| MISO      | L5      | SPI MISO    | MISO          | R13         |
| SCK       | L6      | SPI clock   | SCK           | R11         |

These are the default pin definitions in `config.h`:
```cpp
#define BFF_BCK_PIN  15  // A3 — I2S bit clock
#define BFF_WS_PIN   16  // A2 — I2S word select
#define BFF_DATA_PIN 17  // A1 — I2S data
#define BFF_SDCS_PIN 18  // A0 — SD chip select
```

The firmware selects the audio board automatically based on the target hardware:

| Build target                        | `AUDIO_BOARD` default              | Wiring                                                              |
|-------------------------------------|------------------------------------|---------------------------------------------------------------------|
| ESP32-S3 Reverse TFT Feather        | `AUDIO_BOARD_BFF` (MAX98357 I2S)   | Breadboard wires per table above                                    |
| Huzzah32 (`--board feather-esp32`)  | `AUDIO_BOARD_MUSIC_MAKER` (VS1053) | Music Maker stacks on Feather header, no breadboard wiring needed   |

To override the default for a given build, define `AUDIO_BOARD` before `config.h` is included, or edit the conditional block in `config.h` directly.

---

---

## Adafruit PCM5102 Stereo I2S DAC (#6250)

**Form factor:** Small breakout board (32.5 × 20.3 mm) with 3.5mm stereo jack and solder pads. Line-level output — requires powered speakers or amplifier (minimum 1 kΩ load; cannot drive headphones directly).

**Chip:** Texas Instruments PCM5102A. The chip datasheet calls the word clock pin **LRCK**; Adafruit's silkscreen labels it **WSEL** — these are the same signal.

```
     Adafruit PCM5102 I2S DAC (#6250)
     ┌──────────────────────────────────────────────────────────────┐
     │   ○    ○    ○    ○    ○    ○   [*]                          │
     │   DE  FIL  MCK   MU   FM   3V                               │
     │  (T1) (T2) (T3) (T4) (T5) (T6)                  [3.5mm] ==│
     │                                                             │
     │              [PCM5102A]                                     │
     │                                                             │
     │   ○    ○    ○    ○    ○    ○    ○    ○                      │
     │  (1)  (2)  (3)  (4)  (5)  (6)  (7)  (8)                    │
     │  VIN  GND WSEL  DIN  BCK  Lout   G  Rout                   │
     └──────────────────────────────────────────────────────────────┘
```

Bottom row — 8 pads in a single line, labels offset on silkscreen:

| # | Pad  | Function |
|---|------|----------|
| 1 | VIN  | Power input (3.3–5V) |
| 2 | GND  | Ground |
| 3 | WSEL | I²S word select / LRCK |
| 4 | DIN  | I²S data in |
| 5 | BCK  | I²S bit clock |
| 6 | Lout | Left audio output (same as 3.5mm L) |
| 7 | G    | Analog audio ground |
| 8 | Rout | Right audio output (same as 3.5mm R) |

Top control pads (T1–T6, left → right with jack at right):

| Pad | Label | Function | Default | For this project |
|-----|-------|----------|---------|-----------------|
| T1  | DE    | De-emphasis for 44.1 kHz | OFF | Leave floating |
| T2  | FIL   | Filter: LOW=normal, HIGH=low-latency | Normal | Leave floating |
| T3  | MCK   | Master clock input | Auto (from BCK) | Leave floating |
| T4  | MU    | Mute / XSMT: LOW=muted, HIGH=active | — | **Tie to 3.3V** |
| T5  | FM    | Format: LOW=I²S, HIGH=left-justified | — | **Tie to GND** |
| T6  | 3V    | 3.3V output from onboard regulator | — | Do not connect |

### Breadboard Wiring — PCM5102 → Feather

**Power and configuration (5 connections)**

| PCM5102 Pad | Connect to    | Notes |
|-------------|---------------|-------|
| VIN (B1 upper) | Feather 3V (R2) | Power |
| GND (B1 lower) | Feather GND (R4) | Ground |
| MU  (T4)    | Feather 3V    | Un-mute — **required or output is silent** |
| FM  (T5)    | GND           | I²S format — **required or audio is garbled** |

**I2S audio (3 signal wires)**

| PCM5102 Pad | Signal              | Feather Label | Feather Pos | GPIO |
|-------------|---------------------|---------------|-------------|------|
| BCK  (pad 5) | Bit clock          | A3            | R8          | 15   |
| WSEL (pad 3) | Word select (LRCK) | A2            | R7          | 16   |
| DIN  (pad 4) | Data in            | A1            | R6          | 17   |

### Config.h pin definitions (same as BFF — no firmware changes needed)

```cpp
#define BFF_BCK_PIN  15  // A3 — I2S bit clock  → PCM5102 BCK
#define BFF_WS_PIN   16  // A2 — I2S word select → PCM5102 WSEL (LRCK)
#define BFF_DATA_PIN 17  // A1 — I2S data out   → PCM5102 DIN
```

---

## References

| Source | URL / Path |
|--------|------------|
| Audio BFF pinout | https://learn.adafruit.com/adafruit-audio-bff/pinouts |
| Audio BFF Fritzing part (physical layout) | https://github.com/adafruit/Fritzing-Library/blob/master/parts/Adafruit%20Audio%20BFF.fzpz |
| Audio BFF downloads page | https://learn.adafruit.com/adafruit-audio-bff/downloads |
| ESP32-S3 Reverse TFT Feather pinout | https://learn.adafruit.com/esp32-s3-reverse-tft-feather/pinouts |
| ESP32-S3 Reverse TFT Feather Fritzing part (physical layout) | https://github.com/adafruit/Fritzing-Library/blob/master/parts/Adafruit%20ESP32-S3%20Reverse%20TFT%20Feather.fzpz |
| ESP32-S3 Reverse TFT Feather official pinout SVG | https://github.com/adafruit/Adafruit-ESP32-S3-Reverse-TFT-Feather-PCB/blob/main/Adafruit_ESP32-S3_Reverse_TFT_Feather_Pinout.svg |
| GPIO numbers (`pins_arduino.h`) | `~/Library/Arduino15/packages/esp32/hardware/esp32/3.3.5/variants/adafruit_feather_esp32s3_reversetft/pins_arduino.h` |
| PrimusV3 firmware config | `V3_2/Arduino/radiusV2/config.h` |
