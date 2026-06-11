# PrimusV3 Hardware Wiring — Radius V2

Wiring guide for the Radius V2 audio node: ESP32-S3 Reverse TFT Feather + Music Maker FeatherWing.

---

## Boards

| Board                        | Adafruit Product                               | Role                                     |
|------------------------------|------------------------------------------------|------------------------------------------|
| ESP32-S3 Reverse TFT Feather | [#5691](https://www.adafruit.com/product/5691) | Main controller (WiFi, Art-Net, display) |
| Music Maker FeatherWing      | [#3357](https://www.adafruit.com/product/3357) | VS1053 codec + microSD card (stacks on Feather) |

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

## Adafruit Music Maker FeatherWing (#3357)

**Form factor:** Standard Feather (stacks directly on Feather headers — no breadboard wiring needed).

**Chip:** VLSI VS1053B — hardware audio codec. Decodes WAV, MP3, AAC, OGG, MIDI, FLAC in silicon. The host MCU streams raw file bytes over SPI; the VS1053 handles all decoding and drives the audio output directly. No audio processing required in firmware.

**Outputs:** 3.5mm stereo headphone jack (also usable as line-out into an amplifier).

**Storage:** MicroSD card slot, accessed over a separate SPI chip select. Shares MOSI/MISO/SCK with the VS1053 but uses an independent CS line.

```
        Adafruit Music Maker FeatherWing (#3357)
        ┌──────────────[USB passthrough]────────────┐  ← RST end
        │                                           │
 L1  RST│  ○                               ○  │BAT    R1
 L2   3V│  ○                               ○  │EN     R2
 L3 AREF│  ○                               ○  │USB    R3
 L4  GND│  ○                               ○  │D13    R4
 L5   A0│  ○                               ○  │D12    R5
 L6   A1│  ○    [VS1053B]  [microSD]       ○  │D11    R6
 L7   A2│  ○                               ○  │D10    R7
 L8   A3│  ○                               ○  │D9     R8
 L9   A6│  ○  ← SD_CS                     ○  │D6     R9
L10   A7│  ○  ← VS1053 CS                 ○  │D5     R10
L11   A8│  ○  ← DREQ (data request)       ○  │RX     R11
L12   A9│  ○  ← DCS  (data chip select)   ○  │TX     R12
        │                   [3.5mm jack]   ○  │SDA    R13
        │                                  ○  │SCL    R14
        │                                  ○  │SCK    R15
        │                                  ○  │MOSI   R16
        │                                  ○  │MISO   (inner row)
        └───────────────────────────────────────┘
```

### SPI connections (HUZZAH32)

The Music Maker uses 4 dedicated control pins plus the shared SPI bus.

**Control pins**

| Signal       | HUZZAH32 Label | GPIO | Function                                   |
|--------------|----------------|------|--------------------------------------------|
| VS1053 CS    | A7             | 32   | Chip select — command/data SPI access      |
| VS1053 DCS   | A9             | 33   | Data chip select — streaming audio data    |
| VS1053 DREQ  | A8             | 15   | Data request — signals VS1053 buffer ready |
| SD CS        | A6             | 14   | SD card chip select                        |

**Shared SPI bus** (standard Feather SPI pins, shared with other devices)

| Signal | HUZZAH32 Label | GPIO |
|--------|----------------|------|
| MOSI   | MOSI           | 18   |
| MISO   | MISO           | 19   |
| SCK    | SCK            | 5    |

### Pin definitions in `config.h`

```cpp
// GPIO6–11 on ESP32 are internal flash SPI and must NOT be used as GPIO
#define MM_CS_PIN    32  // GPIO32 (A7) — VS1053 chip select
#define MM_DCS_PIN   33  // GPIO33 (A9) — VS1053 data chip select
#define MM_DREQ_PIN  15  // GPIO15 (A8) — VS1053 data request
#define MM_SDCS_PIN  14  // GPIO14 (A6) — SD card chip select
```

### Volume

The VS1053 has a hardware volume register: 0 = max, 254 = silent. The firmware maps the 0–100 UI range to this scale:

```cpp
uint8_t vs1053vol = (uint8_t)((100 - volume) * 254 / 100);
_musicMaker.setVolume(vs1053vol, vs1053vol);  // left, right
```

`setVolume()` can be called at any time without interrupting playback — used for the live volume slider in the sender UI.

---

## References

| Source | URL / Path |
|--------|------------|
| Music Maker FeatherWing overview | https://learn.adafruit.com/adafruit-music-maker-featherwing |
| Music Maker FeatherWing pinouts | https://learn.adafruit.com/adafruit-music-maker-featherwing/pinouts |
| VS1053B datasheet | https://www.vlsi.fi/fileadmin/datasheets/vs1053.pdf |
| ESP32-S3 Reverse TFT Feather pinout | https://learn.adafruit.com/esp32-s3-reverse-tft-feather/pinouts |
| ESP32-S3 Reverse TFT Feather Fritzing part (physical layout) | https://github.com/adafruit/Fritzing-Library/blob/master/parts/Adafruit%20ESP32-S3%20Reverse%20TFT%20Feather.fzpz |
| ESP32-S3 Reverse TFT Feather official pinout SVG | https://github.com/adafruit/Adafruit-ESP32-S3-Reverse-TFT-Feather-PCB/blob/main/Adafruit_ESP32-S3_Reverse_TFT_Feather_Pinout.svg |
| GPIO numbers (`pins_arduino.h`) | `~/Library/Arduino15/packages/esp32/hardware/esp32/3.3.5/variants/adafruit_feather_esp32s3_reversetft/pins_arduino.h` |
| PrimusV3 firmware config | `V3_2/Arduino/radiusV2/config.h` |

---

---

# Future Research / Archived Audio Hardware

The following hardware was tested as alternatives to the Music Maker FeatherWing but was not successful. Kept here for future reference.

---

## Adafruit Audio BFF (#5769)

**Status:** Unsuccessful. I2S audio via ESP8266Audio library did not produce reliable output. All firmware support removed as of 2026-06-11.

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

### Breadboard Wiring — Audio BFF → Feather

Position counting:
- **BFF** — L or R side, numbered from the **JST speaker connector end** (closest pin = 1)
- **Feather** — all used pins are on the right side, numbered from the **USB-C connector end** (closest pin = 1)

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

### References

| Source | URL / Path |
|--------|------------|
| Audio BFF pinout | https://learn.adafruit.com/adafruit-audio-bff/pinouts |
| Audio BFF Fritzing part (physical layout) | https://github.com/adafruit/Fritzing-Library/blob/master/parts/Adafruit%20Audio%20BFF.fzpz |
| Audio BFF downloads page | https://learn.adafruit.com/adafruit-audio-bff/downloads |

---

## Adafruit PCM5102 Stereo I2S DAC (#6250)

**Status:** Researched but not tested in firmware. Line-level output — requires powered speakers or amplifier.

**Form factor:** Small breakout board (32.5 × 20.3 mm) with 3.5mm stereo jack and solder pads. Cannot drive headphones directly (minimum 1 kΩ load).

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

Bottom row — 8 pads in a single line:

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

**Power and configuration (4 connections)**

| PCM5102 Pad | Connect to    | Notes |
|-------------|---------------|-------|
| VIN (pad 1) | Feather 3V (R2) | Power |
| GND (pad 2) | Feather GND (R4) | Ground |
| MU  (T4)    | Feather 3V    | Un-mute — **required or output is silent** |
| FM  (T5)    | GND           | I²S format — **required or audio is garbled** |

**I2S audio (3 signal wires)**

| PCM5102 Pad | Signal              | Feather Label | Feather Pos | GPIO |
|-------------|---------------------|---------------|-------------|------|
| BCK  (pad 5) | Bit clock          | A3            | R8          | 15   |
| WSEL (pad 3) | Word select (LRCK) | A2            | R7          | 16   |
| DIN  (pad 4) | Data in            | A1            | R6          | 17   |

Note: I2S pins are the same as the Audio BFF wiring above — both share the A1/A2/A3 signals.
