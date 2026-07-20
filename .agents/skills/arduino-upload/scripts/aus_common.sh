#!/usr/bin/env bash
# =============================================================================
# aus_common.sh — Reference implementation of the AUS 1.0 specification.
#
# This is a SOURCED library, not a standalone script. A conforming upload
# script sources it, registers one or more board profiles, parses args, and
# calls aus_run:
#
#   #!/usr/bin/env bash
#   set -euo pipefail
#   AUS_SCRIPT_VERSION="1.0.0"
#   SKETCH_DIR="$(cd "$(dirname "$0")" && pwd)/my_sketch"
#   source /path/to/aus_common.sh
#   aus_register_board default --fqbn "esp32:esp32:featheresp32" --libs "Adafruit NeoPixel"
#   aus_parse_args "$@"
#   aus_run "$SKETCH_DIR"
#
# See references/aus-spec.md for the contract this implements, and
# references/common-library.md for full API documentation.
#
# Compatibility: bash 3.2+ (macOS default). No associative arrays, no mapfile,
# no ${var,,}. See aus-spec.md §8.
# =============================================================================

# Guard against double-sourcing.
[[ -n "${AUS_COMMON_SOURCED:-}" ]] && return 0
AUS_COMMON_SOURCED=1

# -----------------------------------------------------------------------------
# Spec version (this library implements AUS 1.0).
# -----------------------------------------------------------------------------
AUS_SPEC_VERSION="1.0"

# -----------------------------------------------------------------------------
# Exit codes (aus-spec.md §6). Exported so user scripts and hooks can reference.
# -----------------------------------------------------------------------------
AUS_EXIT_SUCCESS=0
AUS_EXIT_GENERIC=1
AUS_EXIT_CLI_NOT_FOUND=2
AUS_EXIT_NO_PORTS=3
# shellcheck disable=SC2034 # part of the public exit-code API for callers/hooks
AUS_EXIT_AMBIGUOUS_PORTS=4
AUS_EXIT_UNKNOWN_BOARD=5
AUS_EXIT_COMPILE_FAILED=6
AUS_EXIT_UPLOAD_FAILED=7
AUS_EXIT_LIB_INSTALL_FAILED=8
AUS_EXIT_CORE_INSTALL_FAILED=9
AUS_EXIT_PORT_DETECTION_ERROR=10
AUS_EXIT_EXPECT_FAILED=11

# -----------------------------------------------------------------------------
# Global state. Initialized here so `set -u` never trips on an unset var.
# -----------------------------------------------------------------------------
AUS_SCRIPT_VERSION="${AUS_SCRIPT_VERSION:-0.1.0}"

# Board profile registry (parallel arrays — bash 3.2 has no associative arrays).
AUS_BOARD_NAMES=()
AUS_BOARD_FQBNS=()
AUS_BOARD_DEFINES=()
AUS_BOARD_BAUDS=()
AUS_BOARD_LIBS=()        # each entry: comma-separated lib names (may contain spaces)
AUS_BOARD_DESCS=()
AUS_BOARD_VIDS=()         # each entry: comma-separated 4-hex VIDs
AUS_BOARD_KEYWORDS=()     # each entry: comma-separated keywords
AUS_BOARD_CORE=()         # each entry: packager:arch e.g. esp32:esp32
AUS_BOARD_PACKAGE_URL=()  # each entry: board-manager URL (may be empty)
AUS_BOARD_DEFAULT=""

# Parser output.
AUS_BOARD_PROFILE=""
AUS_FQBN_OVERRIDE=""
AUS_BAUD_OVERRIDE=""
AUS_COMPILE_ONLY=false
AUS_INSTALL_ONLY=false
AUS_LIST_PORTS=false
AUS_LIST_PORTS_JSON=false
AUS_AUTO_PORT=false
AUS_ALL_PORTS=false
AUS_CLEAN=false
AUS_DRY_RUN=false
AUS_VERBOSE=0
AUS_QUIET=false
AUS_EXPLICIT_PORTS=()
AUS_DEFINE_FLAGS=""          # accumulated -D flags (space-separated)
AUS_OVERRIDE_DEFINES=()      # array of "KEY VALUE" pairs for the header
AUS_OVERRIDE_SECRET_KEYS=()  # keys whose value should not be logged
AUS_POST_UPLOAD_HOOK="${AUS_POST_UPLOAD_HOOK:-}"
AUS_EXPECT_REGEX=""
AUS_EXPECT_TIMEOUT=15
AUS_MONITOR_TIMEOUT=0

# Resolved after aus_resolve_board.
AUS_RESOLVED_FQBN=""
AUS_RESOLVED_EXTRA_FLAGS=""
AUS_RESOLVED_BAUD=""
AUS_RESOLVED_LIBS=()
AUS_RESOLVED_VIDS=""
AUS_RESOLVED_KEYWORDS=""
AUS_RESOLVED_CORE=""
AUS_RESOLVED_PACKAGE_URL=""

# Override header state.
AUS_BUILD_OVERRIDE_HEADER=""
AUS_BUILD_ID=""

# CLI path (resolved by aus_find_cli).
AUS_CLI_BIN=""

# =============================================================================
# Logging  (aus-spec.md §7)
# =============================================================================

# Determine color support. Checked at call time so --no-color takes effect.
_aus_use_color() {
  if [[ "${AUS_NO_COLOR:-0}" == 1 ]]; then
    return 1
  fi
  [[ -t 2 ]]
}

aus_info() {
  if [[ "$AUS_QUIET" == true ]]; then return 0; fi
  if _aus_use_color; then
    printf '\033[1;34m[INFO]\033[0m  %s\n' "$*" >&2
  else
    printf '[INFO]  %s\n' "$*" >&2
  fi
}

aus_ok() {
  if [[ "$AUS_QUIET" == true ]]; then return 0; fi
  if _aus_use_color; then
    printf '\033[1;32m[OK]\033[0m    %s\n' "$*" >&2
  else
    printf '[OK]    %s\n' "$*" >&2
  fi
}

aus_warn() {
  if _aus_use_color; then
    printf '\033[1;33m[WARN]\033[0m  %s\n' "$*" >&2
  else
    printf '[WARN]  %s\n' "$*" >&2
  fi
}

aus_error() {
  if _aus_use_color; then
    printf '\033[1;31m[ERROR]\033[0m %s\n' "$*" >&2
  else
    printf '[ERROR] %s\n' "$*" >&2
  fi
}

# Log that a secret-valued override was set, without echoing the value.
# Usage: aus_log_secret_set "WiFi password"
aus_log_secret_set() {
  aus_info "$1 override: set"
}

# Exit with a code and message. Usage: aus_die <code> <message>
aus_die() {
  local code="$1"; shift
  aus_error "$*"
  exit "$code"
}

# =============================================================================
# Board profile registry
# =============================================================================

# Default port-detection signals (ESP32-leaning; override per-profile for others).
# These are the proven values from the PrimusV3 firmware workflow.
_AUS_DEFAULT_VIDS="10c4,1a86,303a,239a,0403"
_AUS_DEFAULT_KEYWORDS="esp32,espressif,cp210,cp210x,ch340,ch910,wch,silicon labs,feather,adafruit"

# Packager → board-manager URL table. Extend via AUS_EXTRA_PACKAGE_URLS.
# Format: "packager|URL" entries separated by newlines.
_AUS_PACKAGE_URLS="esp32|https://espressif.github.io/arduino-esp32/package_esp32_index.json
esp8266|https://arduino.esp8266.com/stable/package_esp8266com_index.json
rp2040|https://github.com/earlephilhower/arduino-pico/releases/download/global/package_rp2040_index.json
adafruit|https://github.com/adafruit/arduino-board-index/zipball/master"

# Register a board profile. Call before aus_parse_args.
# Usage:
#   aus_register_board <name> [--fqbn F] [--define "-DX"] [--baud N]
#                        [--libs "Lib One,Lib Two"] [--desc "text"]
#                        [--vids "1111,2222"] [--keywords "a,b"]
#                        [--core packager:arch] [--package-url URL]
#                        [--default]
# Note: --libs is comma-separated so names with spaces ("Adafruit NeoPixel")
# survive intact.
aus_register_board() {
  local name="$1"; shift
  if [[ -z "$name" ]]; then
    aus_die "$AUS_EXIT_GENERIC" "aus_register_board: profile name is required"
  fi

  local fqbn="" define="" baud="" libs="" desc="" vids="" keywords=""
  local core="" package_url="" is_default=false

  while [[ $# -gt 0 ]]; do
    case "$1" in
      --fqbn)         fqbn="${2:-}"; shift 2 ;;
      --define)       define="${2:-}"; shift 2 ;;
      --baud)         baud="${2:-}"; shift 2 ;;
      --libs)         libs="${2:-}"; shift 2 ;;
      --desc)         desc="${2:-}"; shift 2 ;;
      --vids)         vids="${2:-}"; shift 2 ;;
      --keywords)     keywords="${2:-}"; shift 2 ;;
      --core)         core="${2:-}"; shift 2 ;;
      --package-url)  package_url="${2:-}"; shift 2 ;;
      --default)      is_default=true; shift ;;
      *) aus_die "$AUS_EXIT_GENERIC" "aus_register_board: unknown option: $1" ;;
    esac
  done

  if [[ -z "$fqbn" ]]; then
    aus_die "$AUS_EXIT_GENERIC" "aus_register_board: --fqbn is required for profile '$name'"
  fi

  # Derive core (packager:arch) from FQBN if not supplied.
  if [[ -z "$core" ]]; then
    # FQBN is packager:arch:board[:options] — take first two fields.
    local pkg arch
    IFS=: read -r pkg arch _unused <<< "$fqbn"
    core="${pkg}:${arch}"
  fi

  # Apply defaults for port detection.
  [[ -z "$vids" ]] && vids="$_AUS_DEFAULT_VIDS"
  [[ -z "$keywords" ]] && keywords="$_AUS_DEFAULT_KEYWORDS"
  [[ -z "$baud" ]] && baud="115200"

  # Look up package URL if not supplied.
  if [[ -z "$package_url" ]]; then
    local pkg_only
    IFS=: read -r pkg_only _unused <<< "$core"
    local line
    while IFS= read -r line; do
      if [[ -n "$line" ]]; then
        local entry_pkg="${line%%|*}"
        local entry_url="${line#*|}"
        if [[ "$entry_pkg" == "$pkg_only" ]]; then
          package_url="$entry_url"
          break
        fi
      fi
    done <<< "$_AUS_PACKAGE_URLS"
  fi

  # Append to parallel arrays.
  AUS_BOARD_NAMES+=("$name")
  AUS_BOARD_FQBNS+=("$fqbn")
  AUS_BOARD_DEFINES+=("$define")
  AUS_BOARD_BAUDS+=("$baud")
  AUS_BOARD_LIBS+=("$libs")
  AUS_BOARD_DESCS+=("$desc")
  AUS_BOARD_VIDS+=("$vids")
  AUS_BOARD_KEYWORDS+=("$keywords")
  AUS_BOARD_CORE+=("$core")
  AUS_BOARD_PACKAGE_URL+=("$package_url")

  # First registered board is the default unless --default was given to another.
  if [[ -z "$AUS_BOARD_DEFAULT" ]]; then
    AUS_BOARD_DEFAULT="$name"
  fi
  if [[ "$is_default" == true ]]; then
    AUS_BOARD_DEFAULT="$name"
  fi
}

# Look up a profile by name. Sets _aus_idx on success (0-based index).
# Returns 0 if found, 1 if not.
_aus_lookup_board() {
  local needle="$1"
  local i
  for i in "${!AUS_BOARD_NAMES[@]}"; do
    if [[ "${AUS_BOARD_NAMES[$i]}" == "$needle" ]]; then
      _aus_idx="$i"
      return 0
    fi
  done
  return 1
}

# Resolve the selected board profile into AUS_RESOLVED_* globals.
# Uses AUS_BOARD_PROFILE (or the default), applying --fqbn / --baud overrides.
aus_resolve_board() {
  local profile="${AUS_BOARD_PROFILE:-$AUS_BOARD_DEFAULT}"
  if [[ -z "$profile" ]]; then
    aus_die "$AUS_EXIT_GENERIC" "No board profile registered. Call aus_register_board before aus_run."
  fi

  if ! _aus_lookup_board "$profile"; then
    aus_error "Unknown board profile: $profile"
    local available
    available="$(printf '%s ' "${AUS_BOARD_NAMES[@]}")"
    aus_error "Registered profiles: ${available% }"
    exit "$AUS_EXIT_UNKNOWN_BOARD"
  fi

  local idx="$_aus_idx"
  AUS_BOARD_PROFILE="$profile"
  AUS_RESOLVED_FQBN="${AUS_BOARD_FQBNS[$idx]}"
  AUS_RESOLVED_EXTRA_FLAGS="${AUS_BOARD_DEFINES[$idx]}"
  AUS_RESOLVED_BAUD="${AUS_BOARD_BAUDS[$idx]}"
  AUS_RESOLVED_VIDS="${AUS_BOARD_VIDS[$idx]}"
  AUS_RESOLVED_KEYWORDS="${AUS_BOARD_KEYWORDS[$idx]}"
  AUS_RESOLVED_CORE="${AUS_BOARD_CORE[$idx]}"
  AUS_RESOLVED_PACKAGE_URL="${AUS_BOARD_PACKAGE_URL[$idx]}"

  # Apply overrides.
  if [[ -n "$AUS_FQBN_OVERRIDE" ]]; then
    AUS_RESOLVED_FQBN="$AUS_FQBN_OVERRIDE"
    # Re-derive core from the overridden FQBN (don't change package URL — caller's responsibility).
    local pkg arch
    IFS=: read -r pkg arch _unused <<< "$AUS_RESOLVED_FQBN"
    AUS_RESOLVED_CORE="${pkg}:${arch}"
    aus_info "FQBN override: $AUS_RESOLVED_FQBN"
  fi
  if [[ -n "$AUS_BAUD_OVERRIDE" ]]; then
    AUS_RESOLVED_BAUD="$AUS_BAUD_OVERRIDE"
  fi

  # Accumulate --define flags into EXTRA_FLAGS.
  if [[ -n "$AUS_DEFINE_FLAGS" ]]; then
    AUS_RESOLVED_EXTRA_FLAGS="${AUS_RESOLVED_EXTRA_FLAGS} ${AUS_DEFINE_FLAGS}"
  fi

  # Split libs into an array for install. Libraries are comma-separated so that
  # names containing spaces (e.g. "Adafruit NeoPixel") survive intact.
  local lib_str="${AUS_BOARD_LIBS[$idx]}"
  AUS_RESOLVED_LIBS=()
  if [[ -n "$lib_str" ]]; then
    local old_ifs="$IFS"
    IFS=',' read -r -a AUS_RESOLVED_LIBS <<< "$lib_str"
    IFS="$old_ifs"
    # Trim leading/trailing whitespace from each entry.
    local i
    for i in "${!AUS_RESOLVED_LIBS[@]}"; do
      local entry="${AUS_RESOLVED_LIBS[i]}"
      # Strip leading whitespace
      entry="${entry#"${entry%%[![:space:]]*}"}"
      # Strip trailing whitespace
      entry="${entry%"${entry##*[![:space:]]}"}"
      AUS_RESOLVED_LIBS[i]="$entry"
    done
  fi
}

# =============================================================================
# Toolchain bootstrap  (aus-spec.md §9)
# =============================================================================

# Find arduino-cli on PATH or in conventional locations. Sets AUS_CLI_BIN.
# Returns 0 if found, 1 if not.
aus_find_cli() {
  # 1. Explicit env var.
  if [[ -n "${ARDUINO_CLI:-}" && -x "$ARDUINO_CLI" ]]; then
    AUS_CLI_BIN="$ARDUINO_CLI"
    return 0
  fi

  # 2. AUS_TOOLCHAIN_DIR.
  if [[ -n "${AUS_TOOLCHAIN_DIR:-}" && -x "$AUS_TOOLCHAIN_DIR/bin/arduino-cli" ]]; then
    AUS_CLI_BIN="$AUS_TOOLCHAIN_DIR/bin/arduino-cli"
    return 0
  fi

  # 3. Conventional project-local .tools dir, walking up from the script.
  #    (Resolved by the caller via AUS_REPO_ROOT if set.)
  local repo="${AUS_REPO_ROOT:-}"
  if [[ -n "$repo" && -x "$repo/.tools/arduino-cli/bin/arduino-cli" ]]; then
    AUS_CLI_BIN="$repo/.tools/arduino-cli/bin/arduino-cli"
    return 0
  fi

  # 4. PATH.
  if command -v arduino-cli &>/dev/null; then
    AUS_CLI_BIN="$(command -v arduino-cli)"
    return 0
  fi

  AUS_CLI_BIN=""
  return 1
}

# Verify the CLI is available. If AUS_AUTO_INSTALL_CLI is true and the CLI is
# missing, attempt to bootstrap it. Exit with AUS_EXIT_CLI_NOT_FOUND on failure.
aus_check_cli() {
  if aus_find_cli; then
    # Prepend its directory to PATH so subprocess calls find the same binary.
    local cli_dir
    cli_dir="$(dirname "$AUS_CLI_BIN")"
    case ":${PATH:-}:" in
      *":$cli_dir:"*) ;;
      *) PATH="$cli_dir:$PATH"; export PATH ;;
    esac
    return 0
  fi

  # Try auto-install if enabled (default: on).
  if [[ "${AUS_AUTO_INSTALL_CLI:-1}" == 1 ]]; then
    aus_info "arduino-cli not found; attempting auto-install..."
    if aus_bootstrap_cli; then
      return 0
    fi
  fi

  aus_error "arduino-cli not found."
  aus_error "Install it: https://arduino.github.io/arduino-cli/latest/installation/"
  aus_error "Or set AUS_AUTO_INSTALL_CLI=1 to let this script download it automatically."
  exit "$AUS_EXIT_CLI_NOT_FOUND"
}

# Download arduino-cli into AUS_TOOLCHAIN_DIR (default: .tools/arduino-cli).
# Idempotent: does nothing if the binary already runs.
# Delegates to the standalone aus_bootstrap.sh if available; otherwise inlines.
aus_bootstrap_cli() {
  local target_dir="${AUS_TOOLCHAIN_DIR:-${AUS_REPO_ROOT:-$(pwd)}/.tools/arduino-cli}"
  local target_bin="$target_dir/bin/arduino-cli"

  if [[ -x "$target_bin" ]] && "$target_bin" version &>/dev/null; then
    AUS_CLI_BIN="$target_bin"
    aus_info "arduino-cli already installed at $target_bin"
    return 0
  fi

  # Prefer the standalone installer script if it's alongside this library.
  local bootstrap_script=""
  local lib_dir
  lib_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  if [[ -x "$lib_dir/aus_bootstrap.sh" ]]; then
    bootstrap_script="$lib_dir/aus_bootstrap.sh"
  elif [[ -n "${AUS_REPO_ROOT:-}" && -x "$AUS_REPO_ROOT/.agents/skills/arduino-upload/scripts/aus_bootstrap.sh" ]]; then
    bootstrap_script="$AUS_REPO_ROOT/.agents/skills/arduino-upload/scripts/aus_bootstrap.sh"
  fi

  if [[ -n "$bootstrap_script" ]]; then
    if bash "$bootstrap_script" "$target_dir"; then
      AUS_CLI_BIN="$target_bin"
      return 0
    fi
    return 1
  fi

  # Inline fallback (minimal).
  _aus_inline_bootstrap "$target_dir" "$target_bin"
}

# Minimal inline downloader. Prefers the standalone script; this is a fallback.
_aus_inline_bootstrap() {
  local target_dir="$1"
  local target_bin="$2"

  mkdir -p "$target_dir/bin"

  local os arch
  os="$(uname -s)"
  arch="$(uname -m)"
  local asset_keyword
  case "$os" in
    Darwin)                asset_keyword="macOS" ;;
    Linux)                 asset_keyword="Linux" ;;
    MINGW*|MSYS*|CYGWIN*)  asset_keyword="Windows" ;;
    *) aus_error "Unsupported OS for auto-install: $os"; return 1 ;;
  esac
  case "$arch" in
    arm64|aarch64) asset_keyword="$asset_keyword 64bit" ;;
    x86_64|amd64)  asset_keyword="$asset_keyword 64bit" ;;
    *)             asset_keyword="$asset_keyword 32bit" ;;
  esac

  if ! command -v curl &>/dev/null; then
    aus_error "curl is required to auto-install arduino-cli."
    return 1
  fi

  local api_url="https://api.github.com/repos/arduino/arduino-cli/releases/latest"
  local release_json
  release_json="$(curl -fsSL "$api_url" 2>/dev/null || true)"
  if [[ -z "$release_json" ]]; then
    aus_error "Could not fetch arduino-cli release info from GitHub."
    return 1
  fi

  # Extract the matching asset URL. (python3 is available — we checked.)
  local download_url
  download_url="$(printf '%s' "$release_json" | python3 -c '
import json, sys
data = json.load(sys.stdin)
keyword = sys.argv[1]
for asset in data.get("assets", []):
    name = asset.get("name", "")
    if keyword.lower() in name.lower() and ("arm64" in name.lower() or "64bit" in name.lower() or "x86_64" in name.lower() or "aarch64" in name.lower() or "arm_64" in name.lower()):
        # Prefer exact arch match
        pass
    if keyword.lower() in name.lower() and (name.endswith(".tar.gz") or name.endswith(".zip")):
        print(asset["browser_download_url"])
        break
' "$asset_keyword" 2>/dev/null || true)"

  if [[ -z "$download_url" ]]; then
    aus_error "Could not find arduino-cli asset for: $asset_keyword"
    return 1
  fi

  local tmp_archive
  tmp_archive="$(mktemp)"
  trap 'rm -f "$tmp_archive"' RETURN

  aus_info "Downloading arduino-cli..."
  if ! curl -fsSL "$download_url" -o "$tmp_archive"; then
    aus_error "Download failed."
    return 1
  fi

  if [[ "$download_url" == *.zip ]]; then
    if ! unzip -o "$tmp_archive" -d "$target_dir/bin" arduino-cli 2>/dev/null; then
      unzip -o "$tmp_archive" -d "$target_dir/bin"
    fi
  else
    tar -xzf "$tmp_archive" -C "$target_dir/bin" arduino-cli 2>/dev/null || tar -xzf "$tmp_archive" -C "$target_dir/bin"
  fi

  chmod +x "$target_bin" 2>/dev/null || true
  if "$target_bin" version &>/dev/null; then
    aus_ok "arduino-cli installed: $("$target_bin" version | head -1)"
    AUS_CLI_BIN="$target_bin"
    return 0
  fi
  aus_error "Installed binary does not run."
  return 1
}

# Ensure the board core (packager:arch) is installed. Idempotent.
aus_ensure_core() {
  local core="$1"
  local package_url="$2"

  # Register the board-manager URL if we have one and it's not already there.
  if [[ -n "$package_url" ]]; then
    local existing_urls
    existing_urls="$("$AUS_CLI_BIN" config get board_manager.additional_urls 2>/dev/null || true)"
    if ! echo "$existing_urls" | grep -qF "$package_url"; then
      aus_info "Registering board manager URL: $package_url"
      "$AUS_CLI_BIN" config add board_manager.additional_urls "$package_url" 2>/dev/null || true
      "$AUS_CLI_BIN" core update-index 2>/dev/null || true
    fi
  fi

  if "$AUS_CLI_BIN" core list 2>/dev/null | grep -q "$core"; then
    return 0
  fi

  aus_info "Installing board core: $core"
  if [[ "$AUS_DRY_RUN" == true ]]; then
    return 0
  fi
  if ! "$AUS_CLI_BIN" core install "$core"; then
    aus_error "Failed to install core: $core"
    exit "$AUS_EXIT_CORE_INSTALL_FAILED"
  fi
  aus_ok "Core installed: $core"
}

# Ensure required libraries are installed. Idempotent.
aus_ensure_libs() {
  if [[ ${#AUS_RESOLVED_LIBS[@]} -eq 0 ]]; then
    return 0
  fi

  aus_info "Checking required libraries..."
  local installed
  if [[ "$AUS_DRY_RUN" == true ]]; then
    installed="[]"
  else
    installed="$("$AUS_CLI_BIN" lib list --format json 2>/dev/null || echo "[]")"
  fi

  local lib
  for lib in "${AUS_RESOLVED_LIBS[@]}"; do
    [[ -z "$lib" ]] && continue
    # Match library name flexibly (spaces → dots for grep).
    local lib_pattern
    lib_pattern="$(printf '%s' "$lib" | sed 's/ /./g')"
    if echo "$installed" | grep -qi "$lib_pattern"; then
      aus_ok "Already installed: $lib"
    else
      aus_info "Installing: $lib"
      if [[ "$AUS_DRY_RUN" == true ]]; then
        continue
      fi
      if ! "$AUS_CLI_BIN" lib install "$lib"; then
        aus_error "Failed to install library: $lib"
        exit "$AUS_EXIT_LIB_INSTALL_FAILED"
      fi
      aus_ok "Installed: $lib"
    fi
  done
}

# =============================================================================
# Override header  (aus-spec.md §4)
# =============================================================================

# C-escape a string value for use as a double-quoted C string literal.
# Prints the quoted string (including surrounding quotes).
aus_c_string_literal() {
  local value="$1"
  value="${value//\\/\\\\}"
  value="${value//\"/\\\"}"
  # Also escape newlines (shouldn't happen due to earlier validation, but be safe).
  printf '"%s"' "$value"
}

# Add a #define KEY VALUE to the override header. VALUE is emitted as-is
# (use for integers or pre-quoted C expressions).
# Usage: aus_override_define KEY VALUE
aus_override_define() {
  local key="$1" val="$2"
  AUS_OVERRIDE_DEFINES+=("$key $val")
}

# Add a #define KEY "string" to the override header. VALUE is C-escaped.
# Usage: aus_override_define_cstring KEY VALUE
aus_override_define_cstring() {
  local key="$1" val="$2"
  local escaped
  escaped="$(aus_c_string_literal "$val")"
  AUS_OVERRIDE_DEFINES+=("$key $escaped")
}

# Mark a key as secret so its value is not logged in the "overrides applied" summary.
# Usage: aus_mark_secret KEY
aus_mark_secret() {
  AUS_OVERRIDE_SECRET_KEYS+=("$1")
}

# Generate the override header file if any overrides were supplied.
# Sets AUS_BUILD_OVERRIDE_HEADER and appends -include to AUS_RESOLVED_EXTRA_FLAGS.
aus_create_override_header() {
  if [[ ${#AUS_OVERRIDE_DEFINES[@]} -eq 0 ]]; then
    return 0
  fi

  AUS_BUILD_OVERRIDE_HEADER="$(mktemp "${TMPDIR:-/tmp}/aus_overrides.XXXXXX")"
  AUS_BUILD_ID="$(date +%s)-${RANDOM:-0}-$$"

  {
    printf '#pragma once\n'
    printf '#define AUS_BUILD_ID %s\n' "$(aus_c_string_literal "$AUS_BUILD_ID")"
    local entry
    for entry in "${AUS_OVERRIDE_DEFINES[@]}"; do
      printf '#define %s\n' "$entry"
    done
  } > "$AUS_BUILD_OVERRIDE_HEADER"

  AUS_RESOLVED_EXTRA_FLAGS="$AUS_RESOLVED_EXTRA_FLAGS -include $AUS_BUILD_OVERRIDE_HEADER"
}

# Remove the override header if it was created. Called via EXIT trap.
_aus_cleanup_override_header() {
  if [[ -n "${AUS_BUILD_OVERRIDE_HEADER:-}" && -f "${AUS_BUILD_OVERRIDE_HEADER:-}" ]]; then
    rm -f "$AUS_BUILD_OVERRIDE_HEADER"
  fi
}

# =============================================================================
# Port detection  (aus-spec.md §5)
# =============================================================================

# Internal: run the embedded Python port detector.
# Args: mode (list|json|auto|all)
# Env: AUS_RESOLVED_FQBN, AUS_RESOLVED_VIDS, AUS_RESOLVED_KEYWORDS, etc.
_aus_port_python() {
  local mode="$1"
  AUS_PY_MODE="$mode" \
  AUS_PY_TARGET_FQBN="$AUS_RESOLVED_FQBN" \
  AUS_PY_VIDS="$AUS_RESOLVED_VIDS" \
  AUS_PY_KEYWORDS="$AUS_RESOLVED_KEYWORDS" \
  AUS_PY_SCRIPT_VERSION="$AUS_SCRIPT_VERSION" \
  AUS_PY_SELECTED_BOARD="$AUS_BOARD_PROFILE" \
  AUS_PY_SPEC_VERSION="$AUS_SPEC_VERSION" \
  python3 - "$mode" <<'PY'
import json
import os
import re
import subprocess
import sys

mode = sys.argv[1]
target_fqbn = os.environ.get("AUS_PY_TARGET_FQBN", "").lower()
match_vids = set(
    v.strip().lower() for v in os.environ.get("AUS_PY_VIDS", "").split(",") if v.strip()
)
match_keywords = tuple(
    k.strip().lower() for k in os.environ.get("AUS_PY_KEYWORDS", "").split(",") if k.strip()
)
script_version = os.environ.get("AUS_PY_SCRIPT_VERSION", "0")
selected_board = os.environ.get("AUS_PY_SELECTED_BOARD", "") or None
spec_version = os.environ.get("AUS_PY_SPEC_VERSION", "1.0")

IGNORED_KEYWORDS = ("bluetooth", "debug-console")

MAC_PATH_RE = re.compile(r"/(cu|tty)\.usb(serial|modem|serial.*)")
LINUX_PATH_RE = re.compile(r"/dev/tty(usb|acm)\d+", re.IGNORECASE)


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
        sys.exit(10)
    try:
        data = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError as exc:
        print(f"Could not parse arduino-cli board list JSON: {exc}", file=sys.stderr)
        sys.exit(10)
    if isinstance(data, dict):
        return data.get("detected_ports", []) or data.get("ports", [])
    return data if isinstance(data, list) else []


def port_record(entry):
    port = entry.get("port", {}) if isinstance(entry, dict) else {}
    if not isinstance(port, dict):
        port = {}
    props = port.get("properties", {})
    if not isinstance(props, dict):
        props = {}
    boards = entry.get("matching_boards", []) if isinstance(entry, dict) else port.get("matching_boards", [])
    if not isinstance(boards, list):
        boards = []

    address = str(port.get("address", ""))
    if not address:
        return None
    label = str(port.get("label", address))
    protocol = str(port.get("protocol", "")) or "unknown"
    props_lower = {str(k).lower(): str(v) for k, v in props.items()}

    vid = normalize_vid(props_lower.get("vid") or props_lower.get("vendorid"))
    pid = normalize_vid(props_lower.get("pid") or props_lower.get("productid"))

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
    elif any(fqbn.lower().startswith(target_fqbn.rsplit(":", 1)[0].split(":")[0] + ":") for fqbn in board_fqbns):
        # Same packager:arch family
        pass
    if vid and vid in match_vids:
        reasons.append("USB VID %s" % vid)
    for keyword in match_keywords:
        if keyword in text_blob:
            reasons.append(keyword)
            break
    if MAC_PATH_RE.search(address.lower()):
        reasons.append("USB serial path")
    if LINUX_PATH_RE.search(address):
        reasons.append("USB serial path")

    ignored = any(keyword in text_blob for keyword in IGNORED_KEYWORDS)
    is_serial = protocol == "serial" or bool(address)
    is_candidate = is_serial and bool(reasons) and not ignored

    board_label = ", ".join(name for name in board_names if name) or "unknown board"
    reason_label = ", ".join(dict.fromkeys(reasons)) or "no match"

    return {
        "address": address,
        "label": label,
        "protocol": protocol,
        "vid": vid,
        "pid": pid,
        "matching_fqbn": target_match,
        "candidate": is_candidate,
        "reason": reason_label if is_candidate else "",
        "board": board_label,
    }


records = []
for entry in load_ports():
    rec = port_record(entry)
    if rec is not None:
        records.append(rec)

candidates = [r for r in records if r["candidate"]]
others = [r for r in records if not r["candidate"]]

if mode == "json":
    print(json.dumps({
        "spec_version": spec_version,
        "script_version": script_version,
        "target_fqbn": target_fqbn,
        "selected_board": selected_board,
        "ports": records,
        "candidates": candidates,
        "others": others,
    }, separators=(",", ":")))
    sys.exit(0)

if mode == "all":
    if not candidates:
        print("No matching serial ports were detected.", file=sys.stderr)
        print("Run with --ports to inspect, or pass a port explicitly.", file=sys.stderr)
        sys.exit(3)
    exact = [r for r in candidates if r["matching_fqbn"]]
    selected = exact if exact else candidates
    if exact and len(exact) < len(candidates):
        print("Using only ports that match the selected board exactly.", file=sys.stderr)
        print("Other candidates were ignored; pass explicit ports to override.", file=sys.stderr)
    elif not exact and len(candidates) > 1:
        print("Board FQBN did not match any port exactly.", file=sys.stderr)
        print("Because --all was requested, every candidate will be used.", file=sys.stderr)
    for r in selected:
        print(r["address"])
    sys.exit(0)

if mode == "auto":
    if len(candidates) == 1:
        print(candidates[0]["address"])
        sys.exit(0)
    if not candidates:
        print("No matching serial ports were detected.", file=sys.stderr)
        sys.exit(3)
    print("Multiple matching serial ports were detected:", file=sys.stderr)
    for r in candidates:
        print("  %s  (%s)" % (r["address"], r["reason"]), file=sys.stderr)
    print("Use --all to flash every candidate, or pass a port explicitly.", file=sys.stderr)
    sys.exit(4)

# mode == "list" (human-readable)
if candidates:
    print("Candidate serial ports:")
    for r in candidates:
        print("  %s" % r["address"])
        print("    Board:  %s" % r["board"])
        print("    Reason: %s" % r["reason"])
else:
    print("No matching serial ports detected.")

if others:
    print("")
    print("Other serial ports (not selected by --auto):")
    for r in others:
        print("  %s  (%s)" % (r["address"], r["protocol"]))
PY
}

# Human-readable port list. Prints to stdout, exits 0.
aus_list_ports() {
  _aus_require_python3
  _aus_port_python list
}

# Machine-readable port JSON (§5). Single line to stdout, exits 0.
aus_list_ports_json() {
  _aus_require_python3
  _aus_port_python json
}

# Detect exactly one port. Prints address to stdout. Exits 3 (none) or 4 (many).
aus_detect_port() {
  _aus_require_python3
  _aus_port_python auto
}

# Detect all candidate ports. Prints one address per line. Exits 3 if none.
aus_detect_all_ports() {
  _aus_require_python3
  _aus_port_python all
}

_aus_require_python3() {
  if ! command -v python3 &>/dev/null; then
    aus_error "python3 is required for port detection but was not found."
    aus_error "Install python3, or pass an explicit port path."
    exit "$AUS_EXIT_PORT_DETECTION_ERROR"
  fi
}

# =============================================================================
# Argument parser  (aus-spec.md §3)
# =============================================================================

# User-overridable hook for project-specific flags.
# Receives: $1 = flag, $2 = next-arg (may be empty).
# Returns: 0 if handled (set AUS_CUSTOM_SHIFT to 1 or 2), 1 if not recognized.
# Default implementation: recognize nothing.
AUS_CUSTOM_SHIFT=2
aus_custom_arg() {
  return 1
}

aus_parse_args() {
  while [[ $# -gt 0 ]]; do
    case "$1" in
      -h|--help)
        aus_print_usage
        exit "$AUS_EXIT_SUCCESS"
        ;;
      --version)
        printf '%s (AUS %s)\n' "$AUS_SCRIPT_VERSION" "$AUS_SPEC_VERSION"
        exit "$AUS_EXIT_SUCCESS"
        ;;
      --board)
        _aus_require_value "$1" "${2:-}"
        AUS_BOARD_PROFILE="$2"
        shift 2
        ;;
      --fqbn)
        _aus_require_value "$1" "${2:-}"
        AUS_FQBN_OVERRIDE="$2"
        shift 2
        ;;
      --baud)
        _aus_require_value "$1" "${2:-}"
        if ! [[ "$2" =~ ^[0-9]+$ ]]; then
          aus_die "$AUS_EXIT_GENERIC" "--baud requires a numeric value, got: $2"
        fi
        AUS_BAUD_OVERRIDE="$2"
        shift 2
        ;;
      --compile)
        AUS_COMPILE_ONLY=true
        shift
        ;;
      --install)
        AUS_INSTALL_ONLY=true
        shift
        ;;
      --auto|-auto)
        AUS_AUTO_PORT=true
        shift
        ;;
      --all|-all|--all-ports)
        AUS_ALL_PORTS=true
        shift
        ;;
      --ports|-ports|--list-ports|--detect-ports)
        AUS_LIST_PORTS=true
        shift
        ;;
      --ports-json|--list-ports-json)
        AUS_LIST_PORTS_JSON=true
        shift
        ;;
      --clean)
        AUS_CLEAN=true
        shift
        ;;
      --dry-run)
        AUS_DRY_RUN=true
        shift
        ;;
      --no-color)
        AUS_NO_COLOR=1
        shift
        ;;
      -v|--verbose)
        AUS_VERBOSE=$((AUS_VERBOSE + 1))
        shift
        ;;
      --quiet)
        AUS_QUIET=true
        shift
        ;;
      --define)
        _aus_require_value "$1" "${2:-}"
        if ! [[ "$2" == *=* ]]; then
          aus_die "$AUS_EXIT_GENERIC" "--define requires KEY=VAL form, got: $2"
        fi
        AUS_DEFINE_FLAGS="${AUS_DEFINE_FLAGS} -D${2}"
        shift 2
        ;;
      --define-header)
        _aus_require_value "$1" "${2:-}"
        if ! [[ "$2" == *=* ]]; then
          aus_die "$AUS_EXIT_GENERIC" "--define-header requires KEY=VAL form, got: $2"
        fi
        local _key="${2%%=*}"
        local _val="${2#*=}"
        aus_override_define "$_key" "$_val"
        shift 2
        ;;
      --post-upload-hook)
        _aus_require_value "$1" "${2:-}"
        AUS_POST_UPLOAD_HOOK="$2"
        shift 2
        ;;
      --expect)
        _aus_require_value "$1" "${2:-}"
        AUS_EXPECT_REGEX="$2"
        shift 2
        ;;
      --expect-timeout)
        _aus_require_value "$1" "${2:-}"
        AUS_EXPECT_TIMEOUT="$2"
        shift 2
        ;;
      --monitor)
        # Handled by aus_run — just marks intent. Optional timeout as value.
        if [[ $# -ge 2 && "$2" =~ ^[0-9]+$ ]]; then
          AUS_MONITOR_TIMEOUT="$2"
          shift 2
        else
          shift
        fi
        ;;
      --)
        shift
        while [[ $# -gt 0 ]]; do
          AUS_EXPLICIT_PORTS+=("$1")
          shift
        done
        ;;
      -*)
        # Try the user's custom-arg hook.
        AUS_CUSTOM_SHIFT=2
        if aus_custom_arg "$1" "${2:-}"; then
          shift "$AUS_CUSTOM_SHIFT"
        else
          aus_error "Unknown option: $1"
          aus_print_usage
          exit "$AUS_EXIT_GENERIC"
        fi
        ;;
      *)
        AUS_EXPLICIT_PORTS+=("$1")
        shift
        ;;
    esac
  done

  _aus_check_mutex
}

# Verify a flag has a value, or die.
_aus_require_value() {
  local flag="$1" val="${2:-}"
  if [[ -z "$val" ]]; then
    aus_die "$AUS_EXIT_GENERIC" "$flag requires a value"
  fi
}

# Enforce mutual-exclusion rules (§3.5).
_aus_check_mutex() {
  if [[ "$AUS_AUTO_PORT" == true && "$AUS_ALL_PORTS" == true ]]; then
    aus_die "$AUS_EXIT_GENERIC" "Use either --auto or --all, not both."
  fi
  if [[ "$AUS_LIST_PORTS" == true && "$AUS_LIST_PORTS_JSON" == true ]]; then
    aus_die "$AUS_EXIT_GENERIC" "Use either --ports or --ports-json, not both."
  fi
  if [[ "$AUS_AUTO_PORT" == true && ${#AUS_EXPLICIT_PORTS[@]} -gt 0 ]]; then
    aus_die "$AUS_EXIT_GENERIC" "Use either --auto or an explicit port, not both."
  fi
  if [[ "$AUS_ALL_PORTS" == true && ${#AUS_EXPLICIT_PORTS[@]} -gt 0 ]]; then
    aus_die "$AUS_EXIT_GENERIC" "Use either --all or explicit ports, not both."
  fi
  if [[ "$AUS_INSTALL_ONLY" == true ]]; then
    if [[ "$AUS_AUTO_PORT" == true || "$AUS_ALL_PORTS" == true || ${#AUS_EXPLICIT_PORTS[@]} -gt 0 ]]; then
      aus_die "$AUS_EXIT_GENERIC" "--install does not use a port; remove --auto/--all/port arguments."
    fi
  fi
}

# Default usage. User scripts may override by defining aus_print_usage themselves
# BEFORE calling aus_parse_args. This default lists the standard flags.
aus_print_usage() {
  cat <<'EOF'
Usage: <script> [--board PROFILE] [--fqbn FQBN] [--baud N]
                 {--compile | --install | --auto | --all | --ports | --ports-json}
                 [--define KEY=VAL] [--define-header KEY=VAL]
                 [--post-upload-hook PATH] [--expect REGEX]
                 [--clean] [--dry-run] [--no-color] [-v | --verbose] [--quiet]
                 [PORT ...]

Standard flags (AUS 1.0):
  --board PROFILE         Select a board profile by name.
  --fqbn FQBN             Override the FQBN entirely (advanced).
  --baud N                Override the upload speed.
  --compile               Compile only; do not flash.
  --install               Install cores + libraries, then exit.
  --auto                  Detect and use exactly one port (exits 4 if ambiguous).
  --all                   Flash every candidate port.
  --ports                 List candidate ports (human-readable) and exit.
  --ports-json            List candidate ports as JSON and exit.
  --define KEY=VAL        Add -DKEY=VAL to compiler flags.
  --define-header KEY=VAL Add #define KEY VAL to the override header.
  --post-upload-hook PATH Run PATH after each successful upload.
  --expect REGEX          After upload, assert a serial line matches REGEX.
  --expect-timeout N      Timeout for --expect (default 15s).
  --clean                 Wipe build cache before compiling.
  --dry-run               Print commands; execute nothing.
  --no-color              Disable ANSI color in logs.
  -v, --verbose           Increase verbosity.
  --quiet                 Errors only.
  -h, --help              Show this help.
  --version               Print version and exit.

Positional arguments are treated as explicit serial port paths.
EOF
}

# =============================================================================
# Build & upload
# =============================================================================

# Run arduino-cli compile with the resolved profile + overrides.
# Sets the EXIT trap to clean up the override header.
aus_compile() {
  local sketch_dir="$1"

  # Register cleanup for the override header.
  if [[ -z "${_AUS_TRAP_SET:-}" ]]; then
    trap '_aus_cleanup_override_header' EXIT
    _AUS_TRAP_SET=1
  fi

  aus_create_override_header

  local fqbn_with_options="${AUS_RESOLVED_FQBN}:UploadSpeed=${AUS_RESOLVED_BAUD}"

  if [[ "$AUS_COMPILE_ONLY" == true ]]; then
    aus_info "Compiling (verify-only): $sketch_dir"
  else
    aus_info "Compiling before upload: $sketch_dir"
  fi
  aus_info "Board profile: $AUS_BOARD_PROFILE"
  aus_info "FQBN: $fqbn_with_options"
  if [[ -n "$AUS_BUILD_OVERRIDE_HEADER" ]]; then
    aus_info "Override header: $AUS_BUILD_OVERRIDE_HEADER"
    _aus_log_overrides
  fi

  local compile_cmd=(
    "$AUS_CLI_BIN" compile
    --fqbn "$fqbn_with_options"
    --build-property "compiler.cpp.extra_flags=$AUS_RESOLVED_EXTRA_FLAGS"
    --build-property "compiler.c.extra_flags=$AUS_RESOLVED_EXTRA_FLAGS"
    --warnings default
  )
  if [[ "$AUS_CLEAN" == true ]]; then
    compile_cmd+=(--clean)
  fi
  if [[ "$AUS_VERBOSE" -gt 0 ]]; then
    compile_cmd+=(--verbose)
  fi
  compile_cmd+=("$sketch_dir")

  if [[ "$AUS_DRY_RUN" == true ]]; then
    aus_info "[dry-run] ${compile_cmd[*]}"
    return 0
  fi

  if ! "${compile_cmd[@]}"; then
    aus_error "Compilation failed."
    exit "$AUS_EXIT_COMPILE_FAILED"
  fi
  aus_ok "Compilation successful"
}

# Log which overrides were applied, redacting secrets.
_aus_log_overrides() {
  local entry key val is_secret
  for entry in "${AUS_OVERRIDE_DEFINES[@]}"; do
    key="${entry%% *}"
    val="${entry#* }"
    is_secret=false
    local s
    for s in "${AUS_OVERRIDE_SECRET_KEYS[@]:-}"; do
      [[ "$s" == "$key" ]] && is_secret=true && break
    done
    if [[ "$is_secret" == true ]]; then
      aus_info "  $key: <set>"
    else
      aus_info "  $entry"
    fi
  done
}

# Upload to one port. Assumes compile already succeeded.
aus_upload_one() {
  local sketch_dir="$1" port="$2"
  local fqbn_with_options="${AUS_RESOLVED_FQBN}:UploadSpeed=${AUS_RESOLVED_BAUD}"

  aus_info "Uploading to $port at ${AUS_RESOLVED_BAUD} baud..."
  local upload_cmd=(
    "$AUS_CLI_BIN" upload
    --fqbn "$fqbn_with_options"
    --port "$port"
    "$sketch_dir"
  )

  if [[ "$AUS_DRY_RUN" == true ]]; then
    aus_info "[dry-run] ${upload_cmd[*]}"
    return 0
  fi

  if ! "${upload_cmd[@]}"; then
    aus_error "Upload failed: $port"
    exit "$AUS_EXIT_UPLOAD_FAILED"
  fi
  aus_ok "Upload complete: $port"
}

# =============================================================================
# Serial & testing hooks  (aus-spec.md §10)
# =============================================================================

# Portable timeout: runs a command with a wall-clock limit.
# Tries `timeout` (GNU coreutils / Linux), then `gtimeout` (brew coreutils on
# macOS), then falls back to a pure-bash background-job implementation.
# Usage: _aus_run_with_timeout <seconds> <command...>
# Returns the command's exit code, or 124 on timeout.
_aus_run_with_timeout() {
  local seconds="$1"; shift
  if [[ "$seconds" -le 0 ]] 2>/dev/null; then
    "$@"
    return $?
  fi
  # Prefer the real tools when available.
  if command -v timeout &>/dev/null; then
    timeout "$seconds" "$@"
    return $?
  fi
  if command -v gtimeout &>/dev/null; then
    gtimeout "$seconds" "$@"
    return $?
  fi
  # Pure-bash fallback: run in background, kill on timeout.
  # Sends SIGTERM first, then SIGKILL after 2s if still alive.
  local tmpdir
  tmpdir="$(mktemp -d)"
  local pid status_file
  status_file="$tmpdir/status"
  echo "124" > "$status_file"  # default: timed out
  (
    "$@"
    echo "$?" > "$status_file"
  ) &
  pid=$!
  local monitor=0
  while (( monitor < seconds )); do
    if ! kill -0 "$pid" 2>/dev/null; then
      break  # command finished
    fi
    sleep 1
    monitor=$((monitor + 1))
  done
  if kill -0 "$pid" 2>/dev/null; then
    # Still running — timed out. Kill it.
    kill -TERM "$pid" 2>/dev/null || true
    sleep 2
    kill -KILL "$pid" 2>/dev/null || true
    wait "$pid" 2>/dev/null || true
  else
    wait "$pid" 2>/dev/null || true
  fi
  local result
  result="$(cat "$status_file" 2>/dev/null || echo 1)"
  rm -rf "$tmpdir"
  return "$result"
}

# Run arduino-cli monitor on a port, optionally with a timeout.
# Lines are printed to stdout as they arrive.
aus_monitor() {
  local port="$1" to_secs="${2:-$AUS_MONITOR_TIMEOUT}"
  local config="baudrate=${AUS_RESOLVED_BAUD}"
  if [[ "$to_secs" -gt 0 ]] 2>/dev/null; then
    _aus_run_with_timeout "$to_secs" "$AUS_CLI_BIN" monitor -p "$port" -c "$config" 2>/dev/null || true
  else
    "$AUS_CLI_BIN" monitor -p "$port" -c "$config"
  fi
}

# Capture serial output to a file.
aus_capture() {
  local port="$1" outfile="$2" to_secs="${3:-$AUS_MONITOR_TIMEOUT}"
  aus_monitor "$port" "$to_secs" > "$outfile"
}

# Assert that a serial line matching REGEX appears within TIMEOUT seconds.
# Returns 0 on match, 1 on timeout (caller conventionally exits 11).
#
# Implementation: stream the monitor output to a temp file in the background
# while a watcher greps each new line for the regex. This avoids the
# subshell/PIPESTATUS fragility of a pipe-based approach and works portably
# across macOS (no `timeout` cmd) and Linux.
aus_expect() {
  local port="$1" regex="$2" to_secs="${3:-$AUS_EXPECT_TIMEOUT}"
  aus_info "Expecting serial output matching /$regex/ within ${to_secs}s..."
  local config="baudrate=${AUS_RESOLVED_BAUD}"

  local tmpdir
  tmpdir="$(mktemp -d)"
  local capture_file="$tmpdir/serial.log"
  local monitor_pid=""

  # Start the monitor in the background, writing to the capture file.
  "$AUS_CLI_BIN" monitor -p "$port" -c "$config" > "$capture_file" 2>/dev/null &
  monitor_pid=$!

  # Watch the file for the regex until timeout or monitor exits.
  local elapsed=0
  local matched=false
  while (( elapsed < to_secs )); do
    if ! kill -0 "$monitor_pid" 2>/dev/null; then
      # Monitor exited on its own. Check whatever it captured.
      if grep -qE "$regex" "$capture_file" 2>/dev/null; then
        matched=true
      fi
      break
    fi
    if grep -qE "$regex" "$capture_file" 2>/dev/null; then
      matched=true
      break
    fi
    sleep 1
    elapsed=$((elapsed + 1))
  done

  # Clean up the monitor process if still running.
  if kill -0 "$monitor_pid" 2>/dev/null; then
    kill -TERM "$monitor_pid" 2>/dev/null || true
    sleep 1
    kill -KILL "$monitor_pid" 2>/dev/null || true
  fi
  wait "$monitor_pid" 2>/dev/null || true

  # Echo what we captured (helps debugging on failure).
  if [[ -s "$capture_file" ]]; then
    # Print up to the first 20 lines so callers see what the board said.
    head -20 "$capture_file" >&2
  fi

  rm -rf "$tmpdir"

  if [[ "$matched" == true ]]; then
    aus_ok "Serial expectation matched."
    return 0
  fi
  aus_error "Serial expectation not matched within ${to_secs}s."
  return 1
}

# Run the post-upload hook if one is configured.
# Args: port fqbn profile
aus_run_post_upload_hook() {
  local port="$1" fqbn="$2" profile="$3"
  if [[ -z "$AUS_POST_UPLOAD_HOOK" ]]; then
    return 0
  fi
  if [[ ! -x "$AUS_POST_UPLOAD_HOOK" ]] && ! command -v "$AUS_POST_UPLOAD_HOOK" &>/dev/null; then
    # Try bash explicit invocation for non-executable scripts.
    if [[ -f "$AUS_POST_UPLOAD_HOOK" ]]; then
      aus_info "Running post-upload hook: $AUS_POST_UPLOAD_HOOK"
      if ! bash "$AUS_POST_UPLOAD_HOOK" "$port" "$fqbn" "$profile"; then
        aus_error "Post-upload hook failed."
        exit "$AUS_EXIT_GENERIC"
      fi
      return 0
    fi
    aus_error "Post-upload hook not found: $AUS_POST_UPLOAD_HOOK"
    exit "$AUS_EXIT_GENERIC"
  fi
  aus_info "Running post-upload hook: $AUS_POST_UPLOAD_HOOK"
  if ! "$AUS_POST_UPLOAD_HOOK" "$port" "$fqbn" "$profile"; then
    aus_error "Post-upload hook failed."
    exit "$AUS_EXIT_GENERIC"
  fi
}

# =============================================================================
# Top-level orchestrator
# =============================================================================

# Main entry point. Call after aus_register_board + aus_parse_args.
# Usage: aus_run <sketch_dir>
aus_run() {
  local sketch_dir="${1:-${AUS_SKETCH_DIR:-}}"
  if [[ -z "$sketch_dir" ]]; then
    aus_die "$AUS_EXIT_GENERIC" "aus_run: sketch directory is required (pass as arg or set AUS_SKETCH_DIR)."
  fi
  if [[ ! -d "$sketch_dir" ]]; then
    aus_die "$AUS_EXIT_GENERIC" "Sketch directory not found: $sketch_dir"
  fi

  # --- Port-listing modes (no board resolution needed for --ports-json,
  #     but we resolve anyway so target_fqbn is accurate). ---
  aus_resolve_board

  if [[ "$AUS_LIST_PORTS_JSON" == true ]]; then
    aus_check_cli
    aus_list_ports_json
    exit "$AUS_EXIT_SUCCESS"
  fi
  if [[ "$AUS_LIST_PORTS" == true ]]; then
    aus_check_cli
    aus_list_ports
    exit "$AUS_EXIT_SUCCESS"
  fi

  # --- Toolchain. ---
  aus_check_cli

  # --- Install-only mode. ---
  if [[ "$AUS_INSTALL_ONLY" == true ]]; then
    aus_ensure_core "$AUS_RESOLVED_CORE" "$AUS_RESOLVED_PACKAGE_URL"
    aus_ensure_libs
    aus_ok "Install complete for profile: $AUS_BOARD_PROFILE"
    exit "$AUS_EXIT_SUCCESS"
  fi

  # --- Determine upload ports (unless compile-only). ---
  local upload_ports=()
  if [[ "$AUS_COMPILE_ONLY" == false ]]; then
    if [[ "$AUS_ALL_PORTS" == true ]]; then
      aus_info "Detecting all candidate ports..."
      local detected
      if ! detected="$(aus_detect_all_ports)"; then
        exit "$?"
      fi
      while IFS= read -r line; do
        [[ -n "$line" ]] && upload_ports+=("$line")
      done <<< "$detected"
    elif [[ ${#AUS_EXPLICIT_PORTS[@]} -gt 0 ]]; then
      upload_ports=("${AUS_EXPLICIT_PORTS[@]}")
    else
      if [[ "$AUS_AUTO_PORT" == true ]]; then
        aus_info "Auto-detecting port..."
      else
        aus_info "No port supplied; using auto-detect. Use --ports to inspect or pass a port explicitly."
      fi
      local detected
      if ! detected="$(aus_detect_port)"; then
        exit "$?"
      fi
      upload_ports+=("$detected")
    fi
    if [[ ${#upload_ports[@]} -eq 0 ]]; then
      aus_die "$AUS_EXIT_NO_PORTS" "No upload ports selected."
    fi
  fi

  # --- Ensure toolchain installed (cores + libs). ---
  aus_ensure_core "$AUS_RESOLVED_CORE" "$AUS_RESOLVED_PACKAGE_URL"
  aus_ensure_libs

  # --- Compile. ---
  aus_compile "$sketch_dir"
  if [[ "$AUS_COMPILE_ONLY" == true ]]; then
    exit "$AUS_EXIT_SUCCESS"
  fi

  # --- Upload. ---
  if [[ ${#upload_ports[@]} -eq 1 ]]; then
    aus_ok "Using port: ${upload_ports[0]}"
  else
    aus_ok "Using ${#upload_ports[@]} ports:"
    local p
    for p in "${upload_ports[@]}"; do printf '  %s\n' "$p" >&2; done
  fi

  local port
  for port in "${upload_ports[@]}"; do
    aus_upload_one "$sketch_dir" "$port"

    # Post-upload assertion / hook.
    if [[ -n "$AUS_EXPECT_REGEX" ]]; then
      if ! aus_expect "$port" "$AUS_EXPECT_REGEX" "$AUS_EXPECT_TIMEOUT"; then
        exit "$AUS_EXIT_EXPECT_FAILED"
      fi
    fi
    aus_run_post_upload_hook "$port" "$AUS_RESOLVED_FQBN" "$AUS_BOARD_PROFILE"
  done

  # --- Hint for serial monitoring. ---
  echo "" >&2
  if [[ ${#upload_ports[@]} -eq 1 ]]; then
    aus_info "Monitor serial: $AUS_CLI_BIN monitor -p ${upload_ports[0]} -c baudrate=${AUS_RESOLVED_BAUD}"
  else
    aus_info "Monitor serial: $AUS_CLI_BIN monitor -p <port> -c baudrate=${AUS_RESOLVED_BAUD}"
  fi

  exit "$AUS_EXIT_SUCCESS"
}
