/*
 * config.h — Radius Central V4 receiver (V1 HUZZAH32 + Music Maker)
 */

#ifndef CONFIG_H
#define CONFIG_H

#include <Arduino.h>

#define FIRMWARE_VERSION "4.0.0"
#ifndef TARGET_BOARD
#define TARGET_BOARD BOARD_FEATHER_ESP32
#endif

#define BOARD_FEATHER_ESP32               2

#define NO_DISPLAY
#define FIRMWARE_NAME "Radius V1"

#define AUDIO_BOARD_MUSIC_MAKER 1
#define AUDIO_BOARD AUDIO_BOARD_MUSIC_MAKER

#define MM_CS_PIN    6
#define MM_DCS_PIN  10
#define MM_DREQ_PIN  9
#define MM_SDCS_PIN  5

#define BTN_D0  0
#define BTN_D1  14

#define DEFAULT_WIFI_SSID      "PrimusRouter"
#define DEFAULT_WIFI_PASSWORD  "router-password"

#define DEFAULT_STATIC_IP      192, 168, 1, 100
#define DEFAULT_GATEWAY        192, 168, 1, 1
#define DEFAULT_SUBNET         255, 255, 255, 0

#define ARTNET_PORT              6454
#define ARTNET_OPCODE_POLL       0x2000
#define ARTNET_OPCODE_POLLREPLY  0x2100
#define ARTNET_OPCODE_ADDRESS    0x6000
#define ARTNET_OPCODE_IP_CONFIG  0x8200
#define ARTNET_OPCODE_AUDIO_CMD  0x8300
#define ARTNET_OPCODE_FTP_CMD    0x8301
#define ARTNET_PROTOCOL_VER      14

#define DEVICE_SHORT_NAME  "Radius"
#define DEVICE_LONG_NAME   "Radius Central V1"
#define FIRMWARE_VERSION_H 4
#define FIRMWARE_VERSION_L 0
#define OEM_CODE           0xFFFF
#define ESTA_CODE          0x0000

#define NODE_CAPS_PREFIX "PVRAD1"
#define NODE_CAPS_BOARD  "v1"
#define NODE_CAPS_FEATURES "RA"

#define FPS_REPORT_PORT         6455
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

// Set to 1 for loop timing CSV on Serial (development only).
#ifndef RADIUS_DIAG
#define RADIUS_DIAG 0
#endif

#endif // CONFIG_H
