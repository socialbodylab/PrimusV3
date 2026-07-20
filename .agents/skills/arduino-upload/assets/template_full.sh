#!/usr/bin/env bash
# =============================================================================
# template_full.sh — Full-featured AUS 1.0 conforming upload script.
#
# Demonstrates every common feature:
#   - Multiple board profiles (with a non-default default)
#   - Project-specific flags (--ssid, --password, --device-name)
#     wired through the aus_custom_arg hook
#   - Build overrides injected as #defines via the override header
#   - Secret redaction (password is never logged)
#   - A --post-upload-hook for protocol-level readback
#   - Custom usage text
#
# Conforms to: AUS 1.0
#
# This is a template — replace the __MARKED__ values and trim what you don't
# need. The structure (register → parse → run) is what matters.
# =============================================================================
set -euo pipefail

# --- Script identity. Bump this when you change the script. ---
# shellcheck disable=SC2034 # consumed by the sourced AUS library
AUS_SCRIPT_VERSION="1.0.0"

# --- Locate the AUS library. ---
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
AUS_LIB_DIR="${AUS_LIB_DIR:-$SCRIPT_DIR}"
# shellcheck disable=SC1090 # resolves at runtime
source "$AUS_LIB_DIR/aus_common.sh"

# --- Locate the sketch (sibling directory by convention). ---
SKETCH_DIR="$SCRIPT_DIR/__SKETCH_NAME__"

# =============================================================================
# Project-specific override state.
#
# These mirror the PrimusV3 firmware workflow: WiFi credentials, device name,
# and similar values get baked into a build via the override header so the
# same firmware image can be customized per-device at flash time.
# =============================================================================
WIFI_SSID=""
WIFI_PASSWORD=""
DEVICE_NAME=""
WIFI_OVERRIDE_SET=false

# =============================================================================
# Custom usage (overrides AUS's default).
# =============================================================================
aus_print_usage() {
  cat <<EOF
$(basename "$0") — compile & upload __PROJECT_NAME__ firmware (AUS 1.0)

Usage:
  $(basename "$0") [--board PROFILE] [--auto | --all | PORT ...] [options]

Standard AUS flags:
  --board v1|v2          Select board profile (default: v1).
  --compile              Compile only (no flash). Like Arduino IDE Verify.
  --install              Install cores + libraries, then exit.
  --auto                 Use the single detected port.
  --all                  Flash every candidate port.
  --ports                List candidate ports and exit.
  --ports-json           List candidate ports as JSON (machine-readable).
  --define KEY=VAL       Add -DKEY=VAL to compiler flags.
  --define-header K=V    Add #define K V to the override header.
  --post-upload-hook P   Run P after each upload.
  --expect REGEX         Assert a serial line matches REGEX after upload.
  --baud N               Override upload speed.
  --clean                Wipe build cache before compiling.
  --dry-run              Print commands; execute nothing.
  --no-color             Disable ANSI color.
  -v, --verbose          Increase verbosity.
  --quiet                Errors only.
  -h, --help             Show this help.
  --version              Print version and exit.

Project flags (baked into the build via override header):
  --ssid NAME            Override the default WiFi SSID for this build.
  --password PASS        Override the default WiFi password (never logged).
  --device-name NAME     Override the default device name for this build.

Examples:
  $(basename "$0") --board v1 --compile            # verify-only
  $(basename "$0") --board v2 --auto               # flash detected board
  $(basename "$0") --board v1 --ssid Home --password secret --auto
  $(basename "$0") --board v2 --all                # flash every board
EOF
}

# =============================================================================
# Custom-arg hook: handle project-specific flags.
#
# Called by aus_parse_args for any unrecognized flag. Return 0 if handled
# (and set AUS_CUSTOM_SHIFT to how many args to consume), 1 if not yours.
# =============================================================================
aus_custom_arg() {
  local flag="$1" val="${2:-}"

  case "$flag" in
    --ssid)
      [[ -z "$val" ]] && aus_die "$AUS_EXIT_GENERIC" "$flag requires a value"
      WIFI_SSID="$val"
      WIFI_OVERRIDE_SET=true
      # shellcheck disable=SC2034 # read by aus_parse_args to know how many args to shift
      AUS_CUSTOM_SHIFT=2
      return 0
      ;;
    --password)
      [[ -z "$val" ]] && aus_die "$AUS_EXIT_GENERIC" "$flag requires a value"
      WIFI_PASSWORD="$val"
      WIFI_OVERRIDE_SET=true
      # shellcheck disable=SC2034 # read by aus_parse_args to know how many args to shift
      AUS_CUSTOM_SHIFT=2
      return 0
      ;;
    --device-name)
      [[ -z "$val" ]] && aus_die "$AUS_EXIT_GENERIC" "$flag requires a value"
      DEVICE_NAME="$val"
      # shellcheck disable=SC2034 # read by aus_parse_args to know how many args to shift
      AUS_CUSTOM_SHIFT=2
      return 0
      ;;
  esac
  return 1  # not ours — let AUS reject it
}

# =============================================================================
# Register board profiles.
#
# Each profile pins an FQBN, default baud, required libraries, and the USB VID
# set + keywords used for port detection. See references/board-profiles.md.
# =============================================================================
aus_register_board v1 \
  --fqbn "esp32:esp32:featheresp32" \
  --baud 115200 \
  --libs "Adafruit NeoPixel" \
  --desc "Adafruit HUZZAH32 (ESP32)" \
  --default

aus_register_board v2 \
  --fqbn "esp32:esp32:adafruit_feather_esp32s3_reversetft" \
  --baud 921600 \
  --libs "Adafruit NeoPixel,Adafruit GFX Library,Adafruit ST7735 and ST7789 Library" \
  --desc "Adafruit Feather ESP32-S3 Reverse TFT"

# =============================================================================
# Translate project overrides into the override header.
#
# This runs AFTER aus_parse_args (so flags are populated) but BEFORE aus_run
# (so the header is ready when compile fires). The header is cleaned up
# automatically by an EXIT trap inside the library.
# =============================================================================
_apply_project_overrides() {
  if [[ "$WIFI_OVERRIDE_SET" == true ]]; then
    if [[ -n "$WIFI_SSID" ]]; then
      # Validate: no newlines, non-empty.
      [[ "$WIFI_SSID" == *$'\n'* || "$WIFI_SSID" == *$'\r'* ]] && \
        aus_die "$AUS_EXIT_GENERIC" "SSID cannot contain newlines."
      aus_override_define_cstring DEFAULT_WIFI_SSID "$WIFI_SSID"
    fi
    if [[ -n "$WIFI_PASSWORD" ]]; then
      [[ "$WIFI_PASSWORD" == *$'\n'* || "$WIFI_PASSWORD" == *$'\r'* ]] && \
        aus_die "$AUS_EXIT_GENERIC" "Password cannot contain newlines."
      aus_override_define_cstring DEFAULT_WIFI_PASSWORD "$WIFI_PASSWORD"
      # Mark as secret so it's never echoed in the overrides summary.
      aus_mark_secret DEFAULT_WIFI_PASSWORD
    fi
  fi

  if [[ -n "$DEVICE_NAME" ]]; then
    [[ "$DEVICE_NAME" == *$'\n'* || "$DEVICE_NAME" == *$'\r'* ]] && \
      aus_die "$AUS_EXIT_GENERIC" "Device name cannot contain newlines."
    if [[ ${#DEVICE_NAME} -gt 32 ]]; then
      aus_die "$AUS_EXIT_GENERIC" "Device name must be 32 characters or fewer."
    fi
    aus_override_define_cstring DEVICE_SHORT_NAME "$DEVICE_NAME"
  fi
}

# =============================================================================
# Main.
# =============================================================================
aus_parse_args "$@"
_apply_project_overrides
aus_run "$SKETCH_DIR"
