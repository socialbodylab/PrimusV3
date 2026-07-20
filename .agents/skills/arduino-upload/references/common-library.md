# AUS Common Library — API Reference

The `aus_common.sh` library is the reference implementation of AUS 1.0. Source it from your upload script and call its functions; your script conforms to the spec by construction.

This document is the complete API. For the contract, see `aus-spec.md`. For end-to-end examples, see the templates under `assets/`.

## Sourcing the library

```bash
#!/usr/bin/env bash
set -euo pipefail
AUS_SCRIPT_VERSION="1.0.0"        # used by --version and --ports-json

# Locate the library. The scaffolder sets this; hand-written scripts should
# resolve it relative to their own location.
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
AUS_LIB_DIR="${AUS_LIB_DIR:-$SCRIPT_DIR}"
source "$AUS_LIB_DIR/aus_common.sh"

# ... register boards, parse args, run ...
```

The library is idempotent (safe to source twice) and guarded against `set -u`.

---

## Lifecycle

A conforming script is just four calls in order:

```bash
aus_register_board ...          # 1. Declare your board profile(s). Repeatable.
aus_parse_args "$@"             # 2. Parse CLI flags into globals.
# (optional: translate project flags into overrides here)
aus_run "$SKETCH_DIR"           # 3. Resolve board + dispatch to compile/upload/install.
                                #    Never returns — always exits.
```

`aus_run` always calls `exit` itself. Do not expect control to return.

---

## Board profile registry

### `aus_register_board <name> [options]`

Declare a board profile. Call once per profile, before `aus_parse_args`. The first-registered profile is the default unless another is given `--default`.

**Options:**

| Option | Required | Default | Description |
|---|---|---|---|
| `--fqbn <fqbn>` | yes | — | Fully Qualified Board Name, e.g. `esp32:esp32:featheresp32`. |
| `--baud <n>` | no | `115200` | Default upload speed. |
| `--define "<-DX>"` | no | (none) | Compiler define(s) for this profile, e.g. `-DPROFILE_V1`. |
| `--libs "<lib1>,<lib2>"` | no | (none) | Comma-separated library names to auto-install (comma-separated so names with spaces survive). |
| `--desc "<text>"` | no | (none) | Human-readable description (shown in logs). |
| `--vids "1111,2222"` | no | ESP32 set | Comma-separated 4-hex VIDs for port matching. |
| `--keywords "a,b"` | no | ESP32 set | Comma-separated keywords for port matching. |
| `--core "<pkg:arch>"` | no | derived | Board core to install, e.g. `esp32:esp32`. Derived from FQBN if omitted. |
| `--package-url <url>` | no | lookup | Board-manager URL. Auto-looked-up from a built-in table if omitted. |
| `--default` | no | first | Mark this profile as the default selection. |

**Example:**

```bash
aus_register_board v1 \
  --fqbn "esp32:esp32:featheresp32" \
  --baud 115200 \
  --libs "Adafruit NeoPixel" \
  --desc "Adafruit HUZZAH32"

aus_register_board v2 \
  --fqbn "esp32:esp32:adafruit_feather_esp32s3_reversetft" \
  --baud 921600 \
  --libs "Adafruit NeoPixel" \
  --desc "Adafruit Feather S3 Reverse TFT" \
  --default
```

Users select with `--board v1` or `--board v2`. Without `--board`, the default (`v2` above) is used.

---

## Argument parsing

### `aus_parse_args "$@"`

Parses the standard AUS flags (§3.2 of the spec) plus any positional port paths. Sets the `AUS_*` globals listed below. Exits on error.

**Globals set:**

| Global | Type | Meaning |
|---|---|---|
| `AUS_BOARD_PROFILE` | string | Selected profile name (empty → default). |
| `AUS_FQBN_OVERRIDE` | string | `--fqbn` value, if given. |
| `AUS_BAUD_OVERRIDE` | string | `--baud` value, if given. |
| `AUS_COMPILE_ONLY` | bool | `--compile`. |
| `AUS_INSTALL_ONLY` | bool | `--install`. |
| `AUS_AUTO_PORT` | bool | `--auto`. |
| `AUS_ALL_PORTS` | bool | `--all`. |
| `AUS_LIST_PORTS` | bool | `--ports`. |
| `AUS_LIST_PORTS_JSON` | bool | `--ports-json`. |
| `AUS_CLEAN` | bool | `--clean`. |
| `AUS_DRY_RUN` | bool | `--dry-run`. |
| `AUS_VERBOSE` | int | Verbosity level (0 = default). |
| `AUS_QUIET` | bool | `--quiet`. |
| `AUS_EXPLICIT_PORTS` | array | Positional port paths. |
| `AUS_DEFINE_FLAGS` | string | Accumulated `-DKEY=VAL` flags. |
| `AUS_OVERRIDE_DEFINES` | array | `KEY VALUE` pairs for the override header. |
| `AUS_POST_UPLOAD_HOOK` | string | `--post-upload-hook` path or `$AUS_POST_UPLOAD_HOOK`. |
| `AUS_EXPECT_REGEX` | string | `--expect` pattern. |
| `AUS_EXPECT_TIMEOUT` | int | `--expect-timeout` (default 15). |

### Adding project-specific flags

Define `aus_custom_arg` *before* calling `aus_parse_args`. It's called for any unrecognized `-*` flag:

```bash
aus_custom_arg() {
  local flag="$1" val="${2:-}"
  case "$flag" in
    --ssid)
      [[ -z "$val" ]] && aus_die "$AUS_EXIT_GENERIC" "$flag requires a value"
      MY_SSID="$val"
      AUS_CUSTOM_SHIFT=2        # tell parser how many args you consumed
      return 0                  # 0 = handled
      ;;
    --reset)
      MY_RESET=true
      AUS_CUSTOM_SHIFT=1
      return 0
      ;;
  esac
  return 1   # 1 = not ours, let AUS reject it
}
```

`AUS_CUSTOM_SHIFT` defaults to 2; set it to 1 for valueless flags.

### Overriding the usage text

Define `aus_print_usage` before `aus_parse_args`:

```bash
aus_print_usage() {
  cat <<EOF
my-script — does the thing.

Usage: my-script [--board v1] [--auto | PORT]
  ...
EOF
}
```

---

## Overrides (build-time configuration)

Overrides let you inject `#define`s into the compile without editing source. There are two layers; use either or both:

### `--define KEY=VAL` (flag-level, raw `-D`)

Appends `-DKEY=VAL` to the compiler flags. Pass-through — no escaping. Best for simple integer toggles.

### Override header (file-level, force-included `#define`s)

For string values, multi-field config, or anything the sketch reads via `#ifdef`. The library generates a temp header, force-includes it via `-include`, and cleans it up on exit.

#### `aus_override_define <key> <value>`

Add `#define KEY VALUE` to the header. VALUE is emitted verbatim — use for integers, macros, or pre-quoted expressions.

```bash
aus_override_define BAUD_RATE 115200
aus_override_define FEATURE_FLAG (1 << 3)
```

#### `aus_override_define_cstring <key> <value>`

Add `#define KEY "value"` to the header. VALUE is C-escaped (backslashes and quotes escaped, wrapped in quotes). Use for strings the sketch stores as `const char[]`.

```bash
aus_override_define_cstring DEVICE_NAME 'Stage Left'
# → #define DEVICE_NAME "Stage Left"
```

#### `aus_mark_secret <key>`

Mark a key as secret. Its value will not be echoed in the "overrides applied" log summary (only the fact that it was set).

```bash
aus_override_define_cstring DEFAULT_WIFI_PASSWORD 'hunter2'
aus_mark_secret DEFAULT_WIFI_PASSWORD
# log shows: "DEFAULT_WIFI_PASSWORD: <set>"  — never the value
```

#### `aus_create_override_header()`

Generate the header file if any overrides were supplied. Called automatically by `aus_compile` / `aus_run`; you don't usually call this directly. The header always begins with:

```c
#pragma once
#define AUS_BUILD_ID "<unique-per-invocation-string>"
```

Firmware can compare `AUS_BUILD_ID` against persisted state to apply overrides exactly once per flash.

---

## Logging

All log functions write to stderr with the standard prefixes (§7 of the spec). Color is auto-disabled when stderr isn't a TTY or `--no-color` is given.

| Function | Prefix | Color | When to use |
|---|---|---|---|
| `aus_info "msg"` | `[INFO]` | blue | Progress / status. Suppressed by `--quiet`. |
| `aus_ok "msg"` | `[OK]` | green | Success milestones. Suppressed by `--quiet`. |
| `aus_warn "msg"` | `[WARN]` | yellow | Recoverable concerns. |
| `aus_error "msg"` | `[ERROR]` | red | Failures (doesn't exit). |
| `aus_die <code> "msg"` | `[ERROR]` | red | Log an error then exit with `<code>`. |
| `aus_log_secret_set "label"` | `[INFO]` | blue | Log that a secret override was set, value-free. |

---

## Toolchain

These are called automatically by `aus_run`. Call them directly only if you're building a custom flow.

### `aus_check_cli()`

Verify `arduino-cli` is available. Resolution order: `$ARDUINO_CLI`, `$AUS_TOOLCHAIN_DIR/bin`, `$AUS_REPO_ROOT/.tools/arduino-cli/bin`, `PATH`. If missing and `AUS_AUTO_INSTALL_CLI=1` (default), attempts auto-install. Exits `AUS_EXIT_CLI_NOT_FOUND` (2) on failure.

### `aus_bootstrap_cli()`

Download arduino-cli into `$AUS_TOOLCHAIN_DIR` (default `.tools/arduino-cli`). Idempotent. Delegates to `aus_bootstrap.sh` if present, otherwise inlines. Sets `AUS_CLI_BIN`.

### `aus_ensure_core <core> <package-url>`

Install a board core (e.g. `esp32:esp32`) if absent. Registers the package URL first if needed. Idempotent. Exits `AUS_EXIT_CORE_INSTALL_FAILED` (9) on failure.

### `aus_ensure_libs()`

Install every library in `AUS_RESOLVED_LIBS` if absent. Idempotent. Exits `AUS_EXIT_LIB_INSTALL_FAILED` (8) on failure.

**Set `AUS_AUTO_INSTALL_CLI=0` to disable auto-download** (useful in CI where you want to fail fast on a missing toolchain rather than download at runtime).

---

## Port detection

Called automatically by `aus_run` based on flags. Each respects the per-profile `--vids` / `--keywords` settings.

| Function | Mode | Output | Exit on failure |
|---|---|---|---|
| `aus_list_ports` | `--ports` | Human-readable list to stdout | 0 always |
| `aus_list_ports_json` | `--ports-json` | Single-line JSON to stdout (§5) | 0 always |
| `aus_detect_port` | `--auto` | One address to stdout | 3 (none) / 4 (many) |
| `aus_detect_all_ports` | `--all` | One address per line | 3 (none) |

All require `python3` (the multi-signal matcher is Python; see `port-detection.md`). If python3 is missing, they exit `AUS_EXIT_PORT_DETECTION_ERROR` (10).

---

## Build & upload

Called automatically by `aus_run`. Direct use is for custom flows.

### `aus_compile <sketch_dir>`

Run `arduino-cli compile` with the resolved FQBN (including `UploadSpeed`), profile defines, accumulated `--define` flags, and the override header (force-included). Exits `AUS_EXIT_COMPILE_FAILED` (6) on failure. Honors `--clean` and `--dry-run`.

### `aus_upload_one <sketch_dir> <port>`

Run `arduino-cli upload` to one port. Assumes compile already succeeded. Exits `AUS_EXIT_UPLOAD_FAILED` (7) on failure.

---

## Serial & testing hooks

### `aus_monitor <port> [timeout]`

Open `arduino-cli monitor` on a port, line-buffered. With a timeout, exits after N seconds (timeout utility). Without, runs until interrupted.

### `aus_capture <port> <outfile> [timeout]`

Like `aus_monitor` but redirects output to a file.

### `aus_expect <port> <regex> [timeout]`

Open a monitor and succeed (return 0) when a line matches REGEX, or fail (return 1, conventionally exiting 11) on timeout. This is the "is the board alive?" primitive.

```bash
if ! aus_expect "$port" 'blue_green ready' 15; then
  aus_die "$AUS_EXIT_EXPECT_FAILED" "Board did not print its banner — hardware fault?"
fi
```

The `--expect REGEX` flag wires this in automatically after each upload.

### `aus_run_post_upload_hook <port> <fqbn> <profile>`

Invoke the post-upload hook (from `--post-upload-hook` or `$AUS_POST_UPLOAD_HOOK`) as:

```
<hook> <port> <fqbn> <profile>
```

The hook's exit code is propagated. Use this for protocol-level readback (Art-Net, MQTT, HTTP) — anything more complex than a serial line match.

---

## Top-level orchestrator

### `aus_run <sketch_dir>`

The main entry point. Dispatches based on parsed flags:

| Flags present | Behavior | Exit on success |
|---|---|---|
| `--ports-json` | Emit JSON and exit | 0 |
| `--ports` | Emit human list and exit | 0 |
| `--install` | Install cores + libs, exit | 0 |
| `--compile` | Compile only, exit | 0 |
| `--auto` / port(s) / `--all` | Compile + upload (+ hook/expect) | 0 |

Always calls `exit` itself — never returns.

---

## Exit-code constants

All exported as `AUS_EXIT_*` so hooks and custom flows can reference them:

```
AUS_EXIT_SUCCESS         = 0
AUS_EXIT_GENERIC         = 1
AUS_EXIT_CLI_NOT_FOUND   = 2
AUS_EXIT_NO_PORTS        = 3
AUS_EXIT_AMBIGUOUS_PORTS = 4
AUS_EXIT_UNKNOWN_BOARD   = 5
AUS_EXIT_COMPILE_FAILED  = 6
AUS_EXIT_UPLOAD_FAILED   = 7
AUS_EXIT_LIB_INSTALL_FAILED   = 8
AUS_EXIT_CORE_INSTALL_FAILED = 9
AUS_EXIT_PORT_DETECTION_ERROR = 10
AUS_EXIT_EXPECT_FAILED   = 11
```

Use these in `aus_die` calls rather than magic numbers:

```bash
aus_die "$AUS_EXIT_GENERIC" "Something went wrong"
```
