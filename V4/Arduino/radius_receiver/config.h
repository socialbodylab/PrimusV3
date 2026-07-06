/*
 * config.h — Radius Central V4 receiver
 * Hardware: Adafruit ESP32-S3 Reverse TFT Feather (#5691) [rv2]
 *           or Adafruit Feather HUZZAH32 (#3405) [rv1, headless]
 *           + Adafruit Music Maker FeatherWing (#3357)
 */

#ifndef CONFIG_H
#define CONFIG_H

#include <Arduino.h>

// =====================================================================
//  Firmware Version
// =====================================================================
#define FIRMWARE_VERSION_H 4
#define FIRMWARE_VERSION_L 0
#define FIRMWARE_VERSION "4.0.0"

// =====================================================================
//  Target Board Selection  (compile-time switch)
// =====================================================================
#define BOARD_FEATHER_ESP32S3_REVERSETFT  1   // rv2: ESP32-S3 Reverse TFT Feather (5691)
#define BOARD_FEATHER_ESP32               2   // rv1: Feather HUZZAH32 (3405) — headless

#ifndef TARGET_BOARD
  #define TARGET_BOARD BOARD_FEATHER_ESP32S3_REVERSETFT
#endif

#if TARGET_BOARD == BOARD_FEATHER_ESP32
  #define NO_DISPLAY
  #define FIRMWARE_NAME    "Radius V1"
  #define DEVICE_LONG_NAME "Radius Central V1"
  #define NODE_CAPS_BOARD  "v1"
#else
  #define FIRMWARE_NAME    "Radius V2"
  #define DEVICE_LONG_NAME "Radius Central V2"
  #define NODE_CAPS_BOARD  "v2"
#endif

// =====================================================================
//  Audio Board — Music Maker FeatherWing (VS1053, Adafruit 3357)
// =====================================================================
#define AUDIO_BOARD_MUSIC_MAKER 1
#define AUDIO_BOARD AUDIO_BOARD_MUSIC_MAKER

#if TARGET_BOARD == BOARD_FEATHER_ESP32
  // HUZZAH32 — Music Maker control pins land on A6/A7/A8/A9
  // GPIO6–11 are internal flash SPI and must NOT be used as GPIO
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
#define BTN_D0  0   // Active-LOW (INPUT_PULLUP) — D0 boot btn: cycle screens

#if TARGET_BOARD == BOARD_FEATHER_ESP32
  // HUZZAH32 has no safe user buttons — GPIO14 is MM_SDCS_PIN.
  // BTN_D1/D2 are defined but buttonsInit() skips init on this board.
  #define BTN_D1  14
  #define BTN_D2  32
#else
  #define BTN_D1   1  // Active-HIGH (INPUT_PULLDOWN) — D1: context action
  #define BTN_D2   2  // Active-HIGH (INPUT_PULLDOWN) — D2: context action
#endif

// =====================================================================
//  Network Defaults
// =====================================================================
#ifndef DEFAULT_WIFI_SSID
  #define DEFAULT_WIFI_SSID      "PrimusRouter"
#endif
#ifndef DEFAULT_WIFI_PASSWORD
  #define DEFAULT_WIFI_PASSWORD  "router-password"
#endif

#define DEFAULT_STATIC_IP      192, 168, 1, 100
#define DEFAULT_GATEWAY        192, 168, 1, 1
#define DEFAULT_SUBNET         255, 255, 255, 0

// =====================================================================
//  Art-Net
// =====================================================================
#define ARTNET_PORT              6454
#define ARTNET_OPCODE_POLL       0x2000
#define ARTNET_OPCODE_POLLREPLY  0x2100
#define ARTNET_OPCODE_ADDRESS    0x6000
#define ARTNET_OPCODE_IP_CONFIG  0x8200
#define ARTNET_OPCODE_AUDIO_CMD  0x8300
#define ARTNET_OPCODE_FTP_CMD    0x8301
#define ARTNET_PROTOCOL_VER      14

#define DEVICE_SHORT_NAME  "Radius"
#define OEM_CODE           0xFFFF
#define ESTA_CODE          0x0000

#define NODE_CAPS_PREFIX  "PVRAD1"
#define NODE_CAPS_FEATURES "RA"

// =====================================================================
//  Telemetry (UDP 6455 back-channel)
// =====================================================================
#define FPS_REPORT_PORT         6455
#define FPS_BACKCHANNEL_ENABLED true
#define TRACK_TELEMETRY_ENABLED true

#define TRACK_STATE_STOPPED 0
#define TRACK_STATE_PLAYING 1
#define TRACK_STATE_PAUSED  2

// =====================================================================
//  FTP Server
// =====================================================================
#define FTP_USER     "radius"
#define FTP_PASSWORD "radius"
#define FTP_PORT     21

// =====================================================================
//  Timing Constants (ms)
// =====================================================================
#define FPS_INTERVAL           1000
#define WIFI_CHECK_INTERVAL_MS 200
#define CONNECTION_TIMEOUT     10000
#define RECONNECT_INTERVAL     5000

// Set to 1 for loop timing CSV on Serial (development only).
#ifndef RADIUS_DIAG
#define RADIUS_DIAG 0
#endif

#endif // CONFIG_H
