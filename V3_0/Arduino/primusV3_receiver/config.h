/*
 * config.h — PrimusV3 Receiver Configuration
 * ==================================================
 * Centralized output type definitions, network defaults, and hardware
 * pin mapping.  Edit this file to match your physical setup.
 *
 * OUTPUT TYPE TABLE — single source of truth.  To change what a
 * "short strip" means (e.g. 50 pixels instead of 68), edit ONE row.
 * To add a new type (e.g. RING), add one row + enum value.
 *
 * DEVICE CONFIG — assigns type + NeoPXL8 port + Art-Net universe per
 * output.  pixelCount and bytesPerPixel are derived from the type
 * table automatically — no manual duplication.
 */

#ifndef CONFIG_H
#define CONFIG_H

#include <Arduino.h>

// =====================================================================
//  Firmware Info
// =====================================================================
#define FIRMWARE_NAME    "PrimusV3"
#define FIRMWARE_VERSION "3.0.0"

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
// Add / edit rows here to change what each type means globally.
struct OutputTypeDef {
  const char* name;
  uint16_t    pixels;
  uint8_t     bytesPerPixel;  // 3 = RGB, 4 = RGBW
  LayoutType  layout;
  uint8_t     gridCols;       // only used when layout == LAYOUT_GRID
  uint8_t     gridRows;
};

// Index by OutputType enum value.
const OutputTypeDef OUTPUT_TYPE_TABLE[] = {
  /* OUTPUT_OFF         */ { "Off",          0, 0, LAYOUT_NONE,   0, 0 },
  /* OUTPUT_SHORT_STRIP */ { "Short Strip", 30, 3, LAYOUT_LINEAR, 0, 0 },
  /* OUTPUT_LONG_STRIP  */ { "Long Strip",  72, 3, LAYOUT_LINEAR, 0, 0 },
  /* OUTPUT_GRID        */ { "Grid 8x8",    64, 3, LAYOUT_GRID,   8, 8 },
};

#define NUM_OUTPUT_TYPES (sizeof(OUTPUT_TYPE_TABLE) / sizeof(OUTPUT_TYPE_TABLE[0]))

// Convenience accessors
inline const char*  typeName(OutputType t)       { return OUTPUT_TYPE_TABLE[t].name; }
inline uint16_t     typePixels(OutputType t)      { return OUTPUT_TYPE_TABLE[t].pixels; }
inline uint8_t      typeBpp(OutputType t)         { return OUTPUT_TYPE_TABLE[t].bytesPerPixel; }
inline LayoutType   typeLayout(OutputType t)      { return OUTPUT_TYPE_TABLE[t].layout; }

// =====================================================================
//  Per-Output Configuration
// =====================================================================
#define NUM_OUTPUTS 3
#define MAX_OUTPUTS 3   // hardware max (NeoPXL8 ports 0-2)

struct OutputConfig {
  OutputType  type;
  uint8_t     pxl8Port;      // 0, 1, or 2
  uint8_t     universe;      // Art-Net universe for this output
  // Derived fields — call deriveFromType() after setting .type
  uint16_t    pixelCount;
  uint8_t     bytesPerPixel;
};

inline void deriveFromType(OutputConfig& cfg) {
  cfg.pixelCount    = typePixels(cfg.type);
  cfg.bytesPerPixel = typeBpp(cfg.type);
}

// ─── DEFAULT OUTPUT LAYOUT ───────────────────────────────────────────
// Change these to match what's physically plugged in.
// Set unused outputs to OUTPUT_OFF.
inline void loadDefaultConfig(OutputConfig outputs[NUM_OUTPUTS]) {
  // Output 0 — Short strip, 68 RGB LEDs
  outputs[0].type     = OUTPUT_SHORT_STRIP;
  outputs[0].pxl8Port = 0;
  outputs[0].universe = 0;
  deriveFromType(outputs[0]);

  // Output 1 — Long strip, 72 RGB LEDs
  outputs[1].type     = OUTPUT_LONG_STRIP;
  outputs[1].pxl8Port = 1;
  outputs[1].universe = 1;
  deriveFromType(outputs[1]);

  // Output 2 — Grid 8x8, 64 RGB LEDs
  outputs[2].type     = OUTPUT_GRID;
  outputs[2].pxl8Port = 2;
  outputs[2].universe = 2;
  deriveFromType(outputs[2]);
}

// Count how many outputs are actually active
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
// Maximum pixels on any single port — NeoPXL8 allocates this for all 8 ports
#define MAX_LEDS_PER_PORT 72

// Pin mapping: ESP32-S3 GPIO → NeoPXL8 input port
#define PIN_PORT_0  18   // A0 / GPIO18
#define PIN_PORT_1  17   // A1 / GPIO17
#define PIN_PORT_2  16   // A2 / GPIO16

// =====================================================================
//  Buttons — ESP32-S3 Reverse TFT Feather
// =====================================================================
#define BTN_D0  0   // Active-LOW (INPUT_PULLUP)  — cycle screens
#define BTN_D1  1   // Active-HIGH (INPUT_PULLDOWN) — toggle test mode

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
#define ARTNET_PORT            6454
#define ARTNET_OPCODE_DMX      0x5000
#define ARTNET_OPCODE_POLL     0x2000
#define ARTNET_OPCODE_POLLREPLY 0x2100
#define ARTNET_OPCODE_ADDRESS  0x6000
#define ARTNET_OPCODE_OUTPUT_CONFIG 0x8100  // Vendor-defined: set output types
#define ARTNET_PROTOCOL_VER    14

// Device identity — reported in ArtPollReply
#define DEVICE_SHORT_NAME  "PrimusV3"          // max 17 chars + null
#define DEVICE_LONG_NAME   "PrimusV3 LED Node"  // max 63 chars + null
#define FIRMWARE_VERSION_H 3
#define FIRMWARE_VERSION_L 0
#define OEM_CODE           0xFFFF                // generic / unregistered
#define ESTA_CODE          0x0000                // no ESTA manufacturer ID

// FPS back-channel
#define FPS_REPORT_PORT          6455   // UDP port for FPS telemetry to sender
#define FPS_BACKCHANNEL_ENABLED  true   // set false to disable FPS reports

// =====================================================================
//  Timing Constants (ms)
// =====================================================================
#define FPS_INTERVAL           1000   // Report FPS every 1 s
#define CONNECTION_TIMEOUT     10000  // Reconnect if no packets for 10 s
#define RECONNECT_INTERVAL     5000   // Retry WiFi every 5 s
#define FRAME_ASSEMBLY_TIMEOUT 5      // ms to wait for remaining universes

#endif // CONFIG_H
