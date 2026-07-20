# Port Detection — How It Works and How to Tune It

AUS's port detector is a multi-signal matcher: it scores each serial port reported by `arduino-cli board list` against a set of signals and decides which are "candidates" for your selected board. This document explains the signals, the defaults, and how to customize them for unusual hardware.

## Why multi-signal

No single signal is reliable across all boards:

- **USB VID alone misses boards** — many clones share the same CH340 VID (`1a86`) regardless of what's behind it.
- **Keyword matching alone has false positives** — a Bluetooth serial port labeled "Serial" would match `serial`.
- **Path regexes differ by OS** — macOS uses `/dev/cu.usbserial-*`, Linux uses `/dev/ttyUSB*`, Windows uses `COM<n>`.
- **arduino-cli's FQBN match is the strongest signal but only works for boards it recognizes in its database.**

Combining all four signals and de-duplicating the reasons gives a robust "this looks like the board you want" classification, with human-readable justification.

## The four signals

For each port reported by `arduino-cli board list --format json`, the detector computes a list of matching reasons:

### 1. Exact FQBN match (strongest)

If `arduino-cli` matched the port's `matching_boards[].fqbn` exactly to the selected profile's FQBN, the port is marked `matching_fqbn: true` and gets reason `"matches selected board"`. This is the gold standard — `arduino-cli`'s hardware database recognized your board.

### 2. USB VID

The port's properties contain a `vid` (vendor ID). If it's in the profile's `--vids` set, the port gets reason `"USB VID <vid>"`. The default set is ESP32-friendly:

```
10c4 — Silicon Labs CP210x         (most ESP32 dev boards)
1a86 — QinHeng CH340/CH910         (cheap ESP32/ESP8266/AVR clones)
303a — Espressif native USB        (ESP32-S3, ESP32-C3, ESP32-S2)
239a — Adafruit
0403 — FTDI FT232                  (classic Arduino, FTDI cables)
```

Override per profile: `--vids "2341,2a03,0403,1a86"` for AVR Arduino.

### 3. Keyword

The port's `address`, `label`, `protocol`, properties, and matched-board names/FQBNS are joined into a lowercase text blob. If any keyword from the profile's `--keywords` list is found in that blob, the port gets that keyword as a reason. Default keywords:

```
esp32, espressif, cp210, cp210x, ch340, ch910, wch,
silicon labs, feather, adafruit
```

Override per profile: `--keywords "arduino,uno,ftdi,ch340"` for classic Arduino.

### 4. Path regex

Two patterns catch serial adapters that lack a useful VID:

- **macOS**: `/(cu|tty)\.usb(serial|modem)` — matches `/dev/cu.usbserial-1410`, `/dev/cu.usbmodem*`, etc.
- **Linux**: `/dev/tty(usb|acm)\d+` — matches `/dev/ttyUSB0`, `/dev/ttyACM1`.

Reason: `"USB serial path"`. (Windows `COM<n>` ports are always treated as serial by `arduino-cli` and pass through.)

## Exclusions

Ports whose text blob contains any ignored keyword are *never* candidates, regardless of other signals:

```
bluetooth, debug-console
```

This filters out macOS Bluetooth serial ports and the macOS `debug-console` pseudo-port, which otherwise look like serial candidates.

## The `candidate` flag

A port is a candidate iff:

```
(is_serial) AND (has at least one reason) AND (not ignored)
```

Where `is_serial` means `protocol == "serial"` OR the port has an address.

## The four modes

| Mode | Flag | Behavior |
|---|---|---|
| List | `--ports` | Prints every candidate with board name + reasons, then "others" (non-candidates). Always exits 0. |
| JSON | `--ports-json` | Emits the §5 schema. Always exits 0. |
| Auto | `--auto` | Prints exactly one address (the only candidate). Exits 3 if none, 4 if more than one. |
| All | `--all` | Prints one address per line for every candidate. Prefers exact-FQBN matches if any exist. Exits 3 if none. |

### `--all` preference logic

When `--all` is used with multiple candidates:

1. If *some* candidates exactly match the selected FQBN, **only those** are used. Others are noted in a warning.
2. If *no* candidates exactly match, **every** candidate is used (with a warning that FQBN matching failed).

This matters when you have a mix of boards plugged in (say, an ESP32 and an ESP8266) and select the ESP32 profile — `--all` flashes only the ESP32s.

## Tuning for unusual boards

### "My board isn't detected"

1. Plug in the board.
2. Run `./upload.sh --ports-json | python3 -m json.tool` and find your port in the `ports` array.
3. Note the `vid`, `pid`, and any strings in `label` / `protocol` / `board`.
4. Add them to the profile:
   ```bash
   aus_register_board myboard \
     --fqbn "mycore:arch:myboard" \
     --vids "$(echo $VID_YOU_FOUND),10c4,1a86" \
     --keywords "myboard,$BOARD_NAME_YOU_FOUND"
   ```

### "Too many ports are detected (false positives)"

Tighten the VID set. Remove generic entries like `1a86` (CH340) if you have other CH340 devices on your machine, and rely on the FQBN match + a specific keyword instead:

```bash
aus_register_board precise \
  --fqbn "esp32:esp32:myboard" \
  --vids "303a" \
  --keywords "myboard,specific-vendor-name"
```

### "My Bluetooth headphones keep getting detected"

They shouldn't — `bluetooth` is in the ignored-keywords list. If you're hitting a different false-positive source, extend the ignored list by editing `_aus_port_python` in `aus_common.sh` (or open an issue — extending the ignored list via a flag is a planned feature).

## Why Python

The matcher is a ~100-line Python script embedded in `aus_common.sh` via a heredoc. Reasons:

- **JSON parsing** — `arduino-cli board list --format json` emits nested JSON with unpredictable shapes across versions. Python's `json` module handles this robustly; bash JSON parsers are painful.
- **Reason de-duplication** — `dict.fromkeys(reasons)` preserves order while removing duplicates, which is awkward in pure bash.
- **Readable logic** — the scoring function is clearer in Python than in bash `case` statements.

The Python script reads its parameters (target FQBN, VIDs, keywords) from environment variables, so it has no shell-injection surface — values flow through `os.environ`, not `eval`.

**If python3 is unavailable**, the `--compile`, `--install`, and explicit-port modes still work (they don't need detection). Only `--auto`, `--all`, `--ports`, and `--ports-json` require it, and they exit `AUS_EXIT_PORT_DETECTION_ERROR` (10) with a clear message.

## Inspecting what the detector sees

The `--ports-json` output is the single source of truth for what the detector computed. Every entry has:

```json
{
  "address": "/dev/cu.usbserial-1410",
  "label": "USB JTAG/serial debug unit",
  "protocol": "serial",
  "vid": "303a",
  "pid": "0001",
  "matching_fqbn": true,
  "candidate": true,
  "reason": "matches selected board, USB VID 303a",
  "board": "Adafruit Feather ESP32-S3 Reverse TFT"
}
```

If a port you expected to be a candidate shows up in `others` with an empty `reason`, work through the four signals above to see which one failed.

## Calling the detector directly

From a script that sources the library:

```bash
aus_resolve_board                          # sets AUS_RESOLVED_FQBN, etc.
addresses="$(aus_detect_all_ports)"        # newline-separated
json="$(aus_list_ports_json)"              # single-line JSON
```

Each function respects the currently-resolved profile's `--vids` and `--keywords`.
