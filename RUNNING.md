# Running PrimusV3

## Start the sender

```bash
cd ~/Documents/RUR/PrimusV3/V3_1/sender && python3 run.py
```

The sender prints its URL on startup and opens it in your browser automatically. No arguments needed — it picks an available port.

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
cd ~/Documents/RUR/PrimusV3/V3_1/sender && python3 run.py
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

## Build and upload Radius firmware

**V2 (ESP32-S3 Reverse TFT Feather):**

```bash
cd ~/Documents/RUR/PrimusV3/V3_2/Arduino && ./upload.sh /dev/cu.usbmodemXXXX
```

**V1 (HUZZAH32):**

```bash
cd ~/Documents/RUR/PrimusV3/V3_2/Arduino && ./upload.sh --board feather-esp32 /dev/cu.usbserialXXXX
```

Specify the port explicitly to avoid the wrong device being detected.
