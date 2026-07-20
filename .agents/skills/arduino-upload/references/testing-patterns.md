# Testing Patterns — The Four-Tier Model

AUS is designed for *agent-driven* and *CI-driven* firmware development: every operation is a non-interactive CLI with structured output, so a script (or an LLM agent, or a GitHub Actions step) can drive it end-to-end without human intervention.

This document describes the four testing tiers, from cheapest to most expensive, and how to wire them together.

## The four tiers

| Tier | What it tests | Requires a board? | Requires network? | Cost |
|---|---|---|---|---|
| 1. Compile-gate | "Does the code build?" | No | No | Seconds, free |
| 2. Flash + boot | "Does the firmware upload and the board boot?" | Yes | No | Minutes |
| 3. Serial assert | "Did the firmware print its expected startup banner?" | Yes | No | Minutes |
| 4. Protocol readback | "Is the firmware reporting correct state over the network?" | Yes | Yes (usually) | Minutes |

Each tier is strictly stronger than the one before. A tier-1 pass doesn't imply tier-2; a tier-4 pass implies everything below.

---

## Tier 1: Compile-gate

The cheapest, fastest test. Runs `arduino-cli compile` headlessly — no board required. Use this as your merge gate: every PR must compile.

```bash
./upload.sh --compile
./upload.sh --board v2 --compile
```

Exit 0 = builds; exit 6 = compile failed (with the compiler's error output on stderr).

### In CI

```yaml
# .github/workflows/firmware.yml
- name: Compile-gate
  run: |
    ./upload.sh --install    # ensure toolchain + libs
    ./upload.sh --board v1 --compile
    ./upload.sh --board v2 --compile
```

`--install` is idempotent and safe to run every CI run; it caches installed libraries in `~/.arduino15/` (or `$AUS_TOOLCHAIN_DIR`).

### With multiple `--define` combinations

If your firmware has compile-time feature flags, test them all:

```bash
for feature in DEBUG=0 DEBUG=1 LOGGING=0 LOGGING=1; do
  ./upload.sh --board v1 --define "$feature" --compile
done
```

---

## Tier 2: Flash + boot

Compile + upload to one board. The board reboots into the new firmware. Success means the upload command returned 0; it does *not* mean the firmware is healthy — that's tier 3.

```bash
./upload.sh --auto                 # auto-detect the one connected board
./upload.sh /dev/cu.usbserial-XXXX # explicit port
./upload.sh --board v2 --all       # flash every matching board
```

Exit codes:
- `0` — uploaded successfully
- `3` — no ports detected (board not plugged in?)
- `4` — multiple candidates, use `--all` or pick one
- `7` — upload failed (bad cable? board in bootloader mode already?)

### When to use this tier

- Smoke-testing that a freshly-merged change doesn't brick the upload path.
- Preparing a board for a tier-3 or tier-4 test.
- Flashes that don't produce useful serial output (e.g. a one-shot NVS-wipe utility).

---

## Tier 3: Serial assert

The "is the board alive?" test. After upload, open a serial monitor and wait for the firmware to print its expected startup banner. If the banner appears, the board booted, the firmware ran `setup()`, and the serial path works. If it doesn't appear within a timeout, something is wrong.

AUS provides `--expect REGEX` for this:

```bash
./upload.sh --auto --expect 'blue_green ready'
./upload.sh --auto --expect 'boot complete' --expect-timeout 30
```

Exit 0 = banner matched (tier 3 passes). Exit 11 = timeout, banner never appeared (tier 3 fails).

### The canonical example: `blue_green`

The `assets/test_sketches/blue_green/` directory contains the reference tier-3 test:

- `blue_green.ino` — a 60-line sketch that initializes a NeoPixel strip, prints `blue_green ready` to Serial, and runs a rainbow animation. No WiFi, no networking, no dependencies beyond Adafruit_NeoPixel. It exists to isolate "is the hardware path working?" from everything else.

- `blue_green_upload.sh` — an AUS-conforming uploader. Run:

  ```bash
  ./blue_green_upload.sh --auto --expect 'blue_green ready'
  ```

  If exit 0, your board's LED strip, USB-serial, power, and flash are all good. Any issue is in your *actual* firmware, not the hardware.

### Writing your own serial assert

Your sketch just needs to print a recognizable line early in `setup()`:

```cpp
void setup() {
  Serial.begin(115200);
  delay(300);
  Serial.println("myfirmware v1.2 booting...");
  // ... actual init ...
  Serial.println("myfirmware ready");
}
```

Then:

```bash
./upload.sh --auto --expect 'myfirmware ready'
```

### When serial asserts don't work

- **The firmware prints over USB-CDC on a different baud** — set `--baud` to match your `Serial.begin()`.
- **The firmware has no serial output at all** — add a banner. There's no good reason a production sketch can't print one line on boot.
- **The banner only prints once in `setup()`** — by the time the monitor connects after upload, the banner is gone. Print a heartbeat (every 1–2s) so a late-connecting monitor can still catch it. The `blue_green.ino` sketch does this.
- **ESP32-S3 / ESP32-C3 native USB-CDC on macOS** — these chips' USB-CDC implementation can be flaky: the port enumerates and `arduino-cli upload` works, but `arduino-cli monitor` reads zero bytes. Known workarounds: (a) force `CDCOnBoot=disabled` in the FQBN options and route `Serial` to UART0 (GPIO 1/3) with a USB-serial adapter on the read side; (b) use the `Hardware CDC and JTAG` USB mode (`USBMode=hwcdc`); (c) test on Linux or via a real USB-serial bridge. This is a chip/driver quirk, not an AUS issue — the AUS library is correct (verified against simulated monitors).
- **The board uses network-only logging** (no USB-serial) — skip to tier 4.

---

## Tier 4: Protocol readback

The most powerful test. After upload, query the firmware over its actual transport (UDP/Art-Net, MQTT, BLE, HTTP, Modbus, whatever) and assert that its reported state matches what you expect. This is what catches "the firmware booted and looks fine, but it's reporting the wrong device name / wrong IP / wrong config."

AUS provides `--post-upload-hook` for this. The hook is a script invoked after each successful upload:

```bash
./upload.sh --auto \
  --define-header DEFAULT_DEVICE_NAME='Stage Left' \
  --post-upload-hook ./verify_device_name.sh
```

The hook receives three arguments:

```
./verify_device_name.sh <port> <fqbn> <profile>
```

Its exit code is propagated: 0 continues, non-zero aborts (clamped to the 64–127 range to avoid colliding with AUS's reserved codes).

### Example: Art-Net device-name verification

This is the pattern the PrimusV3 firmware workflow uses. After uploading firmware with a `DEFAULT_DEVICE_NAME` override, a Python script queries the board over UDP and asserts the name round-tripped:

```bash
#!/usr/bin/env bash
# verify_device_name.sh — post-upload hook
set -euo pipefail
port="$1" fqbn="$2" profile="$3"

# Wait for the board to boot and join WiFi.
sleep 8

# Discover it on the LAN via Art-Net.
python3 - <<'PY'
import sys, time, socket, struct

# Send ArtPoll, wait for ArtPollReply, check short_name.
# (Real implementation uses the project's Art-Net library.)
EXPECTED_NAME = "Stage Left"
SOCK = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
SOCK.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
SOCK.settimeout(3.0)
SOCK.bind(("0.0.0.0", 6454))

# Broadcast ArtPoll on port 6454.
poll = struct.pack(">8sBBIH", b"Art-Net\x00", 0, 0x52, 0x14, 0)
SOCK.sendto(poll, ("255.255.255.255", 6454))

deadline = time.time() + 10
while time.time() < deadline:
    try:
        data, addr = SOCK.recvfrom(2048)
        if data[:8] == b"Art-Net\x00" and struct.unpack(">H", data[8:10])[0] == 0x0021:
            short_name = data[44:76].decode("ascii", "ignore").rstrip("\x00")
            if short_name == EXPECTED_NAME:
                print(f"PASS: device at {addr[0]} reports name '{short_name}'")
                sys.exit(0)
            else:
                print(f"FAIL: device at {addr[0]} reports '{short_name}', expected '{EXPECTED_NAME}'")
                sys.exit(64)
    except socket.timeout:
        continue

print("FAIL: no Art-Net reply received within timeout")
sys.exit(64)
PY
```

Wire it in:

```bash
./upload.sh --auto \
  --define-header DEFAULT_DEVICE_NAME='"Stage Left"' \
  --post-upload-hook ./verify_device_name.sh
```

If the hook exits non-zero, `./upload.sh` exits non-zero — your CI step fails, your agent gets the signal.

### Other protocol examples

- **HTTP**: `curl http://<board-ip>/health | grep -q '"ok":true'`
- **MQTT**: subscribe to the board's status topic, assert it publishes within N seconds.
- **BLE**: use `bleak` (Python) or `gatttool` to read a characteristic.
- **Modbus**: read a holding register and compare against expected value.

The hook is just a script — anything you can assert from the command line works.

---

## Combining tiers in one invocation

A single `./upload.sh` call can run all four tiers sequentially:

```bash
./upload.sh --board v2 \
  --compile \                                      # tier 1 (redundant if --auto runs)
  --define-header DEFAULT_DEVICE_NAME='"Stage Left"' \
  --auto \                                          # tier 2 (flash)
  --expect 'firmware ready' \                       # tier 3 (serial)
  --post-upload-hook ./verify_artnet.sh             # tier 4 (readback)
```

If any tier fails, the exit code tells you which:

| Exit | Meaning |
|---|---|
| 0 | All tiers passed. |
| 6 | Tier 1 failed (compile error). |
| 7 | Tier 2 failed (upload error). |
| 11 | Tier 3 failed (banner never appeared). |
| 64+ | Tier 4 failed (hook returned this code). |

This is what makes AUS agent-friendly: an LLM or CI runner gets a single integer that tells it exactly what went wrong, without parsing stderr.

---

## The agent-driven loop

Putting it all together — here's the end-to-end workflow an LLM agent (or a developer) follows:

1. **Make a code change** to the sketch.
2. **Compile-gate**: `./upload.sh --compile`. If it fails, fix the code; don't bother with hardware.
3. **Flash + serial assert**: `./upload.sh --auto --expect 'boot ok'`. If it fails, the hardware path is broken — check cables, power, bootloader mode.
4. **Protocol readback** (if applicable): `./upload.sh --auto --post-upload-hook ./verify.sh`. If it fails, the firmware is running but misbehaving — debug the logic.

Each step is a single command with a single integer verdict. The agent doesn't need to read the script's source or understand the hardware; it just runs the command and branches on the exit code.

This is the workflow the PrimusV3 firmware project uses daily. AUS generalizes it so any Arduino project can adopt the same loop.
