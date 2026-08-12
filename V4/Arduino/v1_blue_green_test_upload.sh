#!/usr/bin/env bash
# v1_blue_green_test_upload.sh — Compile & upload the V1 blue/green test sketch
# Usage:
#   ./v1_blue_green_test_upload.sh --ports
#   ./v1_blue_green_test_upload.sh --auto
#   ./v1_blue_green_test_upload.sh --compile
#   ./v1_blue_green_test_upload.sh /dev/cu.usbserial-XXXX

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
SKETCH_DIR="$SCRIPT_DIR/v1_blue_green_test"

if [[ -n "${ARDUINO_CLI:-}" && -x "$ARDUINO_CLI" ]]; then
  PATH="$(dirname "$ARDUINO_CLI"):$PATH"
fi

if [[ -n "${PRIMUSV3_PYTHON_BIN_DIR:-}" && -d "$PRIMUSV3_PYTHON_BIN_DIR" ]]; then
  PATH="$PRIMUSV3_PYTHON_BIN_DIR:$PATH"
fi

for local_bin in "$REPO_ROOT/.tools/arduino-cli/bin" "$REPO_ROOT/.tools/python-bin"; do
  if [[ -d "$local_bin" ]]; then
    PATH="$local_bin:$PATH"
  fi
done
export PATH

EXPLICIT_PORTS=()
UPLOAD_PORTS=()
COMPILE_ONLY=false
LIST_PORTS=false
AUTO_PORT=false
BAUD=115200

FQBN="esp32:esp32:featheresp32"
FQBN_WITH_OPTIONS="${FQBN}:UploadSpeed=${BAUD}"

info()  { printf "\033[1;34m[INFO]\033[0m  %s\n" "$*"; }
ok()    { printf "\033[1;32m[OK]\033[0m    %s\n" "$*"; }
err()   { printf "\033[1;31m[ERROR]\033[0m %s\n" "$*" >&2; }

usage() {
  cat <<'EOF'
v1_blue_green_test_upload.sh — V1 Huzzah32 blue/green LED test firmware

Usage:
  ./v1_blue_green_test_upload.sh --ports
  ./v1_blue_green_test_upload.sh --auto
  ./v1_blue_green_test_upload.sh --compile
  ./v1_blue_green_test_upload.sh /dev/cu.usbserial-XXXX
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --auto|-auto)
      AUTO_PORT=true
      shift
      ;;
    --ports|-ports|--list-ports)
      LIST_PORTS=true
      shift
      ;;
    --compile)
      COMPILE_ONLY=true
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    -*)
      err "Unknown flag: $1"
      usage
      exit 1
      ;;
    *)
      EXPLICIT_PORTS+=("$1")
      shift
      ;;
  esac
done

detect_auto_port() {
  python3 - "$FQBN" <<'PY'
import json
import subprocess
import sys

target_fqbn = sys.argv[1].lower()
ESP32_VIDS = {"10c4", "1a86", "303a", "239a", "0403"}
KEYWORDS = (
  "esp32", "espressif", "cp210", "cp210x", "ch340", "ch910",
  "wch", "silicon labs", "feather", "adafruit"
)
IGNORED = ("bluetooth", "debug-console")

def normalize_vid(value):
  if value is None:
    return ""
  text = str(value).strip().lower()
  if text.startswith("0x"):
    text = text[2:]
  return text.zfill(4)[-4:]

def port_vid(port):
  props = port.get("properties") or {}
  return normalize_vid(port.get("vendor_id") or port.get("vid") or props.get("vid"))

def looks_esp32(port):
  address = str(port.get("address") or "").lower()
  protocol = str(port.get("protocol") or "").lower()
  board = " ".join(
    str(item.get("name") or "") for item in (port.get("matching_boards") or [])
  ).lower()
  labels = " ".join([
    str(port.get("label") or ""),
    str(port.get("product") or ""),
    str(port.get("manufacturer") or ""),
    board,
  ]).lower()
  if any(token in labels or token in address for token in IGNORED):
    return False
  if port_vid(port) in ESP32_VIDS:
    return True
  haystack = f"{address} {protocol} {labels}"
  return any(keyword in haystack for keyword in KEYWORDS)

raw = subprocess.check_output(["arduino-cli", "board", "list", "--format", "json"], text=True)
payload = json.loads(raw or "{}")
detected = payload.get("detected_ports") or payload.get("ports") or []
candidates = []
for entry in detected:
  port = entry.get("port") if isinstance(entry, dict) and "port" in entry else entry
  if not isinstance(port, dict):
    continue
  address = str(port.get("address") or "").strip()
  if not address:
    continue
  boards = port.get("matching_boards") or entry.get("matching_boards") or []
  board_fqbns = [str(board.get("fqbn") or "") for board in boards if isinstance(board, dict)]
  if looks_esp32(port) or board_fqbns:
    candidates.append(address)

if len(candidates) == 1:
  print(candidates[0])
  sys.exit(0)
if not candidates:
  print("No ESP32-like serial ports were detected.", file=sys.stderr)
else:
  print("Multiple ESP32-like serial ports were detected:", file=sys.stderr)
  for address in candidates:
    print(f"  {address}", file=sys.stderr)
sys.exit(1)
PY
}

list_ports() {
  python3 - <<'PY'
import json
import subprocess

ESP32_VIDS = {"10c4", "1a86", "303a", "239a", "0403"}
KEYWORDS = ("esp32", "espressif", "cp210", "ch340", "feather", "adafruit")
IGNORED = ("bluetooth", "debug-console")

def normalize_vid(value):
  if value is None:
    return ""
  text = str(value).strip().lower()
  if text.startswith("0x"):
    text = text[2:]
  return text.zfill(4)[-4:]

def port_vid(port):
  props = port.get("properties") or {}
  return normalize_vid(port.get("vendor_id") or port.get("vid") or props.get("vid"))

def looks_esp32(port):
  address = str(port.get("address") or "").lower()
  labels = " ".join([
    str(port.get("label") or ""),
    str(port.get("product") or ""),
    str(port.get("manufacturer") or ""),
  ]).lower()
  if any(token in labels or token in address for token in IGNORED):
    return False
  if port_vid(port) in ESP32_VIDS:
    return True
  return any(k in f"{address} {labels}" for k in KEYWORDS)

raw = subprocess.check_output(["arduino-cli", "board", "list", "--format", "json"], text=True)
payload = json.loads(raw or "{}")
detected = payload.get("detected_ports") or payload.get("ports") or []
candidates = []
others = []
for entry in detected:
  port = entry.get("port") if isinstance(entry, dict) and "port" in entry else entry
  if not isinstance(port, dict):
    continue
  address = str(port.get("address") or "").strip()
  if not address:
    continue
  if looks_esp32(port):
    candidates.append(address)
  else:
    others.append(address)

if candidates:
  print("ESP32 candidate serial ports:")
  for address in candidates:
    print(f"  {address}")
else:
  print("No ESP32-like serial ports detected.")
if others:
  print("")
  print("Other serial ports:")
  for address in others:
    print(f"  {address}")
PY
}

if ! command -v arduino-cli &>/dev/null; then
  err "arduino-cli not found."
  exit 1
fi

if [[ "$LIST_PORTS" == true ]]; then
  list_ports
  exit 0
fi

if [[ "$COMPILE_ONLY" == false ]]; then
  if [[ ${#EXPLICIT_PORTS[@]} -gt 0 ]]; then
    UPLOAD_PORTS=("${EXPLICIT_PORTS[@]}")
  else
    info "Auto-detecting ESP32 serial port..."
    if ! detected_port="$(detect_auto_port)"; then
      exit 1
    fi
    UPLOAD_PORTS=("$detected_port")
  fi
fi

if ! arduino-cli core list 2>/dev/null | grep -q "esp32:esp32"; then
  info "Installing ESP32 board core..."
  arduino-cli core install esp32:esp32
fi

info "Installing Adafruit NeoPixel library if needed..."
arduino-cli lib install "Adafruit NeoPixel" >/dev/null 2>&1 || true

info "Compiling: $SKETCH_DIR"
arduino-cli compile --fqbn "$FQBN_WITH_OPTIONS" "$SKETCH_DIR" --warnings default
ok "Compilation successful"

if [[ "$COMPILE_ONLY" == true ]]; then
  exit 0
fi

info "Uploading to ${UPLOAD_PORTS[0]} at ${BAUD} baud..."
arduino-cli upload --fqbn "$FQBN_WITH_OPTIONS" --port "${UPLOAD_PORTS[0]}" "$SKETCH_DIR"
ok "Upload complete: ${UPLOAD_PORTS[0]}"
info "Serial monitor: arduino-cli monitor -p ${UPLOAD_PORTS[0]} -c baudrate=115200"
