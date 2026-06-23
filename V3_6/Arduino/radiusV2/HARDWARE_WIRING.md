# PrimusV3 Hardware Wiring — Radius V2

Wiring guide for the Radius V2 audio node. Two variants share the same Feather + Music Maker core.

- **Variant A — Headphone / Line-Out:** uses the Music Maker headphone jack directly for headphones or powered speakers
- **Variant B — Amplifier:** adds a MAX9744 Class D amp and passive speakers via TS sockets

---

## Boards

| Board                        | Adafruit Product                               | Role                                              | Variant |
|------------------------------|------------------------------------------------|---------------------------------------------------|---------|
| ESP32-S3 Reverse TFT Feather | [#5691](https://www.adafruit.com/product/5691) | Main controller (WiFi, Art-Net, display)          | A, B    |
| Music Maker FeatherWing      | [#3357](https://www.adafruit.com/product/3357) | VS1053 codec + microSD (stacks on Feather)        | A, B    |
| FeatherWing Doubler          | [#2890](https://www.adafruit.com/product/2890) | Side-by-side board mounting                       | B       |
| MAX9744 20W Stereo Amplifier | [#1752](https://www.adafruit.com/product/1752) | Class D stereo amp, I2C volume control            | B       |
| Speaker 3 in 4 Ω 3 W        | [#1314](https://www.adafruit.com/product/1314) | Passive speaker, 4 Ω, bare wire leads             | B       |

---

## System Wiring Overview

---

### Variant B — Amplifier Build

Feather + Music Maker mounted side-by-side on the Doubler. MAX9744 is off-board, connected by short wires. Each speaker channel uses its own mono TS socket.

```
    ┌──────────────────────────────────────────────────────────────┐
    │  FeatherWing Doubler  (#2890)                                │
    │                                                              │
    │  ┌───────────────────────────┬──────────────────────────┐   │
    │  │  Slot A                   │  Slot B                  │   │
    │  │  ESP32-S3 Reverse TFT     │  Music Maker FeatherWing │   │
    │  │  Feather  #5691           │  #3357                   │   │
    │  └───────────────────────────┴──────────────┬───────────┘   │
    │      │ SDA  GPIO3                           │ 3.5mm out     │
    │      │ SCL  GPIO4                           │               │
    │      │ 3V                                   │               │
    │      │ GND                                  │               │
    └──────┼──────────────────────────────────────┼───────────────┘
           │                                      │
           │  4 × I2C wires                       │  3.5mm stereo cable
           │                                      │
           ▼                                      ▼
    ┌──────────────────────────────────────────────────────────────┐
    │  MAX9744  #1752  —  20W Class D Stereo Amplifier             │
    │                                                              │
    │    ← SDA   ← SCL   ← Vi2c (3 V)   ← GND                    │
    │    ← 3.5mm audio in                                          │
    │    → Left+   → Left−                                         │
    │    → Right+  → Right−                                        │
    │    ← 5 V DC  ≥ 2 A   2.1mm barrel  centre +                 │
    └───────────┬──────────────────────────┬───────────────────────┘
                │ Left channel             │ Right channel
                ▼                          ▼
    ┌──────────────────────┐   ┌──────────────────────┐
    │  TS socket  (mono)   │   │  TS socket  (mono)   │
    │  Tip   = Left+       │   │  Tip   = Right+      │
    │  Sleeve= Left−  *    │   │  Sleeve= Right−  *   │
    └─────────┬────────────┘   └─────────┬────────────┘
              ↓ speaker wire             ↓ speaker wire
    ┌──────────────────────────────────────────────────────────────┐
    │  Speaker(s)  #1314  —  3 in · 4 Ω · 3 W · bare wire leads  │
    └──────────────────────────────────────────────────────────────┘

    * Sleeve carries Left−/Right− (BTL driven output), NOT system ground.
      Do not connect sleeve to chassis or audio ground anywhere on the cable.
```

**Power:** Use 5 V for the #1314 speaker (rated 3 W); higher voltages exceed its power rating. The MAX9744 delivers approximately 2–3 W into 4 Ω at 5 V. Keep volume at or below 80 %.

**TS socket rule:** Each BTL channel requires its own mono TS socket. Do not use a single stereo TRS socket for both channels — the shared TRS sleeve would short Left− to Right−, bridging two BTL half-outputs and potentially damaging the amp.

### Connection Summary — Variant B

| From | Signal | To |
|---|---|---|
| Music Maker 3.5mm jack | Stereo audio out | MAX9744 3.5mm input |
| Feather SDA  (GPIO3) | I²C data | MAX9744 pin 4 — SDA |
| Feather SCL  (GPIO4) | I²C clock | MAX9744 pin 5 — SCL |
| Feather 3V | Logic reference | MAX9744 pin 6 — Vi2c |
| Feather GND | Ground | MAX9744 pin 13 — GND |
| MAX9744 Left+  terminal | Speaker + | TS socket tip (left) |
| MAX9744 Left−  terminal | Speaker − | TS socket sleeve (left, NOT ground) |
| MAX9744 Right+ terminal | Speaker + | TS socket tip (right) |
| MAX9744 Right− terminal | Speaker − | TS socket sleeve (right, NOT ground) |
| 5 V DC supply  (≥ 2 A) | Amplifier power | MAX9744 barrel jack |

---

### Variant A — Headphone / Line-Out Build

No amplifier. Feather stacks directly on the Music Maker — no Doubler required. The VS1053 headphone jack drives headphones directly or feeds a line-level input (powered speaker, mixer, audio interface).

```
    ┌──────────────────────────────────────────────────────────────┐
    │  ESP32-S3 Reverse TFT Feather  (#5691)                      │
    │  +  Music Maker FeatherWing  (#3357)  (stacked)             │
    │                                                              │
    │  VS1053  →  [3.5mm headphone jack]                          │
    └────────────────────────────────────┬─────────────────────────┘
                                         │  3.5mm TRS cable or short wire
                                         ▼
    ┌──────────────────────────────────────────────────────────────┐
    │  Panel-mount 3.5mm TRS socket                               │
    │  Tip = Left  ·  Ring = Right  ·  Sleeve = GND              │
    └──────────────────────────────────────────────────────────────┘
    Plug in stereo headphones or run a cable to a powered speaker or line input.
    Standard TRS wiring is correct here — VS1053 output is single-ended, not BTL.
```

### Connection Summary — Variant A

| From | Signal | To |
|---|---|---|
| Music Maker 3.5mm jack | Stereo audio out | Panel-mount TRS socket or headphone plug |
| Socket Tip | Left channel | Headphone / line L |
| Socket Ring | Right channel | Headphone / line R |
| Socket Sleeve | Ground | Headphone / line GND |

---

## Adafruit ESP32-S3 Reverse TFT Feather (#5691)

**Form factor:** Standard Feather (12-pin side + 16-pin side). TFT display faces the back/bottom of the board.

> **L/R orientation note:** This diagram labels the VBAT/D-pins/SCL/SDA row as **L** (12 pins) and the RST/3V/GND/A-pins row as **R** (16 pins). Adafruit's official SVG uses the opposite convention (their "Right" = the VBAT/12-pin side). GPIO numbers are identical regardless of label convention.

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
        ┌──────────────[USB passthrough]────────────┐  ← RST/USB end
        │                                           │
 L1  RST│  ○                               ○  │BAT    R1
 L2   3V│  ○                               ○  │EN     R2
 L3 AREF│  ○                               ○  │USB    R3
 L4  GND│  ○                               ○  │D13    R4
 L5   A0│  ○                               ○  │D12    R5
 L6   A1│  ○    [VS1053B]  [microSD]       ○  │D11    R6
 L7   A2│  ○                     DCS →     ○  │D10    R7
 L8   A3│  ○                    DREQ →     ○  │D9     R8
 L9   A4│  ○              VS1053 CS →      ○  │D6     R9
L10   A5│  ○                  SD_CS →      ○  │D5     R10
L11  SCK│  ○                               ○  │RX     R11
L12 MOSI│  ○                               ○  │TX     R12
        │                   [3.5mm jack]   ○  │SDA    R13
        │                                  ○  │SCL    R14
        │                                  ○  │SCK    R15
        │                                  ○  │MOSI   R16
        │                                  ○  │MISO   (inner row)
        └───────────────────────────────────────┘
```

The 4 control signals connect through the 16-pin (right/D-pin) side of the header at D5, D6, D9, D10. The GPIO numbers at those positions differ by Feather board — see the tables below.

### Control pin connections by board

The Music Maker's 4 control pins land on different GPIOs depending on which Feather it stacks on. The physical header positions are identical — the GPIO numbers differ because the two MCUs number their pins differently.

**Radius V1 — HUZZAH32 (#3405)**

| Signal      | Feather Label | GPIO | Header Position |
|-------------|---------------|------|-----------------|
| VS1053 CS   | A7            | 32   | L10             |
| VS1053 DCS  | A9            | 33   | L12             |
| VS1053 DREQ | A8            | 15   | L11             |
| SD CS       | A6            | 14   | L9              |
| MOSI        | MOSI          | 18   | L12 inner row   |
| MISO        | MISO          | 19   | inner row       |
| SCK         | SCK           | 5    | L11 inner row   |

**Radius V2 — ESP32-S3 Reverse TFT Feather (#5691)**

| Signal      | Feather Label | GPIO | Header Position |
|-------------|---------------|------|-----------------|
| VS1053 CS   | D6            | 6    | L9              |
| VS1053 DCS  | D10           | 10   | L7              |
| VS1053 DREQ | D9            | 9    | L8              |
| SD CS       | D5            | 5    | L10             |
| MOSI        | MOSI          | 35   | R12             |
| MISO        | MISO          | 37   | R13             |
| SCK         | SCK           | 36   | R11             |

Source: `Adafruit_VS1053_Library/examples/feather_player/feather_player.ino` (installed library).

### Pin definitions in `config.h`

Board-conditional — selected automatically at compile time based on `TARGET_BOARD`:

```cpp
#if TARGET_BOARD == BOARD_FEATHER_ESP32
  // HUZZAH32 — control pins land on A6/A7/A8/A9
  #define MM_CS_PIN    32  // GPIO32 (A7) — VS1053 chip select
  #define MM_DCS_PIN   33  // GPIO33 (A9) — VS1053 data chip select
  #define MM_DREQ_PIN  15  // GPIO15 (A8) — VS1053 data request
  #define MM_SDCS_PIN  14  // GPIO14 (A6) — SD card chip select
#else
  // ESP32-S3 Reverse TFT Feather — control pins land on D5/D6/D9/D10
  #define MM_CS_PIN     6  // GPIO6  (D6)  — VS1053 chip select
  #define MM_DCS_PIN   10  // GPIO10 (D10) — VS1053 data chip select
  #define MM_DREQ_PIN   9  // GPIO9  (D9)  — VS1053 data request
  #define MM_SDCS_PIN   5  // GPIO5  (D5)  — SD card chip select
#endif
```

### Volume

The VS1053 has a hardware volume register: 0 = max, 254 = silent. The firmware maps the 0–100 UI range to this scale:

```cpp
uint8_t vs1053vol = (uint8_t)((100 - volume) * 254 / 100);
_musicMaker.setVolume(vs1053vol, vs1053vol);  // left, right
```

`setVolume()` can be called at any time without interrupting playback — used for the live volume slider in the sender UI.

---

---

## Adafruit 20W Stereo Amplifier — MAX9744 (#1752)

The MAX9744 is a Class D stereo amplifier that takes the line-level stereo output from the Music Maker FeatherWing headphone jack and drives 4–8Ω speakers at up to 20W per channel (with 12V supply). Volume is controlled digitally over I2C from the ESP32-S3.

**Signal chain:** Music Maker FeatherWing 3.5mm out → MAX9744 3.5mm in → BTL speaker terminals → speakers (4–8Ω)

---

### Board Jumper Configuration (I2C / digital mode)

The MAX9744 ships in I2C (digital) mode by default. Keep it in this mode for firmware volume control:

- **Analog, AD1, AD2 jumpers: leave OPEN** — closing any of these switches to analog potentiometer mode and disables I2C
- **Do not install the potentiometer** — the Pot Vol pads are only used in analog mode

To change the I2C address from the default 0x4B, close **one** of the address jumpers:

| AD1 | AD2 | I2C Address |
|-----|-----|-------------|
| Open | Open | 0x4B (default) |
| Closed | Open | 0x4A |
| Open | Closed | 0x49 |

---

### Audio Input

Two options — use whichever is easier to wire:

**Option A — 3.5mm cable (simplest)**

Connect a 3.5mm stereo male-to-male cable from the Music Maker FeatherWing headphone jack to the MAX9744 input jack.

**Option B — Terminal block wiring**

Solder in the 3-pin audio input terminal block on the MAX9744 and wire from the Music Maker line-level breakout pads:

| Music Maker Pad | MAX9744 Terminal | Signal |
|-----------------|------------------|--------|
| Left            | LIN              | Left channel |
| Right           | RIN              | Right channel |
| Ground          | AGND             | Analog ground |

The Music Maker Left/Right/Ground pads are on the headphone-out version (#3357), located next to the 3.5mm headphone jack. These are AC-coupled line-level outputs.

---

### I2C Wiring — MAX9744 → ESP32-S3 Feather

Solder or wire to the MAX9744 breakout header row (bottom edge of the board). The Music Maker uses SPI only, so I2C pins SDA/SCL are free.

| MAX9744 Pin | ESP32-S3 Feather Label | GPIO | Notes |
|-------------|------------------------|------|-------|
| SDA         | SDA                    | 3    | I2C data |
| SCL         | SCL                    | 4    | I2C clock |
| Vi2c        | 3V                     | —    | I2C logic reference — **required**, connect to 3.3V |
| GND         | GND                    | —    | Common ground |

The SDA/SCL pins are also available on the STEMMA QT connector on the ESP32-S3 Feather.

---

### Speaker Outputs

Solder in the two 2-pin blue speaker terminal blocks on the MAX9744. Connect 4–8Ω speakers to the Left and Right BTL output pairs, either directly or via panel-mount TS sockets.

The outputs are Bridge-Tied-Load (BTL): **do not connect the outputs to another amplifier** and do not bridge the two channels together.

**Using TS sockets (detachable speakers):** Wire each BTL channel to its own panel-mount 3.5mm mono TS socket — Tip to channel+, Sleeve to channel−. The sleeve carries the driven BTL negative output; it must not be connected to chassis or audio ground anywhere on the cable. Use one TS socket per channel. Do not use a stereo TRS socket to carry both channels — the shared TRS sleeve would short Left− to Right−.

---

### Power

The MAX9744 is powered separately from the Feather stack — the Feather 3V/5V rails cannot supply amplifier current. Connect a supply to the MAX9744 DC barrel jack (2.1mm, center-positive) or the power terminal block.

| Supply Voltage | Power per channel (4Ω) | Power per channel (8Ω) |
|----------------|------------------------|------------------------|
| 5V             | 3.6W                   | 1.8W                   |
| 8V             | ~8W                    | ~5W                    |
| 12V            | 17W                    | 10W                    |
| 14V            | 22W                    | 13W                    |

For full 20W output, use a 12–14V supply rated for at least 2A per channel. The Feather VBUS (5V USB) is only suitable for low-volume use with small speakers.

---

### Pin Definitions in `config.h`

```cpp
// MAX9744 I2C volume control — ESP32-S3 Reverse TFT Feather
#define MAX9744_I2C_ADDR  0x4B  // Default (AD1 and AD2 open)
// SDA = GPIO3 (Feather SDA), SCL = GPIO4 (Feather SCL) — Wire library defaults
```

### Volume Control

The MAX9744 accepts a single I2C byte (0–63) for 64-step volume control. 0 = minimum, 63 = maximum (29.5 dB gain). Wire the call after `Wire.begin()`:

```cpp
bool setAmplifierVolume(uint8_t v) {
    if (v > 63) v = 63;
    Wire.beginTransmission(MAX9744_I2C_ADDR);
    Wire.write(v);
    return Wire.endTransmission() == 0;
}
```

To map the firmware 0–100 UI range to the MAX9744 0–63 scale:

```cpp
uint8_t ampVol = (uint8_t)(volume * 63 / 100);
setAmplifierVolume(ampVol);
```

This can be called at any time without interrupting playback. The VS1053 and MAX9744 volume controls are independent — use either or both.

---

### Doubler Build — Connecting MAX9744 Volume Control

The FeatherWing Doubler (#2890) places the ESP32-S3 Feather and Music Maker FeatherWing side-by-side. All pins are cross-connected between the two Feather slots. Every header pin also has a duplicate through-hole next to it — solder the 4 short wires to those holes rather than to the header pins themselves, so the boards seat cleanly.

The MAX9744 is not a FeatherWing and does not plug into the doubler. It lives off-board, connected by 4 short hookup wires (~10–15 cm) running from the doubler's breakout holes to the MAX9744 I2C breakout header on the bottom edge of that board.

#### MAX9744 board layout

```
     Adafruit MAX9744 20W Stereo Amplifier (#1752) — top view
     ┌──────────────────[2.1mm DC Barrel  5–14V]──────────────────┐
     │                                              ○  cap pad    │
     │  Pot.Vol ○ ○ ○   [Analog]○  [AD1]○  [AD2]○               │
     │            solder jumpers — leave ALL open for I2C mode    │
     │                                             Left+  ──○    │
 ════╪═[3.5mm audio in]════════[MAX9744]═══════════Left-  ──○    │
     │                                             Right+ ──○    │
     │                                             Right- ──○    │
     ├────────────────────────────────────────────────────────────┤
     │   1    2    3    4    5    6    7    8  ···  13   14       │
     │   ○    ○    ○    ○    ○    ○    ○    ○       ○    ○       │
     │  RIN  LIN  AGND  SDA  SCL Vi2c SHDN MUTE … GND  VDD      │
     │                  ↑    ↑    ↑              ↑               │
     │                  └────┴────┴── I2C ───────┘               │
     └────────────────────────────────────────────────────────────┘
     Speaker terminals are BTL — 4–8 Ω speakers only, never another amplifier.
     AD1, AD2, and Analog jumpers must remain OPEN (factory default = I2C mode).
```

Pin 4 (SDA), pin 5 (SCL), pin 6 (Vi2c), and pin 13 (GND) are the four connections needed for I2C volume control. The remaining breakout pins (SHDN, MUTE, SYNC, AD1, AD2, VDD) are not connected for this build.

#### FeatherWing Doubler — tap points

The doubler places both Feather slots with their USB/RST ends at the same edge (top). The 12-pin rows (VBAT → SDA) run along the outer long edges; the 16-pin rows (RST → TXD0) face inward toward the proto area.

```
     Adafruit FeatherWing Doubler (#2890) — tap points for MAX9744

     ← USB / RST end (top of both slots) ──────────────────────────
     
     Outer left edge — 12-pin    Inner left edge — 16-pin
     (Slot A: ESP32-S3 Feather)  (Slot A: ESP32-S3 Feather)
     ─────────────────────────   ──────────────────────────────────
     VBAT   L1  ○                RST   R1  ○
       EN   L2  ○                 3V   R2  ○ ◄── tap here → MAX9744 Vi2c
     VBUS   L3  ○                 3V   R3  ○
      D13   L4  ○                GND   R4  ○ ◄── tap here → MAX9744 GND
      D12   L5  ○                 A0   R5  ○
      D11   L6  ○                 A1   R6  ○
      D10   L7  ○                 A2   R7  ○  ┐
       D9   L8  ○                 A3   R8  ○  │  [proto holes area]
       D6   L9  ○                 A4   R9  ○  │
       D5   L10 ○                 A5   R10 ○  ┘
      SCL   L11 ○ ◄── tap here → MAX9744 SCL
      SDA   L12 ○ ◄── tap here → MAX9744 SDA
```

The duplicate through-holes for each pin are in the rows alongside the headers. R2 (3V) and R4 (GND) sit near the USB end of the inner row; L11 (SCL) and L12 (SDA) sit at the far end of the outer row. All four are on the same side (Slot A / left half of the doubler).

#### 4-wire connection table

| Doubler position | Signal | MAX9744 pin |
|-----------------|--------|-------------|
| L12 outer (SDA) | I2C data | 4 — SDA |
| L11 outer (SCL) | I2C clock | 5 — SCL |
| R2 inner (3V) | Logic reference | 6 — Vi2c |
| R4 inner (GND) | Ground | 13 — GND |

Solder to the duplicate through-holes beside the header on the doubler — not to the header pins themselves.

---

## References

| Source | URL / Path |
|--------|------------|
| Music Maker FeatherWing overview | https://learn.adafruit.com/adafruit-music-maker-featherwing |
| Music Maker FeatherWing pinouts | https://learn.adafruit.com/adafruit-music-maker-featherwing/pinouts |
| VS1053B datasheet | https://www.vlsi.fi/fileadmin/datasheets/vs1053.pdf |
| MAX9744 20W amplifier guide | https://learn.adafruit.com/adafruit-20w-stereo-audio-amplifier-class-d-max9744 |
| ESP32-S3 Reverse TFT Feather pinout | https://learn.adafruit.com/esp32-s3-reverse-tft-feather/pinouts |
| ESP32-S3 Reverse TFT Feather Fritzing part (physical layout) | https://github.com/adafruit/Fritzing-Library/blob/master/parts/Adafruit%20ESP32-S3%20Reverse%20TFT%20Feather.fzpz |
| ESP32-S3 Reverse TFT Feather official pinout SVG | https://github.com/adafruit/Adafruit-ESP32-S3-Reverse-TFT-Feather-PCB/blob/main/Adafruit_ESP32-S3_Reverse_TFT_Feather_Pinout.svg |
| GPIO numbers (`pins_arduino.h`) | `~/Library/Arduino15/packages/esp32/hardware/esp32/3.3.5/variants/adafruit_feather_esp32s3_reversetft/pins_arduino.h` |
| PrimusV3 firmware config | `V3_2/Arduino/radiusV2/config.h` |

---

---

## Troubleshooting

### SD Card Not Found at Boot

**Symptom:** Serial output shows `[Audio] WARNING: SD card not found — file playback unavailable`. FTP server never starts. Radius Central shows no files for the device.

**Cause:** The Music Maker FeatherWing's microSD slot is not occupied or the card is not seated properly.

**Procedure:**

1. Open serial monitor at 115200 baud:
   ```bash
   # arduino-cli (specify board to avoid 9600 default):
   arduino-cli monitor -p /dev/cu.usbserial-XXXX -b esp32:esp32:featheresp32
   # Or with screen:
   screen /dev/cu.usbserial-XXXX 115200
   ```

2. Observe boot output. Healthy SD output:
   ```
   [Audio] VS1053 OK
   [Audio] SD OK
   [Boot] Sine test (1kHz, 500ms)...
   ```
   SD failure output:
   ```
   [Audio] VS1053 OK
   [Audio] WARNING: SD card not found — file playback unavailable
   [Boot] Sine test (1kHz, 500ms)...
   [Boot] SD not ready — skipping file playback
   ```

3. If SD failure: power off, physically insert or reseat the microSD card in the Music Maker FeatherWing slot, power on and confirm `[Audio] SD OK` in serial output.

4. If SD card is inserted and the error persists, try a different card formatted as FAT32. The VS1053 library requires FAT32.

5. FTP requires SD — if SD is unavailable, FTP will not start and status lines will show `FTP: off`.

**Known affected device:** Radius-E5 (192.168.8.154, HUZZAH32 V1) — SD card not inserted as of 2026-06-22. WiFi confirmed working (RSSI −22 dBm). Insert SD card to restore file playback and FTP.

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

**Status:** Researched but not tested in firmware. Line-level output — requires powered speakers or amplifier. The active amplifier path for this project uses the Music Maker + MAX9744; the PCM5102 is kept here as an alternative I2S DAC option if the VS1053 path is ever replaced.

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
