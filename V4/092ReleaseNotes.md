# PrimusCentral v0.92

macOS release built from the V4 unified sender (`--product primus` and `--product devices`).

## Changes

- **Independent Primus firmware updates** — Firmware page checks GitHub releases for `PrimusReceiverFirmware-*.zip` assets, shows installed vs latest version, and can download/install receiver source into app data without upgrading PrimusCentral.
- **Firmware release bundles** — `V4/build_firmware_bundle.py` builds zip + SHA-256 sidecar assets for GitHub firmware-only releases.
- **Bundled receiver firmware v3.9.0** — V3 custom PCB profile updates (direct NeoPixel outputs, battery telemetry, TFT screens).

## Validation

- `python3 -m unittest discover -s V4/sender/tests`
- `PrimusCentral.app` Developer ID signed with network entitlements, notarized, and stapled
- `DeviceManager.app` Developer ID signed with network entitlements, notarized, and stapled
- `PrimusCentral-0.92-macOS-arm64.dmg` signed, notarized, stapled, and verified with `hdiutil verify`
- `DeviceManager-0.92-macOS-arm64.dmg` signed, notarized, stapled, and verified with `hdiutil verify`

## Assets

- `PrimusCentral-0.92-macOS-arm64.dmg`
- `PrimusCentral-0.92-macOS-arm64.dmg.sha256`
- `DeviceManager-0.92-macOS-arm64.dmg`
- `DeviceManager-0.92-macOS-arm64.dmg.sha256`
- `PrimusReceiverFirmware-3.9.0.zip`
- `PrimusReceiverFirmware-3.9.0.zip.sha256`

## SHA-256

```text
TBD  PrimusCentral-0.92-macOS-arm64.dmg
TBD  DeviceManager-0.92-macOS-arm64.dmg
TBD  PrimusReceiverFirmware-3.9.0.zip
```
