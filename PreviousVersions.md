# Previous Versions

This page keeps the older Primus sender and receiver tracks available for reference. Current development should start from [README.md](README.md) and the active V3.5 docs under [V3_5/](V3_5/).

## V3.1

V3.1 was the previous modular track. It introduced the split Python sender architecture, the Alpine.js web UI, clip/look workflow, Look Mixer, cue controller, and device grouping. Its receiver firmware targeted the ESP32-S3 Reverse TFT Feather with NeoPXL8 FeatherWing outputs 6 and 7.

Useful reference locations:

- [V3_1/sender/](V3_1/sender/) - modular sender code
- [V3_1/Arduino/](V3_1/Arduino/) - previous ESP32-S3 receiver firmware and upload script
- [V3_1/hardwarePinout.md](V3_1/hardwarePinout.md) - V3.1 hardware pinout

Historical launch command:

```bash
python3 V3_1/sender/run.py
```

Historical firmware command:

```bash
cd V3_1/Arduino
./upload.sh
```

## V3.0

V3.0 was the original single-file sender. It kept the HTTP server, Art-Net engine, effects engine, and full HTML/CSS/JS web UI embedded in [V3_0/sender/led_controller.py](V3_0/sender/led_controller.py). It is useful for historical reference, but it does not include the current V3.5 compatibility firmware, launch behavior, clip/look/cue workflow, or board-profile support.

Historical launch command:

```bash
python3 V3_0/sender/led_controller.py
```

## Current Recommendation

Use V3.5 for new work. V1, V2, and V3.1 hardware should be reflashed with V3.5 firmware so every receiver generation speaks the same current Art-Net, discovery, output-config, IP-config, rename, hello, and FPS telemetry protocol.