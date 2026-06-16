# Previous Versions

This page keeps older Primus sender and receiver tracks available for reference. Current development starts from [README.md](README.md) and the active V3.6 docs under [V3_6/](V3_6/).

## V3.5

V3.5 introduced the Clip, Look, and Timeline segment brightness model, portable sharing bundles, OSC input, firmware upload panel, and the workshop UI profile. Its receiver firmware added capability tags, ArtPollReply discovery, output config, IP config, rename, hello flash, and FPS telemetry.

Useful reference locations:

- [V3_5/sender/](V3_5/sender/) - sender code
- [V3_5/Arduino/](V3_5/Arduino/) - receiver firmware and upload script
- [V3_5/README.md](V3_5/README.md) - V3.5 documentation index

Historical launch command:

```bash
python3 V3_5/sender/run.py
```

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

## V3.0

V3.0 was the original single-file sender. It kept the HTTP server, Art-Net engine, effects engine, and full HTML/CSS/JS web UI embedded in [V3_0/sender/led_controller.py](V3_0/sender/led_controller.py). It is useful for historical reference only.

Historical launch command:

```bash
python3 V3_0/sender/led_controller.py
```

## Current Recommendation

Use V3.6 for all new work. V1, V2, and V3.1 hardware should be reflashed with V3.6 firmware so every receiver generation speaks the same current Art-Net, discovery, output-config, IP-config, rename, hello, and FPS telemetry protocol.
