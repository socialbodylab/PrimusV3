#!/usr/bin/env bash
# upload.sh — Compile & upload primusV3_receiver to ESP32-S3 Reverse TFT Feather
# Usage:
#   ./upload.sh              # auto-detect port, compile + upload
#   ./upload.sh /dev/cu.usbmodem14101   # specify port manually
#   ./upload.sh --compile    # compile only, no upload
#   ./upload.sh --install    # install required libraries only

set -euo pipefail

SKETCH_DIR="$(cd "$(dirname "$0")/primusV3_receiver" && pwd)"
FQBN="esp32:esp32:adafruit_feather_esp32s3_reversetft"
BAUD=921600

REQUIRED_LIBS=(
  "Adafruit NeoPXL8"
  "Adafruit ST7735 and ST7789 Library"
  "Adafruit GFX Library"
)

info()  { printf "\033[1;34m[INFO]\033[0m  %s\n" "$*"; }
ok()    { printf "\033[1;32m[OK]\033[0m    %s\n" "$*"; }
err()   { printf "\033[1;31m[ERROR]\033[0m %s\n" "$*" >&2; }

check_cli() {
  if ! command -v arduino-cli &>/dev/null; then
    err "arduino-cli not found. Install: brew install arduino-cli"
    exit 1
  fi
}

install_libs() {
  info "Checking required libraries..."
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
for p in ports:
    addr = p.get('port', p.get('matching_boards', [{}]))
    boards = p.get('matching_boards', [])
    for b in boards:
        if 'esp32s3' in b.get('fqbn', '').lower():
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

if [[ "${1:-}" == "--install" ]]; then
  install_libs
  exit 0
fi

if ! arduino-cli core list 2>/dev/null | grep -q "esp32:esp32"; then
  info "Installing ESP32 board core..."
  arduino-cli core install esp32:esp32
fi

install_libs

info "Compiling sketch: $SKETCH_DIR"
info "Board: $FQBN"
arduino-cli compile --fqbn "$FQBN" "$SKETCH_DIR" --warnings default
ok "Compilation successful"

if [[ "${1:-}" == "--compile" ]]; then
  exit 0
fi

PORT="${1:-}"
if [[ -z "$PORT" ]]; then
  info "Auto-detecting board port..."
  PORT=$(detect_port)
fi

if [[ -z "$PORT" ]]; then
  err "No board detected. Connect your ESP32-S3 Reverse TFT Feather and try again."
  err "  Or specify port manually: $0 /dev/cu.usbmodemXXXX"
  echo ""
  info "Available ports:"
  arduino-cli board list
  exit 1
fi

ok "Using port: $PORT"

info "Uploading to $PORT at ${BAUD} baud..."
arduino-cli upload --fqbn "$FQBN" --port "$PORT" "$SKETCH_DIR"
ok "Upload complete!"
echo ""
info "Monitor serial output with: arduino-cli monitor -p $PORT -b $FQBN"
