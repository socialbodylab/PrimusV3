# AUS Spec — Arduino Upload Script Standard

**Version:** 1.0
**Status:** Stable
**Audience:** Authors of Arduino upload scripts; tooling that consumes their output (agents, CI, GUIs).

AUS (Arduino Upload Script) is a specification for the CLI surface of scripts that compile and flash Arduino-compatible boards via `arduino-cli`. A script that satisfies this document is said to **conform to AUS 1.0**.

This is a *contract*, not a program. Any script in any language may conform. The reference implementation is the bash library `scripts/aus_common.sh`, and a script that `source`s it and calls `aus_run` conforms by construction.

> **Why a spec exists.** The same workflow — compile-test, flash one board, flash many boards, override build config, verify behavior over serial or network — is reinvented in every firmware project. By fixing the CLI shape, the JSON contract, and the exit codes, tooling written against one conforming script works against all of them. An agent that knows AUS 1.0 can drive *any* conforming script without reading its source.

---

## 0. Definitions

- **Conforming script** — an executable program that satisfies §1–§6 below.
- **Profile** — a named hardware target within a script (e.g. `v1`, `feather-s3`, `uno`). One script may declare multiple profiles; exactly one is *selected* per invocation.
- **FQBN** — the Fully Qualified Board Name used by `arduino-cli` (e.g. `esp32:esp32:featheresp32`). Format: `<packager>:<architecture>:<board_id>[:<options>]`.
- **Candidate port** — a serial/network port the script believes might be the target board.
- **Override** — a build-time configuration value injected into the compile (see §4).

---

## 1. Conformance

A script conforms to **AUS 1.0** if and only if it satisfies **all** of the following:

1. **Version declaration (§2)** — emits the spec version in `--version` output.
2. **Required flags (§3)** — accepts every flag in §3.2 and behaves as specified.
3. **JSON contract (§5)** — `--ports-json` emits JSON matching the §5 schema.
4. **Exit codes (§6)** — uses exit codes exactly as defined in §6.
5. **Log format (§7)** — uses the §7 prefixes and respects `--no-color`.
6. **Idempotency** — `--install` and `--compile` may be run repeatedly with no side effects beyond their stated purpose; re-running a successful install is a no-op.
7. **Portability (§8)** — runs on bash 3.2+ without the constructs listed in §8.

A script MAY additionally accept any number of project-specific flags (§3.4). Project-specific flags must not shadow the meaning of any required flag.

The conformance checker `scripts/aus_selftest.sh` mechanically validates 1–4; 5–7 require human review.

---

## 2. Version declaration

`--version` prints a single line to stdout in the form:

```
<author-version> (AUS <spec-version>)
```

Where:
- `<author-version>` is a free-form string chosen by the script author (e.g. `1.4.2`, `primus-3.13`, `2026-07-20`). It must not contain ` (AUS ` literally.
- `<spec-version>` is the AUS spec version the script targets, e.g. `1.0`.

Examples of conforming output:
```
1.0.0 (AUS 1.0)
primus-upload 3.13.0 (AUS 1.0)
```

A script that declares `AUS 1.0` in `--version` must satisfy the whole of this document. If it does not, it must declare a lower spec version or none.

---

## 3. Command-line interface

### 3.1 Synopsis

```
<conforming-script> [--board <profile>] [--fqbn <fqbn>] [--baud <n>]
                     {action} {port-selection} {overrides}
                     [<positional-port>...]
```

The four groups (action, port-selection, overrides, positional) are all optional and may be combined freely, subject to the mutual-exclusion rules in §3.5.

### 3.2 Required flags

Every conforming script MUST accept the following. Aliases are permitted; the canonical form is listed first.

| Flag | Value | Behavior |
|---|---|---|
| `-h`, `--help` | none | Print usage to stdout and exit 0. |
| `--version` | none | Print version line (§2) and exit 0. |
| `--board` | `<profile>` | Select profile by name. Unknown profile → exit 5. |
| `--baud` | `<n>` | Override the profile's default upload speed. |
| `--fqbn` | `<fqbn>` | Override the selected profile's FQBN entirely. Advanced escape hatch. |
| `--compile` | none | Compile only; do not flash. Requires no board connected. |
| `--install` | none | Install cores and libraries for the selected profile, then exit 0. |
| `--auto` | none | Detect and use exactly one candidate port. Multiple candidates → exit 4. |
| `--all` | none | Flash to every candidate port. |
| `--ports`, `--list-ports` | none | Print a human-readable port list and exit 0. |
| `--ports-json` | none | Print port JSON (§5) and exit 0. |
| `--clean` | none | Wipe build cache before compiling. |
| `--dry-run` | none | Print the commands that would run; execute nothing that has side effects. |
| `--no-color` | none | Disable ANSI color in logs (§7). |
| `-v`, `--verbose` | none | Increase log verbosity. |
| `--quiet` | none | Decrease log verbosity (errors only). |
| `--define` | `KEY=VAL` | Append `-DKEY=VAL` to the compiler flags. Repeatable. |
| `--define-header` | `KEY=VAL` | Append `#define KEY VAL` to the override header (§4). Repeatable. |
| `--post-upload-hook` | `<path>` | Path to a script invoked after each successful upload. |

A positional non-flag argument is treated as an explicit port path and collected into the explicit-port list.

### 3.3 Default profile

A script with multiple profiles MUST define a default. When `--board` is not supplied, the default profile is selected. A script with a single profile implicitly has that profile as the default.

### 3.4 Optional project flags

A script MAY accept additional flags for project-specific overrides (WiFi credentials, device names, IP configuration, feature toggles, etc.). Such flags:

- Must not reuse a name reserved by §3.2.
- Should, where applicable, follow the `--define-header KEY=VAL` convention rather than introducing bespoke flags, so generic tooling can inject config without knowing the project's flag names.
- Are conventionally emitted into the override header as `#define`s (§4).

### 3.5 Mutual-exclusion rules

A conforming parser MUST reject the following combinations with exit code 1 and a clear `[ERROR]` message:

| Combination | Reason |
|---|---|
| `--auto` and `--all` | Ambiguous port-selection mode. |
| `--ports` and `--ports-json` | Ambiguous output mode. |
| `--auto` and any explicit positional port | Conflicting port source. |
| `--all` and any explicit positional port | Conflicting port source. |
| `--install` together with `--auto`, `--all`, or positional ports | `--install` does not touch a board. |

`--compile` is compatible with `--install` only in the order `--install` then `--compile`; in practice `--install --compile` is permitted and performs install followed by a verify pass.

---

## 4. Build overrides

Overrides are per-build configuration values injected into the compile without editing source. There are exactly two mechanisms; conforming scripts MUST support both:

### 4.1 `--define KEY=VAL` (flag-level)

Adds the literal token `-DKEY=VAL` to the C/C++ compiler extra flags. The value is passed through verbatim — no quoting, no escaping is performed by the script. Repeatable; flags accumulate in the order given.

```
--define DEBUG=1 --define BAUD_RATE=115200
# → compiler sees: -DDEBUG=1 -DBAUD_RATE=115200
```

### 4.2 Override header (file-level)

For values that must appear as C `#define`s in a force-included header (string literals, multi-field config, anything the sketch reads via `#ifdef`), the script generates a temporary header containing `#pragma once` followed by one `#define` per supplied override, and force-includes it via the compiler's `-include <file>` option.

The `--define-header KEY=VAL` flag adds a single `#define` to this header. Project-specific flags that surface as `#define`s (WiFi SSID, device name, IP octets, etc.) are conventionally routed through the header rather than via raw `-D`, because:

- String values need C escaping (`"..."`) which `-D` handles inconsistently across compilers.
- The sketch can guard them with `#ifndef` so a default still applies when the override is absent.
- A unique build-id `#define` lets firmware apply overrides *exactly once per flash* (see §4.4).

The header's lifecycle:

1. Created in the system temp directory before compile.
2. Force-included by appending `-include <header>` to the compiler extra flags.
3. Removed on script exit (success or failure) via an `EXIT` trap.

### 4.3 Required override-header defines

If any override is supplied, the generated header MUST begin with:

```c
#pragma once
#define AUS_BUILD_ID "<opaque-string>"
```

`AUS_BUILD_ID` is an opaque, unique-per-invocation string (e.g. `<unix-time>-<random>-<pid>`). Firmware may compare it against persisted state to detect "this is a fresh flash" and apply overrides exactly once rather than clobbering later runtime changes.

### 4.4 Value escaping

When a project flag supplies a string value destined for a C string `#define`, the script MUST escape backslashes (`\` → `\\`) and double quotes (`"` → `\"`) and wrap the result in double quotes. Numeric values are emitted unquoted.

---

## 5. JSON contract (`--ports-json`)

`--ports-json` writes exactly **one JSON object** to stdout as a single line (compact, no indentation). Leading log lines on stderr are permitted and SHOULD be tolerated by parsers (scan stdout for the last line beginning with `{`).

### 5.1 Schema

```json
{
  "spec_version": "1.0",
  "script_version": "<author-version>",
  "target_fqbn": "<selected-fqbn>",
  "selected_board": "<profile-or-null>",
  "ports": [
    {
      "address": "/dev/cu.usbserial-XXXX",
      "label": "USB JTAG/serial debug unit",
      "protocol": "serial",
      "vid": "303a",
      "pid": "0001",
      "matching_fqbn": true,
      "candidate": true,
      "reason": "matches selected board, USB VID 303a"
    }
  ],
  "candidates": [ /* subset of ports where candidate == true */ ],
  "others":     [ /* subset of ports where candidate == false */ ]
}
```

### 5.2 Field semantics

| Field | Type | Meaning |
|---|---|---|
| `spec_version` | string | `"1.0"`. Must match §2. |
| `script_version` | string | Same string as §2's `<author-version>`. |
| `target_fqbn` | string | Lowercased FQBN of the selected profile (or `--fqbn` override), without options. |
| `selected_board` | string\|null | Profile name if one is selected, else `null`. |
| `ports` | array | Every port `arduino-cli` reported. May be empty. |
| `candidates` | array | Subset of `ports` with `candidate == true`. Convenience for callers. |
| `others` | array | Subset of `ports` with `candidate == false`. Convenience for callers. |

Per-port object:

| Field | Type | Meaning |
|---|---|---|
| `address` | string | Port address as `arduino-cli` reports it (e.g. `/dev/cu.usbserial-XXXX`, `COM3`). Never empty. |
| `label` | string | Human-readable label; falls back to `address` if none. |
| `protocol` | string | `serial`, `network`, etc. `"unknown"` if not reported. |
| `vid` | string | 4-hex-digit USB vendor ID, lowercase, zero-padded. Empty string if unknown. |
| `pid` | string | 4-hex-digit USB product ID, lowercase, zero-padded. Empty string if unknown. |
| `matching_fqbn` | bool | True iff `arduino-cli` matched this port to the selected FQBN exactly. |
| `candidate` | bool | True iff the script considers this port a likely target (see §5.3). |
| `reason` | string | Comma-separated human-readable justification for `candidate`. Empty for non-candidates. |

### 5.3 Candidate determination

Whether a port is a `candidate` is implementation-defined, but the *signal set* a conforming implementation should consider includes:

1. **Exact FQBN match** — `arduino-cli` matched the port's board to `target_fqbn`. Strongest signal.
2. **USB VID** — the port's VID is in the selected profile's known-VID set.
3. **Keyword** — port label/product/manufacturer/board-name contains a profile keyword.
4. **Path regex** — the address matches a serial-path pattern (`/dev/cu.usb*`, `/dev/ttyUSB*`, `/dev/ttyACM*`, `COM<n>`, etc.).
5. **Exclusion** — ports whose metadata contains an ignored keyword (e.g. `bluetooth`, `debug-console`) are never candidates.

Profiles MAY customize the VID set and keyword list (see `references/port-detection.md`). The defaults are ESP32-leaning because that is the most common target; AVR, RP2040, and ESP8266 profiles override them.

---

## 6. Exit codes

Conforming scripts use exit codes as follows. **All codes are reserved** except `64+`, which is reserved for project use.

| Code | Symbolic name | Meaning |
|---|---|---|
| 0 | SUCCESS | Operation completed. |
| 1 | GENERIC_FAILURE | Validation error, argument error, or any failure not covered below. |
| 2 | CLI_NOT_FOUND | `arduino-cli` is not installed or not on PATH. |
| 3 | NO_PORTS | No candidate ports were detected. |
| 4 | AMBIGUOUS_PORTS | Multiple candidate ports detected and `--auto` requires exactly one. |
| 5 | UNKNOWN_BOARD | The selected profile name is not declared by this script. |
| 6 | COMPILE_FAILED | `arduino-cli compile` returned non-zero. |
| 7 | UPLOAD_FAILED | `arduino-cli upload` returned non-zero. |
| 8 | LIB_INSTALL_FAILED | A required library failed to install. |
| 9 | CORE_INSTALL_FAILED | A required board core failed to install. |
| 10 | PORT_DETECTION_ERROR | `arduino-cli board list` failed or returned unparseable output. |
| 11 | EXPECT_FAILED | A `--expect` (or equivalent post-upload assertion) did not match within the timeout. |
| 64–127 | reserved | Reserved for project use. Projects SHOULD document their meanings. |
| 128+ | — | Reserved (shell signal conventions: 128+n = killed by signal n). |

Rationale: today most upload scripts collapse every failure to exit 1, forcing callers to parse stderr to learn *what* went wrong. Distinct codes let an agent (or CI step) branch: retry install on 8/9, prompt for a port on 3/4, report a code defect on 6, etc.

---

## 7. Log format

### 7.1 Prefixes and streams

Every log line written by the script itself begins with one of these prefixes, followed by a single space and the message:

| Prefix | Level | Color | Stream |
|---|---|---|---|
| `[INFO]` | info | blue | stderr |
| `[OK]` | success | green | stderr |
| `[WARN]` | warning | yellow | stderr |
| `[ERROR]` | error | red | stderr |

**Stdout is reserved for machine-readable output** (`--ports-json`, `--version`, addresses printed by `--auto`/`--all`). Everything the script itself logs goes to stderr, so a caller capturing stdout for parsing is not polluted by log noise.

### 7.2 Color control

- ANSI color is enabled by default when stderr is a TTY.
- `--no-color` disables it unconditionally.
- When stderr is not a TTY (piped to a file or another process), color SHOULD be disabled automatically. Scripts MAY still emit color if explicitly asked, but the default for non-TTY is off.

### 7.3 Subprocess output

Output from `arduino-cli` and other subprocesses is passed through verbatim (it is not re-prefixed). Callers that need to distinguish script logs from subprocess output may do so by the prefix: lines without an `[INFO]/[OK]/[WARN]/[ERROR]` prefix are from a subprocess.

### 7.4 Secret redaction

The script itself does not echo values supplied via flags that the author designates as secrets (e.g. WiFi passwords). When logging that such a flag was supplied, log only the fact ("password override: set"), never the value. See `references/common-library.md` for the `aus_secret_flags` mechanism.

---

## 8. Portability

### 8.1 Shell baseline

Conforming scripts target **bash 3.2 or later** (the default `/bin/bash` on macOS). This constrains the implementation:

- **No** associative arrays (`declare -A`).
- **No** `mapfile` / `readarray`.
- **No** `${var,,}` / `${var^^}` case-folding — use `printf '%s' "$var" | tr '[:upper:]' '[:lower:]'`.
- **No** `|&` shorthand for `2>&1 |`.
- `[[ ]]`, arrays, `local`, `IFS=. read -r -a arr <<< "$x"`, and `case`/`(( ))` are all fine.

### 8.2 Operating systems

Conforming scripts run on:

- **macOS** (native, via `/bin/bash` 3.2 or a Homebrew bash).
- **Linux** (any distribution with bash 3.2+).
- **Windows** under **WSL** (any distribution) or **Git Bash**. Native Windows `cmd.exe`/PowerShell are *not* supported targets; Windows users should be directed to WSL or Git Bash.

`#!/usr/bin/env bash` is the required shebang — never hardcode `/bin/bash`.

### 8.3 External tools

A conforming script may rely on:

- `bash` 3.2+
- `arduino-cli` (auto-installable per §9)
- `python3` (recommended; used by the reference port detector — see §10)
- Standard POSIX utilities: `awk`, `sed`, `grep`, `tr`, `mktemp`, `curl`, `uname`, `tar`/`unzip`.

`python3` is *recommended*, not required: a script may implement port detection in pure bash if it accepts the loss of multi-signal matching quality. The reference library treats python3 as required for `--ports-json`/`--auto`/`--all` and optional otherwise.

---

## 9. Toolchain bootstrap

A conforming script MUST provide a path from "fresh machine" to "compiling firmware" with no manual Arduino IDE install. Specifically:

1. **Locate** `arduino-cli` by searching, in order:
   - `$ARDUINO_CLI` env var (explicit path),
   - `$AUS_TOOLCHAIN_DIR/bin` (project-local isolated install),
   - `$REPO_ROOT/.tools/arduino-cli/bin` (conventional local install),
   - the inherited `PATH`.
2. **If not found**, either auto-install it (§9.1) or fail with exit code 2 and a message naming the install command or URL.
3. **Ensure the board core** for the selected FQBN's packager is installed (e.g. `esp32:esp32`). Idempotent.
4. **Ensure required libraries** for the selected profile are installed. Idempotent.

### 9.1 Auto-install of `arduino-cli`

If the script auto-installs `arduino-cli`:

- It downloads the latest release from `arduino/arduino-cli` on GitHub, selecting the asset matching the host OS and architecture (`uname -s` + `uname -m`).
- It installs into an isolated, project-local directory (conventionally `.tools/arduino-cli/bin/`), not a system location.
- It is idempotent: if the binary already exists and runs, do nothing.
- It MUST verify the download (checksum if the release provides one, or at minimum a successful `--version` invocation) before accepting it.

The standalone installer `scripts/aus_bootstrap.sh` performs exactly this and nothing else; conforming scripts MAY delegate to it.

### 9.2 Board-manager URLs

When installing a core that requires a non-default package index (e.g. ESP32, RP2040), the script MUST register the corresponding `additional_urls` entry via `arduino-cli config` before running `core update-index`. The reference library maintains a packager → URL table; project scripts may extend it.

---

## 10. Testing hooks

AUS scripts are designed to be driven by agents and CI. Two hooks support post-upload verification:

### 10.1 Serial assertion (`aus_expect` / `--expect`)

A convenience that opens a serial monitor after upload and succeeds (exit 0) when a line matches a supplied regex, or fails (exit 11) on timeout. This is the "is the board alive?" primitive used by minimal hardware tests (see the `blue_green` example).

A conforming script that exposes serial monitoring SHOULD offer this assertion. Scripts without serial support (e.g. network-only boards) MAY omit it.

### 10.2 Post-upload hook (`--post-upload-hook`)

After each successful upload, if a hook path is supplied (via flag or `$AUS_POST_UPLOAD_HOOK`), the script invokes it as:

```
<hook> <port> <fqbn> <profile>
```

The hook's exit code is propagated: 0 continues, non-zero aborts with the same code (clamped to 64–127 if outside that range, to avoid colliding with §6). Hooks are the integration point for protocol-level readback (Art-Net, MQTT, BLE, HTTP) where the firmware reports state over a network rather than serial.

See `references/testing-patterns.md` for the four-tier testing model (compile-gate, flash, serial-assert, hook-readback) and worked examples.

---

## 11. Stability and versioning

This is **AUS 1.0**. Future revisions:

- **Patch** (1.0.x): clarifications, examples, conformance-checker improvements. No behavior change for conforming scripts or callers.
- **Minor** (1.x): additive only — new optional flags, new optional JSON fields, new exit codes in the reserved-for-project range. A script conforming to 1.0 also conforms to any 1.x.
- **Major** (x.0): may change required flags, the JSON schema, or exit-code meanings. Bumping the major version is the only permitted way to break a 1.x caller.

A conforming script declares the *highest* spec version it satisfies. Tooling reads `spec_version` from `--ports-json` or `--version` to decide which features it may use.

---

## 12. Conformance checklist (quick reference)

When writing or reviewing a script, confirm:

- [ ] `--version` prints `<author-version> (AUS 1.0)`.
- [ ] All flags in §3.2 are accepted with the specified behavior.
- [ ] Mutual-exclusion rules (§3.5) are enforced with exit 1.
- [ ] `--ports-json` emits a single-line JSON object matching §5.1.
- [ ] Exit codes match §6 exactly.
- [ ] Logs use the §7 prefixes on stderr; stdout carries only machine output.
- [ ] `--no-color` and non-TTY both disable ANSI.
- [ ] `arduino-cli` is located per §9 or the script fails with exit 2.
- [ ] Cores and libraries install idempotently.
- [ ] No bash 4+ constructs (§8.1); shebang is `#!/usr/bin/env bash`.
- [ ] Override header (if any overrides supplied) begins with `#pragma once` and `AUS_BUILD_ID`, and is cleaned up on exit.
- [ ] Secret-flag values are never echoed.

Run `scripts/aus_selftest.sh <your-script>` to mechanically check the first group.
