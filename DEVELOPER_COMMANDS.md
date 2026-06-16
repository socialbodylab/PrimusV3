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
cd V3_6/Arduino && ./upload.sh --auto
```

**V1 (HUZZAH32):**

```bash
cd V3_6/Arduino && ./upload.sh --auto
```

Specify the port explicitly to avoid the wrong device being detected:

```bash
cd V3_6/Arduino && ./upload.sh /dev/cu.usbmodemXXXX
```

See `V3_6/Arduino/radiusV2/HARDWARE_WIRING.md` for Radius V2 wiring.
