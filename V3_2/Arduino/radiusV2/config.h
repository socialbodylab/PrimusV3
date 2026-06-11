/*
 * config.h — PrimusV3 Audio Receiver Configuration
 * ==================================================
 * Hardware: Adafruit ESP32-S3 Reverse TFT Feather (#5691)
 *           or Adafruit Feather HUZZAH32 (#3405)
 *           + Adafruit Music Maker FeatherWing (#3357)
 *
 * Audio nodes never carry NeoPXL8 / LED outputs — LED output is handled
 * by separate V3.1 receiver nodes.
 */

#ifndef CONFIG_H
#define CONFIG_H

#include <Arduino.h>

// =====================================================================
//  Firmware Info
// =====================================================================
#define FIRMWARE_VERSION "3.2.0"

// =====================================================================
//  Target Board Selection  (compile-time switch)
// =====================================================================
#define BOARD_FEATHER_ESP32S3_REVERSETFT  1   // Adafruit ESP32-S3 Reverse TFT Feather (5691) — Radius V2
#define BOARD_FEATHER_ESP32               2   // Adafruit Feather HUZZAH32 (3405) — Radius V1 (headless)

#ifndef TARGET_BOARD
  #define TARGET_BOARD  BOARD_FEATHER_ESP32S3_REVERSETFT
#endif

#if TARGET_BOARD == BOARD_FEATHER_ESP32
  #define NO_DISPLAY
  #define FIRMWARE_NAME "Radius V1"
#else
  #define FIRMWARE_NAME "Radius V2"
#endif

// =====================================================================
//  Audio Board — Music Maker FeatherWing (VS1053, Adafruit 3357)
// =====================================================================
// The FeatherWing stacks directly on the Feather headers. The control
// pins land on different GPIOs depending on the target board.
// Reference: Adafruit VS1053 library examples/feather_player/feather_player.ino

#if TARGET_BOARD == BOARD_FEATHER_ESP32
  // HUZZAH32 — Music Maker control pins land on A6/A7/A8/A9
  // GPIO6–11 on this chip are internal flash SPI and must NOT be used as GPIO
  #define MM_CS_PIN    32  // GPIO32 (A7) — VS1053 chip select
  #define MM_DCS_PIN   33  // GPIO33 (A9) — VS1053 data chip select
  #define MM_DREQ_PIN  15  // GPIO15 (A8) — VS1053 data request
  #define MM_SDCS_PIN  14  // GPIO14 (A6) — SD card chip select
#else
  // ESP32-S3 Reverse TFT Feather — Music Maker control pins land on D5/D6/D9/D10
  #define MM_CS_PIN     6  // GPIO6  (D6)  — VS1053 chip select
  #define MM_DCS_PIN   10  // GPIO10 (D10) — VS1053 data chip select
  #define MM_DREQ_PIN   9  // GPIO9  (D9)  — VS1053 data request
  #define MM_SDCS_PIN   5  // GPIO5  (D5)  — SD card chip select
#endif

// =====================================================================
//  Buttons
// =====================================================================
#define BTN_D0  0   // Active-LOW  (INPUT_PULLUP)   — D0 boot btn: cycle screens

#if TARGET_BOARD == BOARD_FEATHER_ESP32
  #define BTN_D1  14  // GPIO14 on HUZZAH32 (GPIO1 is TX — not usable)
#else
  #define BTN_D1   1  // Active-HIGH (INPUT_PULLDOWN) — D1 btn: toggle FTP
#endif

// =====================================================================
//  Network Defaults
// =====================================================================
#define DEFAULT_WIFI_SSID      "RUR"
#define DEFAULT_WIFI_PASSWORD  "rurrurrur"

#define DEFAULT_STATIC_IP      192, 168, 8, 150
#define DEFAULT_GATEWAY        192, 168, 8, 1
#define DEFAULT_SUBNET         255, 255, 255, 0

// =====================================================================
//  Art-Net
// =====================================================================
#define ARTNET_PORT              6454
#define ARTNET_OPCODE_POLL       0x2000
#define ARTNET_OPCODE_POLLREPLY  0x2100
#define ARTNET_OPCODE_ADDRESS    0x6000
#define ARTNET_OPCODE_AUDIO_CMD  0x8200  // Vendor: audio play/stop/loop/pause
#define ARTNET_OPCODE_FTP_CMD    0x8201  // Vendor: FTP server control (0=stop, 1=start)
#define ARTNET_PROTOCOL_VER      14

#define DEVICE_SHORT_NAME  "Radius"
#if TARGET_BOARD == BOARD_FEATHER_ESP32
  #define DEVICE_LONG_NAME "Radius V1"
#else
  #define DEVICE_LONG_NAME "Radius V2"
#endif
#define FIRMWARE_VERSION_H 3
#define FIRMWARE_VERSION_L 2
#define OEM_CODE           0xFFFF
#define ESTA_CODE          0x0000

// FPS back-channel
#define FPS_REPORT_PORT         6455
#define FPS_BACKCHANNEL_ENABLED true

// =====================================================================
//  FTP Server
// =====================================================================
#define FTP_USER     "primus"
#define FTP_PASSWORD "primus"
#define FTP_PORT     21

// =====================================================================
//  Timing Constants (ms)
// =====================================================================
#define FPS_INTERVAL        1000
#define CONNECTION_TIMEOUT  10000
#define RECONNECT_INTERVAL  5000

#endif // CONFIG_H
