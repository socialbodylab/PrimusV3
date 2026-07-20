#!/usr/bin/env bash
# =============================================================================
# blue_green_upload.sh — AUS-conforming uploader for the blue_green test sketch.
#
# This is the reference example for §10.1 (serial assertion) of the AUS spec.
# It compiles the sketch, flashes it, and (if --expect is given) waits for the
# board to print its "blue_green ready" banner. Exit 0 = board is alive and
# talking on Serial; exit 11 = banner never appeared (hardware fault).
#
# Usage:
#   ./blue_green_upload.sh --ports              # what's connected?
#   ./blue_green_upload.sh --compile            # just verify it builds
#   ./blue_green_upload.sh --auto               # flash the one detected board
#   ./blue_green_upload.sh --auto --expect 'blue_green ready'   # flash + assert
#   ./blue_green_upload.sh /dev/cu.usbserial-XXXX --expect 'blue_green ready'
# =============================================================================
set -euo pipefail

# shellcheck disable=SC2034 # consumed by the sourced AUS library
AUS_SCRIPT_VERSION="1.0.0"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
AUS_LIB_DIR="${AUS_LIB_DIR:-$SCRIPT_DIR/../../../scripts}"
# shellcheck disable=SC1090 # resolves at runtime
source "$AUS_LIB_DIR/aus_common.sh"

SKETCH_DIR="$SCRIPT_DIR"

# Default to the Adafruit HUZZAH32 (most common ESP32 Feather).
# Override with: --board feather-s3, --fqbn <custom>, etc.
aus_register_board default \
  --fqbn "esp32:esp32:featheresp32" \
  --baud 115200 \
  --libs "Adafruit NeoPixel" \
  --desc "Adafruit HUZZAH32 (ESP32)"

# A second profile for the S3 Reverse TFT Feather — uncomment if you use one.
# aus_register_board feather-s3 \
#   --fqbn "esp32:esp32:adafruit_feather_esp32s3_reversetft" \
#   --baud 921600 \
#   --libs "Adafruit NeoPixel" \
#   --desc "Adafruit Feather ESP32-S3 Reverse TFT"

aus_parse_args "$@"
aus_run "$SKETCH_DIR"
