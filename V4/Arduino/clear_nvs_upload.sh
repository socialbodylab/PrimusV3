#!/usr/bin/env bash
# clear_nvs_upload.sh — Compile & upload the NVS factory-clear sketch
# Usage:
#   ./clear_nvs_upload.sh --ports
#   ./clear_nvs_upload.sh -v1 --auto
#   ./clear_nvs_upload.sh -v2 --auto
#   ./clear_nvs_upload.sh -v3 --auto
#   ./clear_nvs_upload.sh --board radius_v1 --auto
#   ./clear_nvs_upload.sh -v3 --compile
#
# After upload, open serial at 115200 baud and confirm "NVS CLEAR COMPLETE",
# then re-flash normal Primus or Radius firmware.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
SKETCH_DIR="$SCRIPT_DIR/clear_nvs"

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
if [[ -n "${ARDUINO_CLI:-}" && -x "$ARDUINO_CLI" ]]; then
  PATH="$(dirname "$ARDUINO_CLI"):$PATH"
fi
export PATH

BOARD_PROFILE="v3"
EXPLICIT_PORTS=()
UPLOAD_PORTS=()
COMPILE_ONLY=false
LIST_PORTS=false
LIST_PORTS_JSON=false
AUTO_PORT=false
ALL_PORTS=false
BAUD=921600
BAUD_OVERRIDE=""

info()  { printf "\033[1;34m[INFO]\033[0m  %s\n" "$*"; }
ok()    { printf "\033[1;32m[OK]\033[0m    %s\n" "$*"; }
err()   { printf "\033[1;31m[ERROR]\033[0m %s\n" "$*" >&2; }

usage() {
  cat <<'EOF'
clear_nvs_upload.sh — Compile & upload the NVS factory-clear sketch

Erases all saved receiver settings on the connected ESP32 (device name,
show info, static IP, output types, receive mode, WiFi credentials).

Usage:
  ./clear_nvs_upload.sh --ports
  ./clear_nvs_upload.sh -v1 --auto
  ./clear_nvs_upload.sh -v2 --auto
  ./clear_nvs_upload.sh -v3 --auto
  ./clear_nvs_upload.sh --board radius_v1 --auto
  ./clear_nvs_upload.sh -v3 --compile
  ./clear_nvs_upload.sh -v2 /dev/cu.usbserial-XXXX

Flags:
  -v1, -v2, -v3            Primus hardware profile. Default: -v3.
  --board v1|v2|v3|radius_v1|radius_v2
                           Long-form board selection (radius_v1 = HUZZAH32).
  --auto, -auto            Select the only detected ESP32-like serial port.
  --all, -all              Upload to every detected ESP32-like serial port.
  --ports, -ports          List likely ESP32 serial ports and exit.
  --ports-json             List ports as JSON and exit.
  --compile                Compile only; do not upload.
  --baud, --speed <rate>   Override upload speed.
  -h, --help               Show this help.

After a successful wipe, re-flash normal Primus or Radius firmware.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    -v1)
      BOARD_PROFILE="v1"
      shift
      ;;
    -v2)
      BOARD_PROFILE="v2"
      shift
      ;;
    -v3|-v3_1)
      BOARD_PROFILE="v3"
      shift
      ;;
    --board)
      if [[ $# -lt 2 || -z "${2:-}" ]]; then
        err "--board requires a value: v1, v2, v3, radius_v1, or radius_v2"
        exit 1
      fi
      BOARD_PROFILE="${2:-}"
      shift 2
      ;;
    --auto|-auto)
      AUTO_PORT=true
      shift
      ;;
    --all|-all|--all-ports)
      ALL_PORTS=true
      shift
      ;;
    --ports|-ports|--list-ports|--detect-ports)
      LIST_PORTS=true
      shift
      ;;
    --ports-json|--list-ports-json)
      LIST_PORTS_JSON=true
      shift
      ;;
    --compile)
      COMPILE_ONLY=true
      shift
      ;;
    --baud|--speed)
      if [[ $# -lt 2 || -z "${2:-}" ]]; then
        err "$1 requires a baud rate"
        exit 1
      fi
      BAUD_OVERRIDE="$2"
      shift 2
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

if [[ "$ALL_PORTS" == true && ${#EXPLICIT_PORTS[@]} -gt 0 ]]; then
  err "Use either --all or explicit serial ports, not both."
  exit 1
fi

case "$BOARD_PROFILE" in
  v1|v1_huzzah)
    BOARD_PROFILE="v1"
    FQBN="esp32:esp32:featheresp32"
    DEFAULT_BAUD=115200
    ;;
  v2|v2_feather)
    BOARD_PROFILE="v2"
    FQBN="esp32:esp32:adafruit_feather_esp32_v2"
    DEFAULT_BAUD=115200
    ;;
  v3|v3_1|v31|v3_1_reverse_tft)
    BOARD_PROFILE="v3"
    FQBN="esp32:esp32:adafruit_feather_esp32s3_reversetft"
    DEFAULT_BAUD=921600
    ;;
  radius_v1|rv1|radius-v1)
    BOARD_PROFILE="radius_v1"
    FQBN="esp32:esp32:featheresp32"
    DEFAULT_BAUD=115200
    ;;
  radius_v2|rv2|radius-v2)
    BOARD_PROFILE="radius_v2"
    FQBN="esp32:esp32:adafruit_feather_esp32s3_reversetft"
    DEFAULT_BAUD=921600
    ;;
  *)
    err "Unknown board profile: $BOARD_PROFILE"
    err "Expected one of: v1, v2, v3, radius_v1, radius_v2"
    exit 1
    ;;
esac

BAUD="${BAUD_OVERRIDE:-$DEFAULT_BAUD}"
FQBN_WITH_OPTIONS="${FQBN}:UploadSpeed=${BAUD}"

check_cli() {
  if [[ "$LIST_PORTS_JSON" != true ]]; then
    info "Checking Arduino CLI..."
  fi
  if ! command -v arduino-cli &>/dev/null; then
    err "arduino-cli not found. Install Arduino CLI: https://arduino.github.io/arduino-cli/latest/installation/"
    exit 1
  fi
  if needs_python3 && ! command -v python3 &>/dev/null; then
    err "python3 not found. It is required to parse arduino-cli board output."
    exit 1
  fi
}

needs_python3() {
  if [[ "$LIST_PORTS" == true || "$LIST_PORTS_JSON" == true || "$AUTO_PORT" == true || "$ALL_PORTS" == true ]]; then
    return 0
  fi
  if [[ "$COMPILE_ONLY" == false && ${#EXPLICIT_PORTS[@]} -eq 0 ]]; then
    return 0
  fi
  return 1
}

port_parser() {
  local mode="$1"
  python3 - "$mode" "$FQBN" <<'PY'
import json
import re
import subprocess
import sys

mode = sys.argv[1]
target_fqbn = sys.argv[2].lower()

ESP32_VIDS = {"10c4", "1a86", "303a", "239a", "0403"}
KEYWORDS = (
  "esp32", "espressif", "cp210", "cp210x", "ch340", "ch910",
  "wch", "silicon labs", "feather", "adafruit"
)
IGNORED_KEYWORDS = ("bluetooth", "debug-console")


def normalize_vid(value):
  if value is None:
    return ""
  text = str(value).strip().lower()
  if text.startswith("0x"):
    text = text[2:]
  return text.zfill(4)[-4:]


def looks_esp32(port):
  address = str(port.get("address") or "").lower()
  protocol = str(port.get("protocol") or "").lower()
  board = " ".join(
    str(item.get("name") or "") for item in (port.get("matching_boards") or [])
  ).lower()
  labels = " ".join(
    [
      str(port.get("label") or ""),
      str(port.get("product") or ""),
      str(port.get("manufacturer") or ""),
      board,
    ]
  ).lower()
  if any(token in labels or token in address for token in IGNORED_KEYWORDS):
    return False
  vid = normalize_vid(port.get("vendor_id") or port.get("vid"))
  if vid in ESP32_VIDS:
    return True
  haystack = f"{address} {protocol} {labels}"
  return any(keyword in haystack for keyword in KEYWORDS)


raw = subprocess.check_output(
  ["arduino-cli", "board", "list", "--format", "json"],
  text=True,
)
payload = json.loads(raw or "{}")
detected = payload.get("detected_ports") or payload.get("ports") or []
if isinstance(payload, list):
  detected = payload

candidates = []
others = []
for entry in detected:
  port = entry.get("port") if isinstance(entry, dict) and "port" in entry else entry
  if not isinstance(port, dict):
    continue
  address = str(port.get("address") or "").strip()
  if not address:
    continue
  boards = port.get("matching_boards") or entry.get("matching_boards") or []
  board_names = []
  board_fqbns = []
  for board in boards:
    if not isinstance(board, dict):
      continue
    board_names.append(str(board.get("name") or ""))
    board_fqbns.append(str(board.get("fqbn") or ""))
  board_label = ", ".join(name for name in board_names if name) or "unknown"
  reason_bits = [board_label]
  target_match = any(fqbn.lower() == target_fqbn for fqbn in board_fqbns)
  if target_match:
    reason_bits.append("exact board match")
  elif any(fqbn.lower().startswith("esp32:esp32:") for fqbn in board_fqbns):
    reason_bits.append("esp32 board family")
  record = {
    "address": address,
    "board": board_label,
    "reason": "; ".join(reason_bits),
    "protocol": str(port.get("protocol") or ""),
    "target_match": target_match,
  }
  if looks_esp32(port) or target_match or board_fqbns:
    candidates.append(record)
  else:
    others.append(record)

if mode == "json":
  print(json.dumps({
    "target_fqbn": target_fqbn,
    "candidates": candidates,
    "others": others,
  }, indent=2))
  sys.exit(0)

if mode == "all":
  if not candidates:
    print("No ESP32-like serial ports were detected.", file=sys.stderr)
    print("Run this script with --ports to inspect ports, or pass ports explicitly.", file=sys.stderr)
    sys.exit(1)
  exact_matches = [record for record in candidates if record["target_match"]]
  selected = exact_matches or candidates
  for record in selected:
    print(record["address"])
  sys.exit(0)

if mode == "auto":
  if len(candidates) == 1:
    print(candidates[0]["address"])
    sys.exit(0)
  if not candidates:
    print("No ESP32-like serial ports were detected.", file=sys.stderr)
  else:
    print("Multiple ESP32-like serial ports were detected:", file=sys.stderr)
    for record in candidates:
      print(f"  {record['address']}  ({record['reason']})", file=sys.stderr)
  print("Run this script with --ports to inspect ports, or pass a port explicitly.", file=sys.stderr)
  sys.exit(1)

if candidates:
  print("ESP32 candidate serial ports:")
  for record in candidates:
    print(f"  {record['address']}")
    print(f"    Board:  {record['board']}")
    print(f"    Reason: {record['reason']}")
else:
  print("No ESP32-like serial ports detected.")

if others:
  print("")
  print("Other serial ports detected (not selected by --auto):")
  for record in others:
    print(f"  {record['address']}  ({record['protocol']})")
PY
}

list_ports() {
  port_parser list
}

list_ports_json() {
  port_parser json
}

detect_auto_port() {
  port_parser auto
}

detect_all_ports() {
  port_parser all
}

check_cli

if [[ "$LIST_PORTS" == false && "$LIST_PORTS_JSON" == false ]]; then
  info "Starting NVS clear firmware build pipeline..."
fi

if [[ "$LIST_PORTS" == true ]]; then
  list_ports
  exit 0
fi

if [[ "$LIST_PORTS_JSON" == true ]]; then
  list_ports_json
  exit 0
fi

if [[ "$COMPILE_ONLY" == false ]]; then
  if [[ "$ALL_PORTS" == true ]]; then
    info "Detecting all ESP32 serial ports for upload..."
    if ! detected_ports="$(detect_all_ports)"; then
      exit 1
    fi
    while IFS= read -r detected_port; do
      if [[ -n "$detected_port" ]]; then
        UPLOAD_PORTS+=("$detected_port")
      fi
    done <<< "$detected_ports"
  elif [[ ${#EXPLICIT_PORTS[@]} -gt 0 ]]; then
    UPLOAD_PORTS=("${EXPLICIT_PORTS[@]}")
  else
    if [[ "$AUTO_PORT" == true ]]; then
      info "Auto-detecting ESP32 serial port..."
    else
      info "No serial port supplied; using auto-detect. Use --ports to inspect candidates or pass --auto explicitly."
    fi
    if ! detected_port="$(detect_auto_port)"; then
      exit 1
    fi
    UPLOAD_PORTS=("$detected_port")
  fi
fi

if [[ "$COMPILE_ONLY" == false && ${#UPLOAD_PORTS[@]} -eq 0 ]]; then
  err "No upload ports selected."
  exit 1
fi

if ! arduino-cli core list 2>/dev/null | grep -q "esp32:esp32"; then
  info "Installing ESP32 board core..."
  arduino-cli core install esp32:esp32
else
  info "ESP32 board core is installed."
fi

if [[ "$COMPILE_ONLY" == true ]]; then
  info "Compiling sketch: $SKETCH_DIR"
else
  info "Compiling sketch before upload: $SKETCH_DIR"
fi
info "Board profile: $BOARD_PROFILE"
info "Board: $FQBN_WITH_OPTIONS"
info "Running arduino-cli compile..."
arduino-cli compile \
  --fqbn "$FQBN_WITH_OPTIONS" \
  "$SKETCH_DIR" --warnings default
ok "Compilation successful"

if [[ "$COMPILE_ONLY" == true ]]; then
  exit 0
fi

if [[ ${#UPLOAD_PORTS[@]} -eq 1 ]]; then
  ok "Using port: ${UPLOAD_PORTS[0]}"
else
  ok "Using ports:"
  for upload_port in "${UPLOAD_PORTS[@]}"; do
    printf "  %s\n" "$upload_port"
  done
fi

for upload_port in "${UPLOAD_PORTS[@]}"; do
  info "Uploading NVS clear firmware to $upload_port at ${BAUD} baud..."
  arduino-cli upload --fqbn "$FQBN_WITH_OPTIONS" --port "$upload_port" "$SKETCH_DIR"
  ok "Upload complete: $upload_port"
done

echo ""
ok "NVS clear firmware uploaded."
info "Open serial at 115200 baud and confirm: NVS CLEAR COMPLETE"
info "Then re-flash normal Primus or Radius firmware."
if [[ ${#UPLOAD_PORTS[@]} -eq 1 ]]; then
  info "Monitor: arduino-cli monitor -p ${UPLOAD_PORTS[0]} -c baudrate=115200"
else
  info "Monitor: arduino-cli monitor -p <port> -c baudrate=115200"
fi
