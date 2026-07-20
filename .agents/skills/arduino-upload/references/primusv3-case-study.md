# Case Study: PrimusV3's `upload.sh` mapped onto AUS 1.0

This document maps the existing `V4/Arduino/upload.sh` in this repository onto the AUS 1.0 spec. It serves two purposes:

1. **Validates the spec is real-world-shaped** — every feature of a production firmware workflow (multiple boards, build overrides, secret handling, post-upload verification) is expressible.
2. **Provides a migration guide** — if PrimusV3's own scripts ever conform to AUS, this is the diff.

PrimusV3's `upload.sh` is ~1000 lines of bash. It does not conform to AUS yet (it predates the spec), but the *vast majority* of its features map cleanly.

---

## What PrimusV3's `upload.sh` does today

A 1000-line bash script that:

- Compiles and uploads the Primus LED receiver firmware to one of three ESP32 board profiles (`v1`, `v2`, `v3`).
- Auto-detects ESP32 serial ports via a multi-signal Python heredoc.
- Accepts per-build overrides for WiFi credentials, device name, character/performer names, static IP, receive mode, output types, and virtual pixel counts — baked into the build via a generated override header.
- Generates a unique build-id so firmware applies overrides exactly once per flash.
- Is driven by a Python GUI (`firmware.py`) via subprocess, which parses the JSON port list and streams stdout.

It's the *source* of the patterns AUS generalizes.

---

## Feature mapping

| PrimusV3 feature | AUS spec section | Conforms today? | Migration note |
|---|---|---|---|
| `-h`, `--help` | §3.2 | ✅ | Direct match. |
| `-v1`, `-v2`, `-v3`, `--board` | §3.2 (`--board`) | ✅ | Aliases are fine; AUS requires `--board <name>`. |
| `--compile` | §3.2 | ✅ | Direct match. |
| `--install` | §3.2 | ✅ | Direct match. |
| `--auto`, `--all` | §3.2 | ✅ | Direct match. |
| `--ports`, `--ports-json` | §3.2, §5 | ⚠️ partial | JSON shape differs slightly (see below). |
| `--baud` | §3.2 | ✅ | Direct match. |
| Positional ports | §3.2 | ✅ | Direct match. |
| `-ssid`, `-pw`, `--name`, `--character-name`, etc. | §3.4 (project flags) | ✅ | These are project-specific; AUS leaves them to the script. |
| Override header generation | §4 | ✅ | Same mechanism (`#pragma once`, `AUS_BUILD_ID`, `-include`). AUS renames the build-id macro. |
| Secret redaction (password never logged) | §7.4 | ✅ | AUS provides `aus_mark_secret` for this. |
| Multi-signal port detection (VID + keyword + path + FQBN) | §5.3 | ✅ | AUS's reference detector is a generalization of PrimusV3's. |
| `arduino-cli` location (env var, project-local, PATH) | §9 | ✅ | AUS adds auto-install. |
| ESP32 core + library auto-install | §9 | ✅ | AUS generalizes to any core. |
| Exit codes | §6 | ❌ | PrimusV3 uses only 0 and 1. AUS defines 11 distinct codes. |
| `--version` | §2 | ❌ | PrimusV3 has no `--version` flag. |
| `--fqbn` override | §3.2 | ❌ | Not present. |
| `--define KEY=VAL` | §3.2, §4.1 | ❌ | Not present as a generic mechanism. |
| `--define-header KEY=VAL` | §3.2, §4.2 | ❌ | Not present. |
| `--post-upload-hook` | §10.2 | ❌ | Not present (the Art-Net readback lives in Python, not the script). |
| `--expect` | §10.1 | ❌ | Not present. |
| `--clean`, `--dry-run`, `--no-color`, `--verbose`, `--quiet` | §3.2 | ❌ | Not present. |

**Summary:** ~60% of the spec is already satisfied. The remaining 40% is additive — features PrimusV3 doesn't have yet, but that don't conflict with anything it does.

---

## The JSON shape difference

PrimusV3's `--ports-json` emits:

```json
{"target_fqbn":"...", "ports":[...], "candidates":[...], "others":[...]}
```

AUS 1.0 requires:

```json
{"spec_version":"1.0", "script_version":"...", "target_fqbn":"...",
 "selected_board":"...", "ports":[...], "candidates":[...], "others":[...]}
```

The Python parser in PrimusV3's `firmware.py` (`parse_ports_json_output`) tolerantly scans for the last `{`-prefixed line and accepts either shape, so adding the AUS fields is backward-compatible. But PrimusV3's own output is missing:

- `spec_version` — required for callers to know what schema to expect.
- `script_version` — useful for diagnostics.
- `selected_board` — useful when the script supports multiple profiles.
- Per-port `vid`, `pid`, `matching_fqbn` — AUS requires these; PrimusV3 omits them.

---

## What the override header looks like in each

### PrimusV3 today

```c
#pragma once
#define PRIMUSV3_OVERRIDE_BUILD_ID "1784555574-9750-84024"
#define PRIMUSV3_FORCE_DEVICE_NAME_OVERRIDE 1
#define DEVICE_SHORT_NAME "Stage Left"
#define DEFAULT_WIFI_SSID "PrimusRouter"
#define DEFAULT_WIFI_PASSWORD "secret"
```

### AUS-conformant equivalent

```c
#pragma once
#define AUS_BUILD_ID "1784555574-9750-84024"
#define DEVICE_SHORT_NAME "Stage Left"
#define DEFAULT_WIFI_SSID "PrimusRouter"
#define DEFAULT_WIFI_PASSWORD "secret"
```

The differences:

- `AUS_BUILD_ID` replaces `PRIMUSV3_OVERRIDE_BUILD_ID` (spec-mandated name).
- The `PRIMUSV3_FORCE_*_OVERRIDE` macros are gone — AUS doesn't standardize them. PrimusV3 would keep them as project-specific defines via `aus_override_define`, since the firmware reads them in `config.h`.

Firmware-side: change the one `#ifdef PRIMUSV3_OVERRIDE_BUILD_ID` check to `#ifdef AUS_BUILD_ID` (or check both during migration).

---

## What a migration would look like

If PrimusV3's `upload.sh` were rewritten to conform to AUS 1.0, the structure would be:

```bash
#!/usr/bin/env bash
set -euo pipefail
AUS_SCRIPT_VERSION="3.13.0"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/../../../.agents/skills/arduino-upload/scripts/aus_common.sh"

SKETCH_DIR="$SCRIPT_DIR/primusV3_receiver"

# Three profiles, exactly as today.
aus_register_board v1 \
  --fqbn "esp32:esp32:featheresp32" \
  --define "-DPRIMUS_PROFILE_V1" \
  --baud 115200 \
  --libs "Adafruit NeoPixel"

aus_register_board v2 \
  --fqbn "esp32:esp32:adafruit_feather_esp32_v2" \
  --define "-DPRIMUS_PROFILE_V2" \
  --baud 115200 \
  --libs "Adafruit NeoPixel"

aus_register_board v3 \
  --fqbn "esp32:esp32:adafruit_feather_esp32s3_reversetft" \
  --define "-DPRIMUS_PROFILE_V3_1" \
  --baud 921600 \
  --libs "Adafruit NeoPXL8,Adafruit ST7735 and ST7789 Library,Adafruit GFX Library" \
  --default

# Project-specific flags wired through the custom-arg hook.
aus_custom_arg() {
  local flag="$1" val="${2:-}"
  case "$flag" in
    -ssid|--ssid)
      MY_WIFI_SSID="$val"; AUS_CUSTOM_SHIFT=2; return 0 ;;
    -pw|--pw|--password)
      MY_WIFI_PASSWORD="$val"; AUS_CUSTOM_SHIFT=2; return 0 ;;
    --name|--device-name)
      MY_DEVICE_NAME="$val"; AUS_CUSTOM_SHIFT=2; return 0 ;;
    --character-name|--character)
      MY_CHARACTER="$val"; AUS_CUSTOM_SHIFT=2; return 0 ;;
    # ... etc for all the PrimusV3-specific flags ...
  esac
  return 1
}

aus_parse_args "$@"

# Translate parsed project flags into override-header defines.
if [[ -n "${MY_DEVICE_NAME:-}" ]]; then
  aus_override_define_cstring DEVICE_SHORT_NAME "$MY_DEVICE_NAME"
fi
if [[ -n "${MY_WIFI_SSID:-}" ]]; then
  aus_override_define_cstring DEFAULT_WIFI_SSID "$MY_WIFI_SSID"
fi
if [[ -n "${MY_WIFI_PASSWORD:-}" ]]; then
  aus_override_define_cstring DEFAULT_WIFI_PASSWORD "$MY_WIFI_PASSWORD"
  aus_mark_secret DEFAULT_WIFI_PASSWORD
fi
# ... etc ...

aus_run "$SKETCH_DIR"
```

That's ~60 lines instead of ~1000. The other 940 lines are now in `aus_common.sh`, shared with every other AUS-conformant script.

The Python caller (`firmware.py`) would barely change: it already calls `["bash", "upload.sh", "--board", profile, ...]` and parses JSON from `--ports-json`. The only required change is expecting the new top-level JSON fields (`spec_version`, `script_version`, `selected_board`) — and those are additive.

---

## What this case study proves

1. **The spec is grounded in a real, production firmware workflow**, not invented in a vacuum. Every AUS feature traces back to a PrimusV3 need or a generalization of one.

2. **Migration is incremental.** A script can adopt AUS piece by piece: add `--version` first, then `--define`/`--define-header`, then the new exit codes, then (optionally) rewrite to source the library. The spec's stability rules (§11) guarantee each step keeps callers working.

3. **The library eliminates duplication.** PrimusV3 has *four* near-identical upload scripts (`upload.sh`, `radius_upload.sh`, `clear_nvs_upload.sh`, `v1_blue_green_test_upload.sh`), each ~300–1000 lines, each duplicating the same port-detection Python, the same install logic, the same override-header mechanism. AUS consolidates this into one ~700-line library and ~30-line per-script profiles.

4. **The JSON contract enables the Python integration.** PrimusV3's `firmware.py` already treats the upload script as a black box with a JSON API. AUS formalizes that API so the same Python integration works for *any* conforming script, in any project.

---

## What PrimusV3 has that AUS doesn't (yet)

A few PrimusV3 features are out of scope for AUS v1 but worth noting as future spec additions:

- **Per-output configuration overrides** (`--output0 type`, `--virtual0 count`) — these are Primus-specific because they map to Primus-specific `#define`s. They'd remain project flags, not spec flags.
- **Receive-mode override** — same; project-specific.
- **GitHub-release firmware auto-updater** (`firmware_source.py`) — this is a distribution mechanism, not a build/upload concern. A future companion spec could standardize it.

These aren't gaps in AUS; they're correctly classified as project concerns that AUS leaves to the script.
