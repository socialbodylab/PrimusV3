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
79241e46a02cb1322e0c3565f80f061e06b5fdb3ca5ddbd688284a34bcd6625d  PrimusCentral-0.92-macOS-arm64.dmg
87090c6100754bcf9a8e6171d93e375086721d177cf5b792d33c8ac24b090cce  DeviceManager-0.92-macOS-arm64.dmg
cbbef7a64feff3c9a309a54879303e83ef2dc64487cf129f80c908254c7353cc  PrimusReceiverFirmware-3.9.0.zip
```
