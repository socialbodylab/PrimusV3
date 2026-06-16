# V3.1 Hardware Pinout

## Boards Used

| Role | Exact board | Adafruit URL | Notes |
| --- | --- | --- | --- |
| Receiver microcontroller | Adafruit ESP32-S3 Reverse TFT Feather | https://www.adafruit.com/product/5691 | Main controller, WiFi, TFT display, D0/D1 buttons |
| LED output board | Adafruit NeoPXL8 M0 FeatherWing | https://www.adafruit.com/product/3249 | Used through the FeatherWing headers, no solder bridge changes for outputs 6 and 7 |
| Mechanical stack adapter | Adafruit FeatherWing Doubler | https://www.adafruit.com/product/2890 | Used so the Reverse TFT can face outward while the NeoPXL8 FeatherWing sits on the back side |

## LED Output Mapping

| Primus V3.1 output | Art-Net universe | NeoPXL8 strand index | Physical FeatherWing output | Feather pin | ESP32-S3 GPIO | Default output type |
| --- | ---: | ---: | ---: | --- | ---: | --- |
| Output 0 | 0 | 6 | Output 6 | A4 | GPIO14 | Short Strip, 30 px |
| Output 1 | 1 | 7 | Output 7 | A3 | GPIO15 | Long Strip, 72 px |

## Firmware Constants

| Setting | Value | File |
| --- | --- | --- |
| Active output count | `NUM_OUTPUTS = 2` | `V3_1/Arduino/primusV3_receiver/config.h` |
| Maximum output count | `MAX_OUTPUTS = 2` | `V3_1/Arduino/primusV3_receiver/config.h` |
| FeatherWing output 6 pin | `PIN_PORT_6 = 14` | `V3_1/Arduino/primusV3_receiver/config.h` |
| FeatherWing output 7 pin | `PIN_PORT_7 = 15` | `V3_1/Arduino/primusV3_receiver/config.h` |
| Enabled NeoPXL8 slots | `pxl8Pins[6] = PIN_PORT_6`, `pxl8Pins[7] = PIN_PORT_7` | `V3_1/Arduino/primusV3_receiver/primusV3_receiver.ino` |

## Connection Summary

Connect LED data lines to the physical **output 6** and **output 7** connectors on the NeoPXL8 M0 FeatherWing.

| LED connector | Signal path |
| --- | --- |
| NeoPXL8 output 6 | FeatherWing output 6 to Feather A4 to ESP32-S3 GPIO14 |
| NeoPXL8 output 7 | FeatherWing output 7 to Feather A3 to ESP32-S3 GPIO15 |

Outputs 6 and 7 on the NeoPXL8 M0 FeatherWing are fixed hardware outputs. They do not require cutting traces or changing solder jumpers.