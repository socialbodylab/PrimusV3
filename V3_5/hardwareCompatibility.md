# V3.5 Hardware Compatibility

V3.5 uses one shared firmware source tree with separate Arduino build profiles. V1 and V2 boards must be reflashed with V3.5 firmware; the V3.5 sender does not use the old V1 OSC protocol or the old V2 brightness-byte Art-Net payload.

## Build Profiles

| Profile | Hardware | LED driver | Display | Output 0 | Output 1 | Default output types |
| --- | --- | --- | --- | --- | --- | --- |
| `v1` | Adafruit Huzzah32 ESP32 Feather | Direct NeoPixel | None | GPIO32 | GPIO12 | `small_grid`, `long_strip` |
| `v2` | Adafruit ESP32 Feather V2 | Direct NeoPixel | None | GPIO32 | GPIO12 | `small_grid`, `short_strip` |
| `v3_1` | Adafruit ESP32-S3 Reverse TFT Feather + NeoPXL8 FeatherWing | NeoPXL8 | Built-in ST7789 TFT | FeatherWing output 6 / A4 / GPIO14 | FeatherWing output 7 / A3 / GPIO15 | `short_strip`, `long_strip` |

## Output Types

The firmware enum and sender `LOOK_OUTPUT_TYPES` list must stay in this exact order.

| Type ID | Sender key | Firmware enum | Pixels | Layout |
| --- | --- | --- | --- | --- |
| 0 | `none` | `OUTPUT_OFF` | 0 | None |
| 1 | `short_strip` | `OUTPUT_SHORT_STRIP` | 30 | Linear |
| 2 | `long_strip` | `OUTPUT_LONG_STRIP` | 72 | Linear |
| 3 | `grid` | `OUTPUT_GRID` | 64 | 8x8 grid |
| 4 | `small_grid` | `OUTPUT_SMALL_GRID` | 32 | 4x8 grid |
| 5 | `extra_long_strip` | `OUTPUT_EXTRA_LONG_STRIP` | 122 | Linear |

## Discovery

All V3.5 profiles advertise the existing `PV3CAP1` Node Report contract with one compatible extension:

`PV3CAP1|port:type_id:universe|B:profile|F:RIOH`

Profile codes:

| Code | Meaning |
| --- | --- |
| `v1` | V1 Huzzah32 profile |
| `v2` | V2 Feather profile |
| `v31` | V3.1 Reverse TFT profile |

The sender continues to accept V3.1-style tags that do not include `B:profile`; those default to the V3.1 profile when the node name identifies a PrimusV3 device.

## Compile Commands

```sh
./V3_5/Arduino/upload.sh --board v1 --compile
./V3_5/Arduino/upload.sh --board v2 --compile
./V3_5/Arduino/upload.sh --board v3_1 --compile
```

Use the same script without `--compile` to upload. Add a serial port path as the last argument when auto-detection is not enough.
