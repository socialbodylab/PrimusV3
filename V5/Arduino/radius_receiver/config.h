/*
 * config.h — Radius Central V4 receiver (V1 HUZZAH32 or V2 S3 Reverse TFT + Music Maker)
 */

#ifndef CONFIG_H
#define CONFIG_H

#include <Arduino.h>

#define FIRMWARE_VERSION_H     4
#define FIRMWARE_VERSION_L     19
#define FIRMWARE_VERSION_PATCH 0

#define _FW_STR_HELPER(x) #x
#define _FW_STR(x)        _FW_STR_HELPER(x)
#define FIRMWARE_VERSION  "4.19"
#define FIRMWARE_VERSION_FULL _FW_STR(FIRMWARE_VERSION_H) "." _FW_STR(FIRMWARE_VERSION_L) "." _FW_STR(FIRMWARE_VERSION_PATCH)

#define BOARD_FEATHER_ESP32S3_REVERSETFT  1
#define BOARD_FEATHER_ESP32               2

#ifndef TARGET_BOARD
#define TARGET_BOARD BOARD_FEATHER_ESP32
#endif

#if TARGET_BOARD == BOARD_FEATHER_ESP32
#define NO_DISPLAY
#define FIRMWARE_NAME "Radius V1"
#define NODE_CAPS_BOARD "v1"
#ifndef LED_BUILTIN
#define LED_BUILTIN 13
#endif
#define BOARD_HAS_STATUS_LED    1
#define BOARD_STATUS_LED_PIN    LED_BUILTIN
#define BOARD_STATUS_LED_ACTIVE_HIGH 1
#else
#define FIRMWARE_NAME "Radius V2"
#define NODE_CAPS_BOARD "v2"
#define BOARD_HAS_STATUS_NEOPIXEL 1
#define BOARD_STATUS_NEOPIXEL_PIN 45
#define BOARD_STATUS_NEOPIXEL_POWER_PIN -1
#define BOARD_STATUS_NEOPIXEL_BRIGHTNESS 40
#endif

#if TARGET_BOARD == BOARD_FEATHER_ESP32
#define MM_CS_PIN    32
#define MM_DCS_PIN   33
#define MM_DREQ_PIN  15
#define MM_SDCS_PIN  14
#define BTN_D1  14
#define BTN_D2  32
#else
#define MM_CS_PIN     6
#define MM_DCS_PIN   10
#define MM_DREQ_PIN   9
#define MM_SDCS_PIN   5
#define BTN_D1   1
#define BTN_D2   2
#endif

#define BTN_D0  0

// Buttons are compiled out entirely on the HUZZAH32 (V1) build: BTN_D1 (GPIO14)
// is the SD chip-select and BTN_D2 (GPIO32) is the VS1053 chip-select, so
// buttonsInit()'s INPUT_PULLDOWN on those pins fights the Music Maker SPI bus.
// The V1 board is headless (NO_DISPLAY) so buttons have no function there anyway.
#if TARGET_BOARD == BOARD_FEATHER_ESP32
#define RADIUS_HAS_BUTTONS 0
#else
#define RADIUS_HAS_BUTTONS 1
#endif

// Battery telemetry (V1 HUZZAH32 only): stock VBAT/2 divider on A13 (GPIO35,
// ADC1 — safe alongside WiFi). Exactly one analogReadMilliVolts() per second;
// never multi-sample or delay() here — the VS1053 FIFO drains in ~11.6 ms.
#if TARGET_BOARD == BOARD_FEATHER_ESP32
#define RADIUS_BATTERY_MONITOR 1
#else
#define RADIUS_BATTERY_MONITOR 0
#endif

// NOTE: build_opt.h (sketch dir; consumed verbatim as compiler flags, so it
// cannot carry comments) disables NimBLE's peripheral/broadcaster roles —
// Marius is scanner + client only. Without this the merged firmware overflows
// the HUZZAH32's stock 1.25 MB app partition. Do not delete that file.

#define AUDIO_BOARD_MUSIC_MAKER 1
#define AUDIO_BOARD AUDIO_BOARD_MUSIC_MAKER

#ifndef DEFAULT_WIFI_SSID
#define DEFAULT_WIFI_SSID      "OPERADEV"
#endif
#ifndef DEFAULT_WIFI_PASSWORD
#define DEFAULT_WIFI_PASSWORD  "torrentoflight"
#endif

#define DEFAULT_STATIC_IP      192, 168, 1, 100
#define DEFAULT_GATEWAY        192, 168, 1, 1
#define DEFAULT_SUBNET         255, 255, 255, 0

// UDP lane ports (Show / Setup / Watch) — docs/systems/PORT_ORGANIZATION.md
#define PORT_DISCOVERY_DEFAULT   6454   // ArtPoll bootstrap (always)
#define PORT_SHOW_DEFAULT        6456   // ArtAudioCmd live show
#define PORT_SETUP_DEFAULT       6457   // FTP gate / identity / IP
#define PORT_WATCH_DEFAULT       6455   // PTR / PFP telemetry destination
#ifndef PORT_DUAL_LISTEN
#define PORT_DUAL_LISTEN         1      // accept Setup/audio on legacy ports during migrate
#endif
#define ARTNET_PORT              PORT_DISCOVERY_DEFAULT
#define ARTNET_OPCODE_POLL       0x2000
#define ARTNET_OPCODE_POLLREPLY  0x2100
#define ARTNET_OPCODE_ADDRESS    0x6000
#define ARTNET_OPCODE_IP_CONFIG  0x8200
#define ARTNET_OPCODE_SHOW_INFO  0x8210
#define ARTNET_OPCODE_LANE_PORTS 0x8220  // Vendor-defined: set Show/Setup/Watch ports
#define ARTNET_OPCODE_AUDIO_CMD  0x8300
#define ARTNET_OPCODE_FTP_CMD    0x8301
#define ARTNET_OPCODE_AUDIO_STATUS 0x8302
#define ARTNET_PROTOCOL_VER      14

#define SHOW_INFO_FIELD_LEN        64
#define SHOW_INFO_MODE_READ        0
#define SHOW_INFO_MODE_WRITE       1
#define SHOW_INFO_MODE_RESPONSE    2
#define SHOW_INFO_PACKET_LEN       143

#ifndef DEVICE_SHORT_NAME
#define DEVICE_SHORT_NAME  "Radius"
#endif
#if TARGET_BOARD == BOARD_FEATHER_ESP32
#define DEVICE_LONG_NAME   "Radius Central V1"
#else
#define DEVICE_LONG_NAME   "Radius Central V2"
#endif

#ifndef DEFAULT_SHOW_CHARACTER_NAME
#define DEFAULT_SHOW_CHARACTER_NAME ""
#endif
#ifndef DEFAULT_SHOW_PERFORMER_NAME
#define DEFAULT_SHOW_PERFORMER_NAME "Performer"
#endif

#define OEM_CODE           0xFFFF
#define ESTA_CODE          0x0000

#define NODE_CAPS_PREFIX   "PVRAD1"
#define NODE_CAPS_FEATURES "RIHASB"

#define FPS_REPORT_PORT         PORT_WATCH_DEFAULT
#define AUDIO_REPORT_PORT       PORT_WATCH_DEFAULT
#define OSC_PORT                53001
#define FPS_BACKCHANNEL_ENABLED true
#define TRACK_TELEMETRY_ENABLED true

#define TRACK_STATE_STOPPED 0
#define TRACK_STATE_PLAYING 1
#define TRACK_STATE_PAUSED  2

#define FTP_USER     "radius"
#define FTP_PASSWORD "radius"
#define FTP_PORT     21

#define FPS_INTERVAL           1000
#define TRACK_HEARTBEAT_MS     1000
#define WIFI_CHECK_INTERVAL_MS 200
#define CONNECTION_TIMEOUT     10000
#define RECONNECT_INTERVAL     5000

#ifndef RADIUS_DIAG
#define RADIUS_DIAG 0
#endif

#ifndef BOARD_HAS_STATUS_LED
#define BOARD_HAS_STATUS_LED 0
#endif
#ifndef BOARD_HAS_STATUS_NEOPIXEL
#define BOARD_HAS_STATUS_NEOPIXEL 0
#endif

#endif // CONFIG_H
