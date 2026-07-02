# PrimusCentral v0.91

macOS release built from the V4 unified sender (`--product primus` and `--product devices`).

## Changes

- **Receive mode (split/combined)** — firmware ArtReceiveConfig opcode 0x8110, NVS persistence, combined-universe ArtDmx slicing, sender parsing and routing, device UI controls, and upload-time receive-mode defaults.
- **Firmware v3.8.0** — V3 TFT receive-mode display and button control; capability tag reports combined mode (`U:C:N`).
- **Hello serial monitor** — device Hello opens a serial monitor panel for Primus receivers; firmware upload is blocked while monitoring is active.
- **Device Manager UI** — refreshed device grid layout, version label in navbar, and shared device-card improvements from `device-conn.js`.
- **Firmware panel** — receive-mode override options on compile/upload jobs.
- **UI** — navbar shows `PrimusCentral v0.91` and `Device Manager v0.91`.

## Validation

- `python3 -m unittest discover -s V4/sender/tests`
- `PrimusCentral.app` Developer ID signed with network entitlements, notarized, and stapled
- `DeviceManager.app` Developer ID signed with network entitlements, notarized, and stapled
- `PrimusCentral-0.91-macOS-arm64.dmg` signed, notarized, stapled, and verified with `hdiutil verify`
- `DeviceManager-0.91-macOS-arm64.dmg` signed, notarized, stapled, and verified with `hdiutil verify`

## Assets

- `PrimusCentral-0.91-macOS-arm64.dmg`
- `PrimusCentral-0.91-macOS-arm64.dmg.sha256`
- `DeviceManager-0.91-macOS-arm64.dmg`
- `DeviceManager-0.91-macOS-arm64.dmg.sha256`

## SHA-256

```text
TBD  PrimusCentral-0.91-macOS-arm64.dmg
TBD  DeviceManager-0.91-macOS-arm64.dmg
```
