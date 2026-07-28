# DeviceManager v0.96

macOS release built from the V4 unified sender (`--product devices`).

Bundled receiver firmware: **Primus 3.13.0**, **Radius 4.1.1** (latest V4; not V5 / 3.14.0).

## Changes

- **Monitor filtering & layout** — improved character-name filtering, startup scan, and Firmware tab layout since v0.93.
- **Show-info / rename reliability** — Art-Net rename and show-info writes verify with read-back sync.
- **Flash overrides** — character and performer name overrides apply once per firmware flash build.
- **Attach UX** — dedicated browser launcher and UI focus when attaching to an existing Central server.
- **Radius monitoring** — includes the v0.95 Radius monitor fixes and show-info flash overrides (v0.95 was built locally but never published).

## Validation

- `DeviceManager.app` Developer ID signed with network entitlements, notarized, and stapled
- `DeviceManager-0.96-macOS-arm64.dmg` signed, notarized, stapled, and verified with `hdiutil verify`

## Assets

- `DeviceManager-0.96-macOS-arm64.dmg`
- `DeviceManager-0.96-macOS-arm64.dmg.sha256`

## SHA-256

```text
2725c5503a48e6893264a1c8dec58d37a57cd01888409aaf2af8a13e001964e1  DeviceManager-0.96-macOS-arm64.dmg
```
