#!/usr/bin/env bash
# =============================================================================
# aus_bootstrap.sh — Standalone installer for arduino-cli.
#
# Downloads the latest arduino-cli release from GitHub into a project-local
# directory (default: .tools/arduino-cli). Idempotent: does nothing if the
# binary already exists and runs.
#
# This is the standalone form of the auto-install logic in aus_common.sh.
# Conforming scripts MAY delegate to this script, or inline their own
# equivalent (see aus-spec.md §9.1).
#
# Usage:
#   ./aus_bootstrap.sh                       # installs to ./.tools/arduino-cli
#   ./aus_bootstrap.sh /path/to/target       # installs to /path/to/target
#   ./aus_bootstrap.sh --version 1.0.0       # pin a specific version
#
# Exit codes: 0 = installed or already present; 1 = failure.
# =============================================================================
set -euo pipefail

# Colors.
if [[ -t 2 ]]; then
  C_BLUE='\033[1;34m'; C_GREEN='\033[1;32m'; C_RED='\033[1;31m'; C_RESET='\033[0m'
else
  C_BLUE=''; C_GREEN=''; C_RED=''; C_RESET=''
fi
info()  { printf "${C_BLUE}[INFO]${C_RESET} %s\n" "$*" >&2; }
ok()    { printf "${C_GREEN}[OK]${C_RESET}    %s\n" "$*" >&2; }
err()   { printf "${C_RED}[ERROR]${C_RESET} %s\n" "$*" >&2; }

# --- Parse args. ---
TARGET_DIR="${AUS_TOOLCHAIN_DIR:-./.tools/arduino-cli}"
PINNED_VERSION=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --version) PINNED_VERSION="$2"; shift 2 ;;
    -h|--help)
      cat <<EOF
aus_bootstrap.sh — install arduino-cli locally.

Usage:
  $0 [target-dir] [--version X.Y.Z]

Default target: ./.tools/arduino-cli (or \$AUS_TOOLCHAIN_DIR if set).
Default version: latest GitHub release (unless --version pins one).
EOF
      exit 0
      ;;
    -*) err "Unknown option: $1"; exit 1 ;;
    *) TARGET_DIR="$1"; shift ;;
  esac
done

TARGET_BIN="$TARGET_DIR/bin/arduino-cli"

# --- Already installed? ---
if [[ -x "$TARGET_BIN" ]] && "$TARGET_BIN" version &>/dev/null; then
  installed_version="$("$TARGET_BIN" version 2>/dev/null | head -1 || echo "unknown")"
  ok "arduino-cli already installed: $TARGET_BIN"
  ok "Version: $installed_version"
  exit 0
fi

# --- Dependencies. ---
if ! command -v curl &>/dev/null; then
  err "curl is required. Install it first."
  exit 1
fi
if ! command -v python3 &>/dev/null; then
  err "python3 is required (to parse the GitHub release API)."
  exit 1
fi

# --- Detect platform. ---
os="$(uname -s)"
arch="$(uname -m)"
case "$os" in
  Darwin)              platform="macOS" ;;
  Linux)               platform="Linux" ;;
  MINGW*|MSYS*|CYGWIN*) platform="Windows" ;;
  *) err "Unsupported OS: $os"; exit 1 ;;
esac
case "$arch" in
  arm64|aarch64) arch_label="64bit" ;;
  x86_64|amd64)  arch_label="64bit" ;;
  i386|i686)     arch_label="32bit" ;;
  armv7l)        arch_label="arm" ;;
  *) err "Unsupported architecture: $arch"; exit 1 ;;
esac

# --- Fetch the release info. ---
if [[ -n "$PINNED_VERSION" ]]; then
  api_url="https://api.github.com/repos/arduino/arduino-cli/releases/tags/v${PINNED_VERSION#v}"
  info "Fetching arduino-cli v$PINNED_VERSION..."
else
  api_url="https://api.github.com/repos/arduino/arduino-cli/releases/latest"
  info "Fetching latest arduino-cli release..."
fi

release_json="$(curl -fsSL "$api_url" 2>/dev/null || true)"
if [[ -z "$release_json" ]]; then
  err "Could not fetch release info from GitHub."
  err "URL: $api_url"
  exit 1
fi

# --- Pick the matching asset. ---
# Asset naming convention: Arduino-CLI-<version>-<Platform>-<arch>.tar.gz
# e.g. arduino-cli_1.0.4_macOS_64bit.tar.gz, arduino-cli_0.35.3_Linux_64bit.tar.gz
download_url="$(printf '%s' "$release_json" | python3 -c '
import json, sys, re
data = json.loads(sys.stdin.read())
platform = sys.argv[1]
arch_label = sys.argv[2]
assets = data.get("assets", [])
candidates = []
for asset in assets:
    name = asset.get("name", "").lower()
    if platform.lower() not in name:
        continue
    if not (arch_label in name or "arm64" in name or "aarch64" in name):
        continue
    if not (name.endswith(".tar.gz") or name.endswith(".zip")):
        continue
    candidates.append((asset.get("browser_download_url"), name))
if not candidates:
    sys.exit(1)
# Prefer tar.gz over zip if both exist.
for url, name in candidates:
    if name.endswith(".tar.gz"):
        print(url)
        sys.exit(0)
print(candidates[0][0])
' "$platform" "$arch_label" 2>/dev/null || true)"

if [[ -z "$download_url" ]]; then
  err "Could not find an arduino-cli asset for $platform $arch ($arch_label)."
  err "Available assets:"
  printf '%s' "$release_json" | python3 -c '
import json, sys
data = json.loads(sys.stdin.read())
for a in data.get("assets", []):
    print("  " + a.get("name", ""), file=sys.stderr)
' 2>&1 | head -20 >&2
  exit 1
fi

# --- Download. ---
tmp_archive="$(mktemp)"
trap 'rm -f "$tmp_archive"' EXIT

info "Downloading: $download_url"
if ! curl -fSL "$download_url" -o "$tmp_archive"; then
  err "Download failed."
  exit 1
fi

# --- Extract. ---
mkdir -p "$TARGET_DIR/bin"
info "Extracting to $TARGET_DIR/bin/..."
case "$download_url" in
  *.tar.gz)
    # The archive contains a single "arduino-cli" binary at the root.
    if ! tar -xzf "$tmp_archive" -C "$TARGET_DIR/bin" arduino-cli 2>/dev/null; then
      # Some archives nest the binary under a versioned directory; fall back to
      # extracting everything then moving the binary into place.
      tar -xzf "$tmp_archive" -C "$TARGET_DIR/bin"
      found_bin="$(find "$TARGET_DIR/bin" -name arduino-cli -type f | head -1)"
      if [[ -n "$found_bin" && "$found_bin" != "$TARGET_BIN" ]]; then
        mv "$found_bin" "$TARGET_BIN"
      fi
    fi
    ;;
  *.zip)
    if ! unzip -o "$tmp_archive" -d "$TARGET_DIR/bin" arduino-cli 2>/dev/null; then
      unzip -o "$tmp_archive" -d "$TARGET_DIR/bin"
      found_bin="$(find "$TARGET_DIR/bin" -name arduino-cli -type f | head -1)"
      if [[ -n "$found_bin" && "$found_bin" != "$TARGET_BIN" ]]; then
        mv "$found_bin" "$TARGET_BIN"
      fi
    fi
    ;;
esac

chmod +x "$TARGET_BIN" 2>/dev/null || true

# --- Verify. ---
if [[ ! -x "$TARGET_BIN" ]]; then
  err "Extraction did not produce an executable at $TARGET_BIN"
  err "Contents of $TARGET_DIR/bin:"
  ls -la "$TARGET_DIR/bin" >&2
  exit 1
fi

if ! "$TARGET_BIN" version &>/dev/null; then
  err "Binary exists but does not run: $TARGET_BIN"
  exit 1
fi

installed_version="$("$TARGET_BIN" version 2>/dev/null | head -1 || echo unknown)"
ok "arduino-cli installed successfully."
ok "Path: $TARGET_BIN"
ok "Version: $installed_version"
info ""
info "Add to PATH with:"
info "  export PATH=\"$TARGET_DIR/bin:\$PATH\""
info "Or set ARDUINO_CLI=\"$TARGET_BIN\" in your environment."

exit 0
