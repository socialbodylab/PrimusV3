#!/usr/bin/env bash
# upload.sh — Compile & upload PrimusV3.5 receiver build profiles
# Usage:
#   ./upload.sh --board v3_1              # auto-detect port, compile + upload
#   ./upload.sh --board v1 --compile      # compile V1 only
#   ./upload.sh --board v2 /dev/cu.usb... # upload V2 to an explicit port
#   ./upload.sh --board v2 --baud 115200 /dev/cu.usb... # override upload speed
#   ./upload.sh --install                 # install libraries for selected board

set -euo pipefail

SKETCH_DIR="$(cd "$(dirname "$0")/primusV3_receiver" && pwd)"
BOARD_PROFILE="v3_1"
PORT=""
COMPILE_ONLY=false
INSTALL_ONLY=false
BAUD=921600
BAUD_OVERRIDE=""

info()  { printf "\033[1;34m[INFO]\033[0m  %s\n" "$*"; }
ok()    { printf "\033[1;32m[OK]\033[0m    %s\n" "$*"; }
err()   { printf "\033[1;31m[ERROR]\033[0m %s\n" "$*" >&2; }

while [[ $# -gt 0 ]]; do
  case "$1" in
    --board)
      BOARD_PROFILE="${2:-}"
      shift 2
      ;;
    --compile)
      COMPILE_ONLY=true
      shift
      ;;
    --install)
      INSTALL_ONLY=true
      shift
      ;;
    --baud|--speed)
      BAUD_OVERRIDE="${2:-}"
      shift 2
      ;;
    -h|--help)
      sed -n '1,12p' "$0"
      exit 0
      ;;
    *)
      PORT="$1"
      shift
      ;;
  esac
done

case "$BOARD_PROFILE" in
  v1|v1_huzzah)
    BOARD_PROFILE="v1"
    FQBN="esp32:esp32:featheresp32"
    EXTRA_FLAGS="-DPRIMUS_PROFILE_V1"
    DEFAULT_BAUD=115200
    REQUIRED_LIBS=("Adafruit NeoPixel")
    ;;
  v2|v2_feather)
    BOARD_PROFILE="v2"
    FQBN="esp32:esp32:adafruit_feather_esp32_v2"
    EXTRA_FLAGS="-DPRIMUS_PROFILE_V2"
    DEFAULT_BAUD=115200
    REQUIRED_LIBS=("Adafruit NeoPixel")
    ;;
  v3|v3_1|v31|v3_1_reverse_tft)
    BOARD_PROFILE="v3_1"
    FQBN="esp32:esp32:adafruit_feather_esp32s3_reversetft"
    EXTRA_FLAGS="-DPRIMUS_PROFILE_V3_1"
    DEFAULT_BAUD=921600
    REQUIRED_LIBS=(
      "Adafruit NeoPXL8"
      "Adafruit ST7735 and ST7789 Library"
      "Adafruit GFX Library"
    )
    ;;
  *)
    err "Unknown board profile: $BOARD_PROFILE"
    err "Expected one of: v1, v2, v3_1"
    exit 1
    ;;
esac

  BAUD="${BAUD_OVERRIDE:-$DEFAULT_BAUD}"
  FQBN_WITH_OPTIONS="${FQBN}:UploadSpeed=${BAUD}"

check_cli() {
  if ! command -v arduino-cli &>/dev/null; then
    err "arduino-cli not found. Install: brew install arduino-cli"
    exit 1
  fi
}

install_libs() {
  info "Checking required libraries for $BOARD_PROFILE..."
  local installed
  installed=$(arduino-cli lib list --format json 2>/dev/null || echo "[]")
  for lib in "${REQUIRED_LIBS[@]}"; do
    if echo "$installed" | grep -qi "$(echo "$lib" | sed 's/ /./g')"; then
      ok "Already installed: $lib"
    else
      info "Installing: $lib"
      arduino-cli lib install "$lib"
      ok "Installed: $lib"
    fi
  done
}

detect_port() {
  local port
  port=$(arduino-cli board list --format json 2>/dev/null \
    | python3 -c "
import sys, json
data = json.load(sys.stdin)
ports = data.get('detected_ports', data) if isinstance(data, dict) else data
target = '$FQBN'.lower()
for p in ports:
    addr = p.get('port', {})
    boards = p.get('matching_boards', [])
    for b in boards:
        if b.get('fqbn', '').lower() == target:
            print(addr.get('address', '') if isinstance(addr, dict) else '')
            sys.exit(0)
for p in ports:
    addr = p.get('port', {})
    if isinstance(addr, dict) and addr.get('protocol', '') == 'serial':
        print(addr.get('address', ''))
        sys.exit(0)
" 2>/dev/null)
  echo "$port"
}

check_cli

if ! arduino-cli core list 2>/dev/null | grep -q "esp32:esp32"; then
  info "Installing ESP32 board core..."
  arduino-cli core install esp32:esp32
fi

install_libs

if [[ "$INSTALL_ONLY" == true ]]; then
  exit 0
fi

info "Compiling sketch: $SKETCH_DIR"
info "Board profile: $BOARD_PROFILE"
info "Board: $FQBN_WITH_OPTIONS"
arduino-cli compile \
  --fqbn "$FQBN_WITH_OPTIONS" \
  --build-property "compiler.cpp.extra_flags=$EXTRA_FLAGS" \
  --build-property "compiler.c.extra_flags=$EXTRA_FLAGS" \
  "$SKETCH_DIR" --warnings default
ok "Compilation successful"

if [[ "$COMPILE_ONLY" == true ]]; then
  exit 0
fi

if [[ -z "$PORT" ]]; then
  info "Auto-detecting board port..."
  PORT=$(detect_port)
fi

if [[ -z "$PORT" ]]; then
  err "No board detected. Connect the target board and try again."
  err "  Or specify port manually: $0 --board $BOARD_PROFILE /dev/cu.usbmodemXXXX"
  echo ""
  info "Available ports:"
  arduino-cli board list
  exit 1
fi

ok "Using port: $PORT"

info "Uploading to $PORT at ${BAUD} baud..."
arduino-cli upload --fqbn "$FQBN_WITH_OPTIONS" --port "$PORT" "$SKETCH_DIR"
ok "Upload complete!"
echo ""
info "Monitor serial output with: arduino-cli monitor -p $PORT -b $FQBN"
