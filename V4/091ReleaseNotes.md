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
- `PrimusCentral.app` Developer ID signed with network entitlements (notarization pending Apple Developer agreement renewal)
- `DeviceManager.app` Developer ID signed with network entitlements (notarization pending Apple Developer agreement renewal)
- `PrimusCentral-0.91-macOS-arm64.dmg` signed and verified with `hdiutil verify`
- `DeviceManager-0.91-macOS-arm64.dmg` signed and verified with `hdiutil verify`

## Assets

- `PrimusCentral-0.91-macOS-arm64.dmg`
- `PrimusCentral-0.91-macOS-arm64.dmg.sha256`
- `DeviceManager-0.91-macOS-arm64.dmg`
- `DeviceManager-0.91-macOS-arm64.dmg.sha256`

## SHA-256

```text
34a0da96dea55a2ddea089de3401916738cf5b468c45073d9d3baf928da0ad94  PrimusCentral-0.91-macOS-arm64.dmg
c4834b2d1ec24d81112ccd8508bf2a327473c80f451fd601768d62de0d6aeaf3  DeviceManager-0.91-macOS-arm64.dmg
```
