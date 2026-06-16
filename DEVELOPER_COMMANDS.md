# Developer Commands

> **Audience:** Developers and technical operators. Quick-reference shell commands for starting the sender, killing instances, finding serial ports, and uploading firmware. For show operator network setup and app walkthrough, see [HumanGuide.md](HumanGuide.md).

## Start the sender

**Primus Central** (LED + audio nodes):
```bash
python3 V3_6/sender/run.py
```

**Radius Central** (audio-only nodes):
```bash
python3 V3_6/sender/run.py --mode radius
```

The sender prints its URL on startup and opens it in your browser automatically.

## Kill all running instances

```bash
pkill -f "python3.*run.py"
```

To confirm everything is dead:

```bash
ps aux | grep run.py | grep -v grep
```

## Find running instances and their ports

```bash
ps aux | grep run.py | grep -v grep
```

Then look up their ports by PID:

```bash
lsof -p <PID> -i -P -n | grep LISTEN
```

Or find all Python processes listening at once:

```bash
lsof -i -P -n | grep Python | grep LISTEN
```

## Clean restart

```bash
pkill -f "python3.*run.py"
python3 V3_6/sender/run.py
```

## Find the serial port

Use arduino-cli to list connected boards with their port and FQBN:

```bash
arduino-cli board list
```

When a board is connected it appears with its name and port. If nothing is plugged in, only system serial ports (Bluetooth, etc.) show up.

Alternatively, list USB serial devices directly:

```bash
ls /dev/cu.usb*
```

Plug the board in, run it again, and the new entry is your board. ESP32-S3 (Feather TFT) shows up as `cu.usbmodemXXXX`; HUZZAH32 shows up as `cu.usbserialXXXX`.

## Build and upload LED receiver firmware

```bash
cd V3_6/Arduino && ./upload.sh --auto
```

See `V3_6/FIRMWARE_DEVELOPMENT.md` for full profile options (`-v1`, `-v2`, `-v3`).

## Build and upload Radius firmware

**V2 (ESP32-S3 Reverse TFT Feather):**

```bash
cd V3_6/Arduino && ./upload.sh -rv2 --auto
```

**V1 (HUZZAH32):**

```bash
cd V3_6/Arduino && ./upload.sh -rv1 --auto
```

Specify the port explicitly to avoid the wrong device being detected:

```bash
cd V3_6/Arduino && ./upload.sh -rv2 /dev/cu.usbmodemXXXX
```

See `V3_6/FIRMWARE_DEVELOPMENT.md` for full Radius profile options.

## Run the test suite

```bash
python3 -m unittest discover -s V3_6/sender/tests
```

## WAV test fixtures

Three small WAV files for testing and hardware integration are in `V3_6/sender/tests/fixtures/`. All are 44100 Hz, 16-bit mono PCM — the format required by the Radius VS1053 audio board.

| File | Content |
|---|---|
| `silence_1s.wav` | 1 second of silence (~86 KB) |
| `tone_440hz_1s.wav` | 1 second of 440 Hz sine tone (~86 KB) |
| `tone_880hz_1s.wav` | 1 second of 880 Hz sine tone (~86 KB) |

To regenerate them (Python stdlib, no dependencies):

```bash
python3 - <<'EOF'
import math, struct, wave, os
OUT   = "V3_6/sender/tests/fixtures"
RATE  = 44100
N     = RATE  # 1 second
AMP   = 32767
os.makedirs(OUT, exist_ok=True)

def write_wav(name, samples):
    with wave.open(os.path.join(OUT, name), "w") as f:
        f.setnchannels(1); f.setsampwidth(2); f.setframerate(RATE)
        f.writeframes(struct.pack(f"<{len(samples)}h", *samples))

write_wav("silence_1s.wav",    [0] * N)
write_wav("tone_440hz_1s.wav", [int(AMP * math.sin(2*math.pi*440*t/RATE)) for t in range(N)])
write_wav("tone_880hz_1s.wav", [int(AMP * math.sin(2*math.pi*880*t/RATE)) for t in range(N)])
EOF
```

To convert existing audio to the required format on macOS:

```bash
afconvert -f WAVE -d LEI16@44100 input.aif output.wav
```

To convert using SoX (cross-platform):

```bash
sox input.mp3 -r 44100 -b 16 -c 1 output.wav
```
