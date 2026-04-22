/*
 * config.h — PrimusV3 Audio Receiver Configuration
 * ==================================================
 * Centralized output type definitions, network defaults, hardware
 * pin mapping, audio board selection, and FTP credentials.
 *
 * Select audio hardware by changing AUDIO_BOARD below.
 */

#ifndef CONFIG_H
#define CONFIG_H

#include <Arduino.h>

// =====================================================================
//  Firmware Info
// =====================================================================
#define FIRMWARE_NAME    "PrimusV3-Audio"
#define FIRMWARE_VERSION "3.2.0"

// =====================================================================
//  Audio Board Selection  (compile-time switch)
// =====================================================================
#define AUDIO_BOARD_MUSIC_MAKER 1   // Adafruit Music Maker FeatherWing (VS1053, Adafruit 3357)
#define AUDIO_BOARD_BFF         2   // Adafruit Audio BFF (MAX98357 I2S, Adafruit 5769)

#define AUDIO_BOARD AUDIO_BOARD_MUSIC_MAKER  // ← change to switch hardware

// ── Music Maker FeatherWing pins (SPI-based, stacks on Feather header) ──
#define MM_CS_PIN    6   // VS1053 chip select
#define MM_DCS_PIN  10   // VS1053 data chip select
#define MM_DREQ_PIN  9   // VS1053 data request
#define MM_SDCS_PIN  5   // SD card chip select

// ── Audio BFF pins (I2S, manual wiring to Feather) ───────────────────
#define BFF_BCK_PIN   5  // I2S bit clock
#define BFF_WS_PIN    6  // I2S word select (LRC)
#define BFF_DATA_PIN  9  // I2S data
#define BFF_SDCS_PIN 10  // SD card chip select (SPI shared)

// =====================================================================
//  Output Type Definitions
// =====================================================================
enum OutputType {
  OUTPUT_OFF         = 0,
  OUTPUT_SHORT_STRIP = 1,
  OUTPUT_LONG_STRIP  = 2,
  OUTPUT_GRID        = 3
};

// Layout hint — used by display and sender for rendering
enum LayoutType {
  LAYOUT_NONE   = 0,
  LAYOUT_LINEAR = 1,
  LAYOUT_GRID   = 2
};

// ── Type lookup table ────────────────────────────────────────────────
struct OutputTypeDef {
  const char* name;
  uint16_t    pixels;
  uint8_t     bytesPerPixel;  // 3 = RGB, 4 = RGBW
  LayoutType  layout;
  uint8_t     gridCols;
  uint8_t     gridRows;
};

const OutputTypeDef OUTPUT_TYPE_TABLE[] = {
  /* OUTPUT_OFF         */ { "Off",          0, 0, LAYOUT_NONE,   0, 0 },
  /* OUTPUT_SHORT_STRIP */ { "Short Strip", 30, 3, LAYOUT_LINEAR, 0, 0 },
  /* OUTPUT_LONG_STRIP  */ { "Long Strip",  72, 3, LAYOUT_LINEAR, 0, 0 },
  /* OUTPUT_GRID        */ { "Grid 8x8",    64, 3, LAYOUT_GRID,   8, 8 },
};

#define NUM_OUTPUT_TYPES (sizeof(OUTPUT_TYPE_TABLE) / sizeof(OUTPUT_TYPE_TABLE[0]))

inline const char*  typeName(OutputType t)   { return OUTPUT_TYPE_TABLE[t].name; }
inline uint16_t     typePixels(OutputType t)  { return OUTPUT_TYPE_TABLE[t].pixels; }
inline uint8_t      typeBpp(OutputType t)     { return OUTPUT_TYPE_TABLE[t].bytesPerPixel; }
inline LayoutType   typeLayout(OutputType t)  { return OUTPUT_TYPE_TABLE[t].layout; }

// =====================================================================
//  Per-Output Configuration
// =====================================================================
#define NUM_OUTPUTS 3
#define MAX_OUTPUTS 3

struct OutputConfig {
  OutputType  type;
  uint8_t     pxl8Port;
  uint8_t     universe;
  uint16_t    pixelCount;
  uint8_t     bytesPerPixel;
};

inline void deriveFromType(OutputConfig& cfg) {
  cfg.pixelCount    = typePixels(cfg.type);
  cfg.bytesPerPixel = typeBpp(cfg.type);
}

inline void loadDefaultConfig(OutputConfig outputs[NUM_OUTPUTS]) {
  outputs[0].type     = OUTPUT_SHORT_STRIP;
  outputs[0].pxl8Port = 0;
  outputs[0].universe = 0;
  deriveFromType(outputs[0]);

  outputs[1].type     = OUTPUT_LONG_STRIP;
  outputs[1].pxl8Port = 1;
  outputs[1].universe = 1;
  deriveFromType(outputs[1]);

  outputs[2].type     = OUTPUT_GRID;
  outputs[2].pxl8Port = 2;
  outputs[2].universe = 2;
  deriveFromType(outputs[2]);
}

inline uint8_t countActiveOutputs(const OutputConfig outputs[NUM_OUTPUTS]) {
  uint8_t n = 0;
  for (uint8_t i = 0; i < NUM_OUTPUTS; i++) {
    if (outputs[i].type != OUTPUT_OFF) n++;
  }
  return n;
}

// =====================================================================
//  NeoPXL8 Hardware
// =====================================================================
#define MAX_LEDS_PER_PORT 72

#define PIN_PORT_0  18   // A0 / GPIO18
#define PIN_PORT_1  17   // A1 / GPIO17
#define PIN_PORT_2  16   // A2 / GPIO16

// =====================================================================
//  Buttons — ESP32-S3 Reverse TFT Feather
// =====================================================================
#define BTN_D0  0   // Active-LOW (INPUT_PULLUP)  — cycle screens
#define BTN_D1  1   // Active-HIGH (INPUT_PULLDOWN) — toggle test / FTP

// =====================================================================
//  Network Defaults
// =====================================================================
#define DEFAULT_WIFI_SSID      "NETGEAR44"
#define DEFAULT_WIFI_PASSWORD  "sweetgadfly251"

#define DEFAULT_STATIC_IP      192, 168, 1, 100
#define DEFAULT_GATEWAY        192, 168, 1, 1
#define DEFAULT_SUBNET         255, 255, 255, 0

// =====================================================================
//  Art-Net
// =====================================================================
#define ARTNET_PORT                  6454
#define ARTNET_OPCODE_DMX            0x5000
#define ARTNET_OPCODE_POLL           0x2000
#define ARTNET_OPCODE_POLLREPLY      0x2100
#define ARTNET_OPCODE_ADDRESS        0x6000
#define ARTNET_OPCODE_OUTPUT_CONFIG  0x8100  // Vendor: set output types
#define ARTNET_OPCODE_AUDIO_CMD      0x8200  // Vendor: audio play/stop/loop/pause
#define ARTNET_OPCODE_FTP_CMD        0x8201  // Vendor: FTP server control (0=stop, 1=start)
#define ARTNET_PROTOCOL_VER          14

#define DEVICE_SHORT_NAME  "PrimusV3-Audio"
#define DEVICE_LONG_NAME   "PrimusV3 Audio LED Node"
#define FIRMWARE_VERSION_H 3
#define FIRMWARE_VERSION_L 2
#define OEM_CODE           0xFFFF
#define ESTA_CODE          0x0000

// FPS back-channel
#define FPS_REPORT_PORT          6455
#define FPS_BACKCHANNEL_ENABLED  true

// =====================================================================
//  FTP Server
// =====================================================================
#define FTP_USER     "primus"
#define FTP_PASSWORD "primus"
#define FTP_PORT     21

// =====================================================================
//  Timing Constants (ms)
// =====================================================================
#define FPS_INTERVAL           1000
#define CONNECTION_TIMEOUT     10000
#define RECONNECT_INTERVAL     5000
#define FRAME_ASSEMBLY_TIMEOUT 5

#endif // CONFIG_H
