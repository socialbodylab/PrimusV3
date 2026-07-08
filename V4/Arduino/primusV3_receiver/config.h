/*
 * config.h — PrimusV3.6 Receiver Configuration
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
#define FIRMWARE_NAME    "PrimusV3.6"
#define FIRMWARE_VERSION "3.13.0"

// =====================================================================
//  Board Profile
// =====================================================================
// Build with exactly one of:
//   -DPRIMUS_PROFILE_V1
//   -DPRIMUS_PROFILE_V2
//   -DPRIMUS_PROFILE_V3_1
// V3.1 remains the default so this tree still targets current hardware
// when no build profile flag is supplied.
#if !defined(PRIMUS_PROFILE_V1) && !defined(PRIMUS_PROFILE_V2) && !defined(PRIMUS_PROFILE_V3_1)
  #define PRIMUS_PROFILE_V3_1
#endif

#define PRIMUS_DRIVER_NEOPXL8 1
#define PRIMUS_DRIVER_DIRECT  2

// Maximum pixels on any single output. Sized for the V3.6 extra-long strip.
#define MAX_LEDS_PER_PORT 122
// Maximum DMX buffer bytes per output (RGBW-sized).
#define MAX_BUFFER_SIZE (MAX_LEDS_PER_PORT * 4)

// =====================================================================
//  Output Type Definitions
// =====================================================================
enum OutputType {
  OUTPUT_OFF         = 0,
  OUTPUT_SHORT_STRIP = 1,
  OUTPUT_LONG_STRIP  = 2,
  OUTPUT_GRID        = 3,
  OUTPUT_SMALL_GRID  = 4,
  OUTPUT_EXTRA_LONG_STRIP = 5
};

#if defined(PRIMUS_PROFILE_V1)
  #ifndef LED_BUILTIN
    #define LED_BUILTIN 13
  #endif
  #define BOARD_PROFILE_ID        "v1_huzzah"
  #define BOARD_PROFILE_CODE      "v1"
  #define BOARD_PROFILE_LABEL     "V1 Huzzah32"
  #define BOARD_OUTPUT_DRIVER     PRIMUS_DRIVER_DIRECT
  #define BOARD_HAS_TFT_DISPLAY   0
  #define BOARD_HAS_BUTTONS       0
  #define BOARD_HAS_STATUS_LED    1
  #define BOARD_STATUS_LED_PIN    LED_BUILTIN
  #define BOARD_STATUS_LED_ACTIVE_HIGH 1
  #define OUTPUT0_PIN             32
  #define OUTPUT1_PIN             12
  #define OUTPUT0_PHYSICAL_PORT   0
  #define OUTPUT1_PHYSICAL_PORT   1
  #define OUTPUT0_DEFAULT_TYPE    OUTPUT_SMALL_GRID   // Badge (8×4 grid)
  #define OUTPUT1_DEFAULT_TYPE    OUTPUT_LONG_STRIP   // Collar (72 px strip)
  #define BOARD_BATTERY_MONITOR   1
  #define BOARD_BATTERY_PIN       A13
  #define BOARD_BATTERY_FEATURES  "RIOHBMS"
  #ifndef DEFAULT_SHOW_CHARACTER_NAME
  #define DEFAULT_SHOW_CHARACTER_NAME "Character"
  #endif
  #ifndef DEFAULT_SHOW_PERFORMER_NAME
  #define DEFAULT_SHOW_PERFORMER_NAME "Performer"
  #endif
#elif defined(PRIMUS_PROFILE_V2)
  #define BOARD_PROFILE_ID        "v2_feather"
  #define BOARD_PROFILE_CODE      "v2"
  #define BOARD_PROFILE_LABEL     "V2 Feather"
  #define BOARD_OUTPUT_DRIVER     PRIMUS_DRIVER_DIRECT
  #define BOARD_HAS_TFT_DISPLAY   0
  #define BOARD_HAS_BUTTONS       0
  #define BOARD_HAS_STATUS_NEOPIXEL 1
  #define BOARD_STATUS_NEOPIXEL_PIN 0
  #define BOARD_STATUS_NEOPIXEL_POWER_PIN 2
  #define BOARD_STATUS_NEOPIXEL_BRIGHTNESS 40
  #define OUTPUT0_PIN             32
  #define OUTPUT1_PIN             12
  #define OUTPUT0_PHYSICAL_PORT   0
  #define OUTPUT1_PHYSICAL_PORT   1
  #define OUTPUT0_DEFAULT_TYPE    OUTPUT_SMALL_GRID
  #define OUTPUT1_DEFAULT_TYPE    OUTPUT_LONG_STRIP
#else
  #define BOARD_PROFILE_ID        "v3_1_reverse_tft"
  #define BOARD_PROFILE_CODE      "v31"
  #define BOARD_PROFILE_LABEL     "V3.1 Reverse TFT"
  #define BOARD_OUTPUT_DRIVER     PRIMUS_DRIVER_DIRECT
  #define BOARD_HAS_TFT_DISPLAY   1
  #define BOARD_HAS_BUTTONS       1
  #define OUTPUT0_PIN             A0   // GPIO17 — custom PCB output 0
  #define OUTPUT1_PIN             A1   // GPIO18 — custom PCB output 1
  #define OUTPUT0_PHYSICAL_PORT   0
  #define OUTPUT1_PHYSICAL_PORT   1
  #define OUTPUT0_DEFAULT_TYPE    OUTPUT_SMALL_GRID   // Badge (8×4 grid)
  #define OUTPUT1_DEFAULT_TYPE    OUTPUT_LONG_STRIP   // Collar (72 px strip)
  #define BOARD_OUTPUT_WIFI_GATED 1
  #define BOARD_BATTERY_MONITOR   1
  #define BOARD_BATTERY_PIN       A4   // GPIO14 — 5V rail via 100k/100k divider
  #define BOARD_BATTERY_FEATURES  "RIOHBMS"
  #define BOARD_BATTERY_TYPE_RAIL 1
  #define BOARD_BATTERY_ADC_SCALE_NUM  2
  #define BOARD_BATTERY_ADC_SCALE_DEN  1
  #define BOARD_BATTERY_MV_REGULATED   4980
  #define BOARD_BATTERY_MV_FULL        5000
  #define BOARD_BATTERY_MV_WARN        4600
  #define BOARD_BATTERY_MV_EMPTY       4300
#endif

#ifndef BOARD_BATTERY_MONITOR
  #define BOARD_BATTERY_MONITOR   0
#endif
#ifndef BOARD_BATTERY_FEATURES
  #define BOARD_BATTERY_FEATURES  "RIOHMS"
#endif
#ifndef BOARD_OUTPUT_WIFI_GATED
  #define BOARD_OUTPUT_WIFI_GATED 0
#endif
#ifndef BOARD_BATTERY_TYPE_RAIL
  #define BOARD_BATTERY_TYPE_RAIL 0
#endif
#ifndef BOARD_BATTERY_ADC_SCALE_NUM
  #define BOARD_BATTERY_ADC_SCALE_NUM  2
#endif
#ifndef BOARD_BATTERY_ADC_SCALE_DEN
  #define BOARD_BATTERY_ADC_SCALE_DEN  1
#endif
#ifndef BOARD_BATTERY_MV_REGULATED
  #define BOARD_BATTERY_MV_REGULATED 4980
#endif
#ifndef BOARD_BATTERY_MV_FULL
  #define BOARD_BATTERY_MV_FULL 5000
#endif
#ifndef BOARD_BATTERY_MV_WARN
  #define BOARD_BATTERY_MV_WARN 4600
#endif
#ifndef BOARD_BATTERY_MV_EMPTY
  #define BOARD_BATTERY_MV_EMPTY 4300
#endif

#ifndef BOARD_HAS_STATUS_LED
  #define BOARD_HAS_STATUS_LED 0
#endif
#ifndef BOARD_STATUS_LED_ACTIVE_HIGH
  #define BOARD_STATUS_LED_ACTIVE_HIGH 1
#endif
#ifndef BOARD_HAS_STATUS_NEOPIXEL
  #define BOARD_HAS_STATUS_NEOPIXEL 0
#endif
#ifndef BOARD_STATUS_NEOPIXEL_PIN
  #define BOARD_STATUS_NEOPIXEL_PIN -1
#endif
#ifndef BOARD_STATUS_NEOPIXEL_POWER_PIN
  #define BOARD_STATUS_NEOPIXEL_POWER_PIN -1
#endif
#ifndef BOARD_STATUS_NEOPIXEL_BRIGHTNESS
  #define BOARD_STATUS_NEOPIXEL_BRIGHTNESS 40
#endif

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
  /* OUTPUT_SMALL_GRID  */ { "Grid 8x4",    32, 3, LAYOUT_GRID,   8, 4 },
  /* OUTPUT_EXTRA_LONG_STRIP */ { "Extra Long Strip", 122, 3, LAYOUT_LINEAR, 0, 0 },
};

#define NUM_OUTPUT_TYPES (sizeof(OUTPUT_TYPE_TABLE) / sizeof(OUTPUT_TYPE_TABLE[0]))

// Convenience accessors
inline bool         isValidOutputType(OutputType t) { return (uint8_t)t < NUM_OUTPUT_TYPES; }
inline const char*  typeName(OutputType t)       { return isValidOutputType(t) ? OUTPUT_TYPE_TABLE[t].name : "Off"; }
inline uint16_t     typePixels(OutputType t)      { return isValidOutputType(t) ? OUTPUT_TYPE_TABLE[t].pixels : 0; }
inline uint8_t      typeBpp(OutputType t)         { return isValidOutputType(t) ? OUTPUT_TYPE_TABLE[t].bytesPerPixel : 0; }
inline LayoutType   typeLayout(OutputType t)      { return isValidOutputType(t) ? OUTPUT_TYPE_TABLE[t].layout : LAYOUT_NONE; }

// =====================================================================
//  Per-Output Configuration
// =====================================================================
#define NUM_OUTPUTS 2
#define MAX_OUTPUTS 2

struct OutputConfig {
  OutputType  type;
  uint8_t     pxl8Port;      // NeoPXL8 strand index, or direct-driver output index
  uint8_t     dataPin;       // physical data pin for direct-driver profiles
  uint16_t    universe;      // Art-Net universe for this output
  // Derived fields — call deriveFromType() after setting .type
  uint16_t    pixelCount;        // physical LED count
  uint16_t    virtualPixelCount; // Art-Net transport pixel count
  uint8_t     bytesPerPixel;
};

inline uint16_t defaultVirtualPixels(OutputType t) {
  if (t == OUTPUT_SMALL_GRID) return 1;
  return typePixels(t);
}

inline void applyVirtualPixelCount(OutputConfig& cfg, uint16_t virtualCount) {
  if (cfg.type == OUTPUT_OFF || cfg.pixelCount == 0) {
    cfg.virtualPixelCount = 0;
    return;
  }
  if (virtualCount < 1) virtualCount = 1;
  if (virtualCount > cfg.pixelCount) virtualCount = cfg.pixelCount;
  cfg.virtualPixelCount = virtualCount;
}

inline void deriveFromType(OutputConfig& cfg) {
  cfg.pixelCount    = typePixels(cfg.type);
  cfg.bytesPerPixel = typeBpp(cfg.type);
  applyVirtualPixelCount(cfg, defaultVirtualPixels(cfg.type));
}

inline bool profileSupportsOutputType(OutputType t) {
  if (!isValidOutputType(t)) return false;
  return typePixels(t) <= MAX_LEDS_PER_PORT;
}

// ─── DEFAULT OUTPUT LAYOUT ───────────────────────────────────────────
// Change these to match what's physically plugged in.
// Set unused outputs to OUTPUT_OFF.
inline void loadDefaultConfig(OutputConfig outputs[NUM_OUTPUTS]) {
  outputs[0].type     = OUTPUT0_DEFAULT_TYPE;
  outputs[0].pxl8Port = OUTPUT0_PHYSICAL_PORT;
  outputs[0].dataPin  = OUTPUT0_PIN;
  outputs[0].universe = 0;
  deriveFromType(outputs[0]);

  outputs[1].type     = OUTPUT1_DEFAULT_TYPE;
  outputs[1].pxl8Port = OUTPUT1_PHYSICAL_PORT;
  outputs[1].dataPin  = OUTPUT1_PIN;
  outputs[1].universe = 1;
  deriveFromType(outputs[1]);
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
//  LED Hardware
// =====================================================================
#if BOARD_OUTPUT_DRIVER == PRIMUS_DRIVER_NEOPXL8
// Legacy NeoPXL8 FeatherWing mapping (not used on current V3 custom PCB).
#define PIN_PORT_6  14
#define PIN_PORT_7  15
#endif

// Direct NeoPixel profiles (V1/V2/V3 custom PCB).
#define PIN_DIRECT_GRID   32
#define PIN_DIRECT_STRIP  12

// =====================================================================
//  Buttons — ESP32-S3 Reverse TFT Feather
// =====================================================================
#define BTN_D0  0   // Active-LOW (INPUT_PULLUP)  — cycle screens
#define BTN_D1  1   // Active-HIGH (INPUT_PULLDOWN) — toggle test mode

// =====================================================================
//  Network Defaults
// =====================================================================
#ifndef DEFAULT_WIFI_SSID
  #define DEFAULT_WIFI_SSID      "OPERADEV"
#endif
#ifndef DEFAULT_WIFI_PASSWORD
  #define DEFAULT_WIFI_PASSWORD  "torrentoflight"
#endif

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
#define ARTNET_OPCODE_RECEIVE_CONFIG 0x8110 // Vendor-defined: set receive mode / universe base
#define ARTNET_OPCODE_VIRTUAL_RESOLUTION 0x8130 // Vendor-defined: set virtual pixel counts
#define ARTNET_OPCODE_IP_CONFIG    0x8200  // Vendor-defined: set static/DHCP IP
#define ARTNET_OPCODE_SHOW_INFO    0x8210  // Vendor-defined: read/write show metadata
#define SHOW_INFO_FIELD_LEN        64
#define SHOW_INFO_MODE_READ        0
#define SHOW_INFO_MODE_WRITE       1
#define SHOW_INFO_MODE_RESPONSE    2
#define SHOW_INFO_PACKET_LEN       143
#ifndef DEFAULT_SHOW_CHARACTER_NAME
#define DEFAULT_SHOW_CHARACTER_NAME ""
#endif
#ifndef DEFAULT_SHOW_PERFORMER_NAME
#define DEFAULT_SHOW_PERFORMER_NAME "Performer"
#endif
#define ARTNET_PROTOCOL_VER    14

// Device identity — reported in ArtPollReply
#ifndef DEVICE_SHORT_NAME
  #define DEVICE_SHORT_NAME  "PrimusV3"        // max 17 chars + null
#endif
#define DEVICE_LONG_NAME   "PrimusV3.6 LED Node"  // max 63 chars + null
#define NODE_CAPS_PREFIX   "PV3CAP1"            // versioned capability tag in ArtPollReply NodeReport
#define FIRMWARE_VERSION_H 3
#define FIRMWARE_VERSION_L 13
#define OEM_CODE           0xFFFF                // generic / unregistered
#define ESTA_CODE          0x0000                // no ESTA manufacturer ID

// Keep the V3.5 namespace so V3.6 upgrades preserve device names, IP config,
// and output assignments already stored on deployed receivers.
#define PERSISTENCE_NAMESPACE "primus35"

// FPS back-channel
#define FPS_REPORT_PORT          6455   // UDP port for FPS telemetry to sender
#define FPS_BACKCHANNEL_ENABLED  true   // set false to disable FPS reports

// =====================================================================
//  Timing Constants (ms)
// =====================================================================
#define FPS_INTERVAL           1000   // Report FPS every 1 s
#define BATTERY_REPORT_INTERVAL_MS 5000 // Report battery every 5 s
#define CONNECTION_TIMEOUT     10000  // Reconnect if no packets for 10 s
#define RECONNECT_INTERVAL     5000   // Retry WiFi every 5 s
#define FRAME_ASSEMBLY_TIMEOUT 5      // ms to wait for remaining universes

#endif // CONFIG_H
