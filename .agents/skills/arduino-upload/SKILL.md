---
name: arduino-upload
description: Build standardized, agent-friendly Arduino upload scripts that conform to the AUS 1.0 spec, for ANY Arduino-compatible board (ESP32, ESP8266, AVR, RP2040, SAMD, etc.). Use whenever the user wants to set up Arduino firmware development, create an upload/flash script, automate board testing over USB or network, compile-test sketches headlessly, build an agent-driven or CI firmware workflow, or mentions arduino-cli / FQBN / serial upload / flashing. Handles board-profile declaration, automatic arduino-cli + library + core installation, multi-signal port detection, build-time config overrides, post-upload verification, and the full compile-flash-assert loop. Also use when the user has an existing ad-hoc upload script and wants to standardize or refactor it.
---

# Arduino Upload (AUS) Skill

This skill helps you create and work with **AUS 1.0** — the Arduino Upload Script standard: a specification for the CLI surface of scripts that compile and flash Arduino-compatible boards via `arduino-cli`. A conforming script has a known flag set, a known JSON contract, known exit codes, and works the same way across ESP32 / ESP8266 / AVR / RP2040 / SAMD.

The spec is in `references/aus-spec.md`. The reference implementation is the sourced bash library `scripts/aus_common.sh`. Together they make writing a conforming upload script a 30-line exercise instead of a 1000-line one.

## When to use this skill

Trigger this skill when the user wants to:

- **Set up firmware development** for a new Arduino-compatible board or project.
- **Create an upload script** (a "flash script", a "build script", a "deploy script") for Arduino code.
- **Automate board testing** — compile-testing headlessly, asserting serial output, verifying behavior over a network protocol after upload.
- **Build an agent-driven or CI firmware workflow** — a loop where a script (LLM agent, GitHub Actions, etc.) drives compile → flash → verify without human intervention.
- **Standardize an existing ad-hoc script** — refactor a hand-rolled upload.sh into something conforming and shareable.
- Anything involving `arduino-cli`, FQBNs, serial uploads, board profiles, library auto-install, or post-flash verification.

Do NOT trigger for: pure Arduino *sketch* (`.ino`) authoring questions unrelated to the upload/build workflow; PlatformIO-specific questions (different toolchain); or hardware electronics advice unrelated to firmware tooling.

## What's in this skill

```
arduino-upload/
├── SKILL.md                      ← you are here
├── references/
│   ├── aus-spec.md               ← THE specification (read this first when implementing)
│   ├── common-library.md         ← full API docs for every aus_* function
│   ├── board-profiles.md         ← FQBNs + cores + libs for common boards
│   ├── port-detection.md         ← how multi-signal port matching works
│   ├── testing-patterns.md       ← the four-tier compile-flash-assert-readback model
│   └── primusv3-case-study.md    ← how a real 1000-line script maps onto the spec
├── scripts/
│   ├── aus_common.sh             ← the sourced library (implements the spec)
│   ├── new_aus_script.sh         ← scaffolder: generates a conforming script
│   ├── aus_selftest.sh           ← conformance checker: validates a script against the spec
│   └── aus_bootstrap.sh          ← standalone arduino-cli installer
└── assets/
    ├── template_minimal.sh       ← 30-line single-board template
    ├── template_full.sh          ← multi-profile template with custom flags + overrides
    ├── board_profiles/           ← preset snippets for common boards
    └── test_sketches/blue_green/ ← canonical "is the board alive?" test sketch + uploader
```

## How to use it

### Path 1 — Beginner (just want a working upload script)

Run the scaffolder interactively:

```bash
./scripts/new_aus_script.sh
```

Answer the prompts (board preset, name, sketch dir, libraries). It writes a ready-to-run script. Done.

Or with flags:

```bash
./scripts/new_aus_script.sh --name myboard --preset esp32-feather --sketch ./my_sketch --output upload.sh
```

Then:

```bash
./upload.sh --install    # one-time: install cores + libraries
./upload.sh --compile    # verify the code builds
./upload.sh --auto       # flash the detected board
```

### Path 2 — Standard (scaffold + customize)

Scaffold a script, then edit it to add project-specific flags and overrides. Read `references/common-library.md` for the full API. The key hooks:

- **`aus_register_board`** — declare your board(s). See `references/board-profiles.md` for FQBNs.
- **`aus_custom_arg`** — handle project-specific flags (WiFi creds, device names, feature toggles).
- **`aus_override_define` / `aus_override_define_cstring`** — translate those flags into build-time `#define`s.
- **`aus_mark_secret`** — never echo a flag's value in logs.

The `assets/template_full.sh` shows all of these wired together.

### Path 3 — Advanced (hand-write or refactor)

Read `references/aus-spec.md` first — it's the contract. Then either:

- **Hand-write** a script that sources `aus_common.sh` (most flexible), or
- **Refactor** an existing script to conform. Use `references/primusv3-case-study.md` as a worked example of how a real 1000-line script maps onto the spec.

Validate with the conformance checker:

```bash
./scripts/aus_selftest.sh ./your_script.sh
```

It mechanically checks `--version`, `--help`, flag handling, mutex rules, JSON schema, and portability. Aim for 10/10.

## The agent-driven testing loop (why this skill exists)

The killer feature of AUS is that it makes firmware development **scriptable end-to-end**. Every operation is a non-interactive CLI with a single-integer verdict:

```bash
./upload.sh --compile                                    # tier 1: does it build?
./upload.sh --auto                                       # tier 2: does it flash?
./upload.sh --auto --expect 'firmware ready'             # tier 3: does it boot + print?
./upload.sh --auto --post-upload-hook ./verify.sh        # tier 4: does it behave correctly?
```

Read `references/testing-patterns.md` for the full four-tier model and worked examples (including a complete Art-Net protocol-readback hook).

Exit codes tell you exactly which tier failed:

| Exit | Meaning |
|---|---|
| 0 | Success |
| 2 | arduino-cli missing |
| 3 | No ports detected |
| 4 | Multiple ports (use `--all` or pick one) |
| 5 | Unknown board profile |
| 6 | Compile failed |
| 7 | Upload failed |
| 8/9 | Library/core install failed |
| 11 | Serial expectation not matched |
| 64+ | Post-upload hook failed |

This is what lets an LLM agent or CI runner drive firmware development without reading stderr or understanding the hardware.

## Key concepts (read these once)

**AUS 1.0** — the spec version. A conforming script declares it in `--version` output as `<author-version> (AUS 1.0)`.

**Profile** — a named hardware target within a script (e.g. `v1`, `feather-s3`). One script can have many; users select with `--board <name>`.

**FQBN** — Fully Qualified Board Name (`packager:arch:board_id`), the string `arduino-cli` uses to pick the build target. See `references/board-profiles.md`.

**Override** — a build-time `#define` injected via the override header, so the same firmware image can be customized per-device at flash time without editing source. See `references/common-library.md` § Overrides.

**Candidate port** — a serial port the detector believes might be the target board, based on USB VID, keywords, path patterns, and FQBN match. See `references/port-detection.md`.

**Conformance** — a script that satisfies `references/aus-spec.md`. Verify with `scripts/aus_selftest.sh`.

## Portability

- **bash 3.2+** (macOS default). No associative arrays, no `mapfile`, no `${var,,}`.
- **macOS / Linux** native.
- **Windows** via WSL or Git Bash (not native cmd.exe/PowerShell).
- **python3** recommended (used by the port detector); required only for `--auto`/`--all`/`--ports`/`--ports-json`.
- Shebang is always `#!/usr/bin/env bash`.

## Quick reference: the minimal conforming script

```bash
#!/usr/bin/env bash
set -euo pipefail
AUS_SCRIPT_VERSION="1.0.0"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
AUS_LIB_DIR="${AUS_LIB_DIR:-$SCRIPT_DIR}"
source "$AUS_LIB_DIR/aus_common.sh"

SKETCH_DIR="$SCRIPT_DIR/my_sketch"

aus_register_board default \
  --fqbn "esp32:esp32:featheresp32" \
  --baud 115200 \
  --libs "Adafruit NeoPixel"

aus_parse_args "$@"
aus_run "$SKETCH_DIR"
```

That's it. Sources the library, registers one board, parses args, runs. Conforms to AUS 1.0 by construction. Copy `assets/template_minimal.sh` to start.

## Common workflows (jump table)

| User wants... | Read this | Run this |
|---|---|---|
| A new upload script, fast | — | `./scripts/new_aus_script.sh` |
| To know the FQBN for a board | `references/board-profiles.md` | — |
| To add WiFi/device-name overrides | `references/common-library.md` § Overrides | use `aus_override_define_cstring` |
| To understand port detection | `references/port-detection.md` | `./upload.sh --ports-json` |
| To set up automated testing | `references/testing-patterns.md` | `./upload.sh --auto --expect '...'` |
| To verify a script conforms | `references/aus-spec.md` §12 | `./scripts/aus_selftest.sh ./script.sh` |
| To see how a real script maps to the spec | `references/primusv3-case-study.md` | — |
| To install arduino-cli | `references/common-library.md` § Toolchain | `./scripts/aus_bootstrap.sh` |
| The full spec | `references/aus-spec.md` | — |

## Implementation notes for the agent

When helping a user set up AUS for their project:

1. **Default to the scaffolder.** Run `new_aus_script.sh` rather than hand-writing. It produces a clean, conforming script in one step. Hand-write only when the user needs something the scaffolder can't express.

2. **Read the spec before modifying the library.** `aus_common.sh` is the reference implementation — changes to it change what "conformance" means. If a user wants a feature the library lacks, prefer adding it as a project-specific flag in their script (via `aus_custom_arg`) over modifying the library.

3. **Validate after changes.** Run `aus_selftest.sh` on any conforming script you write or modify. Aim for 10/10. The self-test catches the common mistakes (wrong exit codes, missing flags, broken JSON).

4. **The library is designed to be lifted into its own repo.** It has no dependencies on this skill's directory structure beyond the conventional `scripts/` layout. If a user wants to vendor it into their project, they can copy `aus_common.sh` (and optionally `aus_bootstrap.sh`) anywhere and point `AUS_LIB_DIR` at it.

5. **ESP32 is the default but not the limit.** The port-detection defaults lean ESP32 (the most common target), but every profile can override `--vids` and `--keywords`. For AVR/RP2040/ESP8266, use the matching preset or supply custom values. See `references/board-profiles.md`.

6. **Don't reinvent port detection.** The multi-signal Python matcher in `aus_common.sh` is the product of real-world testing across many boards. If a user reports it doesn't detect their board, the fix is almost always to add the board's VID/keywords to the profile (see `references/port-detection.md` § "Tuning for unusual boards"), not to rewrite the detector.
