#!/usr/bin/env bash
# upload.sh — Compile & upload PrimusV3.5 receiver build profiles
# Usage:
#   ./upload.sh --ports                   # list likely ESP32 serial ports
#   ./upload.sh --ports-json              # list likely ESP32 serial ports as JSON
#   ./upload.sh -v3 --auto                # compile, then upload if exactly one ESP32-like port is connected
#   ./upload.sh -v2 --all                 # compile, then upload selected profile to every detected ESP32-like port
#   ./upload.sh -v1 --compile             # compile V1 only, like Arduino IDE Verify
#   ./upload.sh -v2 /dev/cu.usb...        # compile, then upload V2 to an explicit port
#   ./upload.sh -v2 -ssid PrimusRouter -pw router-password --auto # override WiFi defaults for this build
#   ./upload.sh -v3 --name StageLeft --auto # override default device name for this build
#   ./upload.sh -v1 /dev/cu.usb1 /dev/cu.usb2 # upload selected profile to explicit ports
#   ./upload.sh -v2 --baud 115200 /dev/cu.usb... # override upload speed
#   ./upload.sh --install                 # install libraries for selected board

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
SKETCH_DIR="$SCRIPT_DIR/primusV3_receiver"

for local_bin in "$REPO_ROOT/.tools/arduino-cli/bin" "$REPO_ROOT/.tools/python-bin"; do
  if [[ -d "$local_bin" ]]; then
    PATH="$local_bin:$PATH"
  fi
done
export PATH

BOARD_PROFILE="v3"
EXPLICIT_PORTS=()
UPLOAD_PORTS=()
COMPILE_ONLY=false
INSTALL_ONLY=false
LIST_PORTS=false
LIST_PORTS_JSON=false
AUTO_PORT=false
ALL_PORTS=false
BAUD=921600
BAUD_OVERRIDE=""
WIFI_SSID_OVERRIDE=""
WIFI_PASSWORD_OVERRIDE=""
DEVICE_NAME_OVERRIDE=""
WIFI_SSID_OVERRIDE_SET=false
WIFI_PASSWORD_OVERRIDE_SET=false
DEVICE_NAME_OVERRIDE_SET=false
BUILD_OVERRIDE_HEADER=""

info()  { printf "\033[1;34m[INFO]\033[0m  %s\n" "$*"; }
ok()    { printf "\033[1;32m[OK]\033[0m    %s\n" "$*"; }
err()   { printf "\033[1;31m[ERROR]\033[0m %s\n" "$*" >&2; }

usage() {
  cat <<'EOF'
upload.sh — Compile & upload PrimusV3.5 receiver build profiles

Usage:
  ./upload.sh --ports
      List likely ESP32 serial ports detected by arduino-cli.

    ./upload.sh --ports-json
      List likely ESP32 serial ports as machine-readable JSON.

  ./upload.sh -v3 --auto
      Compile first, then upload when exactly one ESP32-like serial port is connected.

  ./upload.sh -v2 --all
      Compile once, then upload to every detected ESP32-like serial port.

  ./upload.sh -v1 --compile
      Compile only; do not upload. This is like Arduino IDE Verify.

  ./upload.sh -v2 /dev/cu.usbserial-XXXX /dev/cu.usbserial-YYYY
      Compile once, then upload to one or more explicit serial ports.

  ./upload.sh -v2 -ssid "PrimusRouter" -pw "router-password" --auto
      Compile with WiFi credential overrides for this build, then upload.

    ./upload.sh -v3 --name "StageLeft" --auto
      Compile with a default Art-Net short-name override for this build.

  Behavior:
    Upload commands always compile first, then upload. You do not need to run
    --compile before uploading; use --compile only when you want a verify-only pass.

Flags:
  -v1, -v2, -v3          Select hardware profile. Default: -v3.
  --board v1|v2|v3       Long-form hardware profile selection.
  --auto, -auto            Select the only detected ESP32-like serial port.
  --all, -all              Select every detected ESP32-like serial port.
  --all-ports              Alias for --all.
  --ports, -ports          List likely ESP32 serial ports and exit.
  --list-ports             Alias for --ports.
  --ports-json             List likely ESP32 serial ports as JSON and exit.
  --compile                Compile only; do not upload. Like Arduino IDE Verify.
  --install                Check/install required Arduino libraries and exit.
  -ssid, --ssid <name>     Override DEFAULT_WIFI_SSID for this build.
  -pw, --pw <password>     Override DEFAULT_WIFI_PASSWORD for this build.
  --password <password>    Alias for -pw.
  -name, --name <name>     Override the default device short name for this build.
  --device-name <name>     Alias for --name.
  --baud, --speed <rate>   Override upload speed.
  -h, --help               Show this help.
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
        err "--board requires a value: v1, v2, or v3"
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
    --install)
      INSTALL_ONLY=true
      shift
      ;;
    -ssid|--ssid)
      if [[ $# -lt 2 ]]; then
        err "$1 requires an SSID value"
        exit 1
      fi
      WIFI_SSID_OVERRIDE="$2"
      WIFI_SSID_OVERRIDE_SET=true
      shift 2
      ;;
    -pw|--pw|--password)
      if [[ $# -lt 2 ]]; then
        err "$1 requires a password value"
        exit 1
      fi
      WIFI_PASSWORD_OVERRIDE="$2"
      WIFI_PASSWORD_OVERRIDE_SET=true
      shift 2
      ;;
    -name|--name|--device-name)
      if [[ $# -lt 2 ]]; then
        err "$1 requires a device name"
        exit 1
      fi
      DEVICE_NAME_OVERRIDE="$2"
      DEVICE_NAME_OVERRIDE_SET=true
      shift 2
      ;;
    --baud|--speed)
      if [[ $# -lt 2 || -z "${2:-}" ]]; then
        err "$1 requires a baud rate"
        exit 1
      fi
      BAUD_OVERRIDE="${2:-}"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    -*)
      err "Unknown option: $1"
      usage
      exit 1
      ;;
    *)
      EXPLICIT_PORTS+=("$1")
      shift
      ;;
  esac
done

if [[ "$AUTO_PORT" == true && "$ALL_PORTS" == true ]]; then
  err "Use either --auto or --all, not both."
  exit 1
fi

if [[ "$LIST_PORTS" == true && "$LIST_PORTS_JSON" == true ]]; then
  err "Use either --ports or --ports-json, not both."
  exit 1
fi

if [[ "$AUTO_PORT" == true && ${#EXPLICIT_PORTS[@]} -gt 0 ]]; then
  err "Use either --auto or an explicit serial port, not both."
  exit 1
fi

if [[ "$ALL_PORTS" == true && ${#EXPLICIT_PORTS[@]} -gt 0 ]]; then
  err "Use either --all or explicit serial ports, not both."
  exit 1
fi

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
    BOARD_PROFILE="v3"
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
    err "Expected one of: v1, v2, v3"
    exit 1
    ;;
esac

BAUD="${BAUD_OVERRIDE:-$DEFAULT_BAUD}"
FQBN_WITH_OPTIONS="${FQBN}:UploadSpeed=${BAUD}"

if [[ "$WIFI_SSID_OVERRIDE_SET" == true && -z "$WIFI_SSID_OVERRIDE" ]]; then
  err "SSID override cannot be empty."
  exit 1
fi

if [[ "$WIFI_SSID_OVERRIDE" == *$'\n'* || "$WIFI_SSID_OVERRIDE" == *$'\r'* ]]; then
  err "SSID override cannot contain newlines."
  exit 1
fi

if [[ "$WIFI_PASSWORD_OVERRIDE" == *$'\n'* || "$WIFI_PASSWORD_OVERRIDE" == *$'\r'* ]]; then
  err "Password override cannot contain newlines."
  exit 1
fi

if [[ "$DEVICE_NAME_OVERRIDE_SET" == true && -z "$DEVICE_NAME_OVERRIDE" ]]; then
  err "Device name override cannot be empty."
  exit 1
fi

if [[ "$DEVICE_NAME_OVERRIDE" == *$'\n'* || "$DEVICE_NAME_OVERRIDE" == *$'\r'* ]]; then
  err "Device name override cannot contain newlines."
  exit 1
fi

if [[ ${#DEVICE_NAME_OVERRIDE} -gt 17 ]]; then
  err "Device name override must be 17 characters or fewer."
  exit 1
fi

c_string_literal() {
  local value="$1"
  value=${value//\\/\\\\}
  value=${value//\"/\\\"}
  printf '"%s"' "$value"
}

create_build_override_header() {
  if [[ "$WIFI_SSID_OVERRIDE_SET" != true && "$WIFI_PASSWORD_OVERRIDE_SET" != true && "$DEVICE_NAME_OVERRIDE_SET" != true ]]; then
    return
  fi

  BUILD_OVERRIDE_HEADER="$(mktemp "/tmp/primus_build_overrides.XXXXXX")"
  trap '[[ -n "${BUILD_OVERRIDE_HEADER:-}" ]] && rm -f "$BUILD_OVERRIDE_HEADER"' EXIT

  {
    printf '#pragma once\n'
    if [[ "$DEVICE_NAME_OVERRIDE_SET" == true ]]; then
      printf '#define DEVICE_SHORT_NAME %s\n' "$(c_string_literal "$DEVICE_NAME_OVERRIDE")"
    fi
    if [[ "$WIFI_SSID_OVERRIDE_SET" == true ]]; then
      printf '#define DEFAULT_WIFI_SSID %s\n' "$(c_string_literal "$WIFI_SSID_OVERRIDE")"
    fi
    if [[ "$WIFI_PASSWORD_OVERRIDE_SET" == true ]]; then
      printf '#define DEFAULT_WIFI_PASSWORD %s\n' "$(c_string_literal "$WIFI_PASSWORD_OVERRIDE")"
    fi
  } > "$BUILD_OVERRIDE_HEADER"

  EXTRA_FLAGS="$EXTRA_FLAGS -include $BUILD_OVERRIDE_HEADER"
}

check_cli() {
  if ! command -v arduino-cli &>/dev/null; then
    err "arduino-cli not found. Install Arduino CLI: https://arduino.github.io/arduino-cli/latest/installation/"
    exit 1
  fi
  if ! command -v python3 &>/dev/null; then
    err "python3 not found. It is required to parse arduino-cli board output."
    exit 1
  fi
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


def load_ports():
  proc = subprocess.run(
    ["arduino-cli", "board", "list", "--format", "json"],
    text=True,
    capture_output=True,
  )
  if proc.returncode != 0:
    print(proc.stderr.strip() or "arduino-cli board list failed", file=sys.stderr)
    sys.exit(1)
  try:
    data = json.loads(proc.stdout or "{}")
  except json.JSONDecodeError as exc:
    print(f"Could not parse arduino-cli board list JSON: {exc}", file=sys.stderr)
    sys.exit(1)
  if isinstance(data, dict):
    return data.get("detected_ports", [])
  return data if isinstance(data, list) else []


def port_record(entry):
  port = entry.get("port", {}) if isinstance(entry, dict) else {}
  if not isinstance(port, dict):
    port = {}
  props = port.get("properties", {})
  if not isinstance(props, dict):
    props = {}
  boards = entry.get("matching_boards", []) if isinstance(entry, dict) else []
  if not isinstance(boards, list):
    boards = []

  address = str(port.get("address", ""))
  label = str(port.get("label", address))
  protocol = str(port.get("protocol", ""))
  props_lower = {str(k).lower(): str(v) for k, v in props.items()}
  vid = normalize_vid(props_lower.get("vid") or props_lower.get("vendorid"))

  board_names = []
  board_fqbns = []
  for board in boards:
    if not isinstance(board, dict):
      continue
    board_names.append(str(board.get("name", "")))
    board_fqbns.append(str(board.get("fqbn", "")))

  text_blob = " ".join(
    [address, label, protocol]
    + list(props_lower.values())
    + board_names
    + board_fqbns
  ).lower()

  target_match = any(fqbn.lower() == target_fqbn for fqbn in board_fqbns)

  reasons = []
  if target_match:
    reasons.append("matches selected board")
  elif any(fqbn.lower().startswith("esp32:esp32:") for fqbn in board_fqbns):
    reasons.append("Arduino CLI matched ESP32 board")
  if vid in ESP32_VIDS:
    reasons.append(f"USB VID {vid}")
  for keyword in KEYWORDS:
    if keyword in text_blob:
      reasons.append(keyword)
      break
  if re.search(r"/(cu|tty)\.usb(serial|modem)", address.lower()):
    reasons.append("USB serial path")
  if re.search(r"/dev/tty(usb|acm)\d+", address.lower()):
    reasons.append("USB serial path")

  ignored = any(keyword in text_blob for keyword in IGNORED_KEYWORDS)
  is_serial = protocol == "serial" or bool(address)
  is_candidate = is_serial and bool(reasons) and not ignored

  board_label = ", ".join(name for name in board_names if name) or "unknown board"
  reason_label = ", ".join(dict.fromkeys(reasons)) or "no ESP32 match"
  return {
    "address": address,
    "label": label,
    "protocol": protocol or "unknown",
    "board": board_label,
    "reason": reason_label,
    "candidate": is_candidate,
    "target_match": target_match,
  }


records = [port_record(entry) for entry in load_ports()]
records = [record for record in records if record["address"]]
candidates = [record for record in records if record["candidate"]]
others = [record for record in records if not record["candidate"]]

if mode == "json":
  print(json.dumps({
    "target_fqbn": target_fqbn,
    "ports": records,
    "candidates": candidates,
    "others": others,
  }, separators=(",", ":")))
  sys.exit(0)

if mode == "all":
  if not candidates:
    print("No ESP32-like serial ports were detected.", file=sys.stderr)
    print("Run this script with --ports to inspect ports, or pass ports explicitly.", file=sys.stderr)
    sys.exit(1)
  exact_matches = [record for record in candidates if record["target_match"]]
  selected = exact_matches or candidates
  if exact_matches and len(exact_matches) < len(candidates):
    print("Using only ports that Arduino CLI matched to the selected board profile.", file=sys.stderr)
    print("Other ESP32-like candidates were ignored; use explicit ports to override.", file=sys.stderr)
  elif not exact_matches and len(candidates) > 1:
    print("Arduino CLI did not identify exact selected-board matches.", file=sys.stderr)
    print("Because --all was requested, every ESP32-like candidate will be used.", file=sys.stderr)
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

check_cli

if [[ "$LIST_PORTS" == true ]]; then
  list_ports
  exit 0
fi

if [[ "$LIST_PORTS_JSON" == true ]]; then
  list_ports_json
  exit 0
fi

if [[ "$COMPILE_ONLY" == false && "$INSTALL_ONLY" == false ]]; then
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

if [[ "$COMPILE_ONLY" == false && "$INSTALL_ONLY" == false && ${#UPLOAD_PORTS[@]} -eq 0 ]]; then
  err "No upload ports selected."
  exit 1
fi

if ! arduino-cli core list 2>/dev/null | grep -q "esp32:esp32"; then
  info "Installing ESP32 board core..."
  arduino-cli core install esp32:esp32
fi

install_libs

if [[ "$INSTALL_ONLY" == true ]]; then
  exit 0
fi

create_build_override_header

if [[ "$DEVICE_NAME_OVERRIDE_SET" == true ]]; then
  info "Device name override: $DEVICE_NAME_OVERRIDE"
fi

if [[ "$WIFI_SSID_OVERRIDE_SET" == true ]]; then
  info "WiFi SSID override: $WIFI_SSID_OVERRIDE"
fi
if [[ "$WIFI_PASSWORD_OVERRIDE_SET" == true ]]; then
  info "WiFi password override: set"
fi

if [[ "$COMPILE_ONLY" == true ]]; then
  info "Compiling sketch: $SKETCH_DIR"
else
  info "Compiling sketch before upload: $SKETCH_DIR"
fi
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

if [[ ${#UPLOAD_PORTS[@]} -eq 1 ]]; then
  ok "Using port: ${UPLOAD_PORTS[0]}"
else
  ok "Using ports:"
  for upload_port in "${UPLOAD_PORTS[@]}"; do
    printf "  %s\n" "$upload_port"
  done
fi

for upload_port in "${UPLOAD_PORTS[@]}"; do
  info "Uploading to $upload_port at ${BAUD} baud..."
  arduino-cli upload --fqbn "$FQBN_WITH_OPTIONS" --port "$upload_port" "$SKETCH_DIR"
  ok "Upload complete: $upload_port"
done
echo ""
if [[ ${#UPLOAD_PORTS[@]} -eq 1 ]]; then
  info "Monitor serial output with: arduino-cli monitor -p ${UPLOAD_PORTS[0]} -b $FQBN"
else
  info "Monitor serial output with: arduino-cli monitor -p <port> -b $FQBN"
fi
