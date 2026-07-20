#!/usr/bin/env bash
# =============================================================================
# template_minimal.sh — The simplest AUS 1.0 conforming upload script.
#
# Single board, no custom flags, no overrides. About 30 lines of real code.
# This is the "hello world" of AUS. Copy it, edit the profile block, done.
#
# Conforms to: AUS 1.0
# =============================================================================
set -euo pipefail

# --- 1. Script identity (used by --version and --ports-json). ---
# shellcheck disable=SC2034 # consumed by the sourced AUS library
AUS_SCRIPT_VERSION="0.1.0"

# --- 2. Locate the AUS library. ---
# The scaffolder fills AUS_LIB_DIR with the absolute path to aus_common.sh.
# If you move this script, set AUS_LIB_DIR manually or copy aus_common.sh
# alongside it.
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
AUS_LIB_DIR="${AUS_LIB_DIR:-$SCRIPT_DIR}"
# shellcheck disable=SC1090 # resolves at runtime
source "$AUS_LIB_DIR/aus_common.sh"

# --- 3. Tell AUS where the sketch lives. ---
SKETCH_DIR="$SCRIPT_DIR/__SKETCH_NAME__"

# --- 4. Register exactly one board profile. ---
# Edit these values for your hardware. See references/board-profiles.md
# for common presets (ESP32, ESP8266, AVR, RP2040).
aus_register_board default \
  --fqbn "__FQBN__" \
  --baud __BAUD__ \
  --libs __LIBS_CSV__ \
  --desc "__BOARD_DESC__"

# --- 5. Parse args + run. That's the whole script. ---
aus_parse_args "$@"
aus_run "$SKETCH_DIR"
