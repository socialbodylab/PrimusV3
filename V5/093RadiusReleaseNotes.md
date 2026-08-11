# RadiusCentral v0.93

macOS release built from the V5 unified sender (`--product radius`).

## Changes

- **App icon** — RadiusCentral now bundles `V5/assets/radiusIcon.png` (converted to `.icns` at build time) instead of the shared Primus `appIcon.png`.

## Validation

- `RadiusCentral.app` Developer ID signed with network entitlements, notarized, and stapled
- `RadiusCentral-0.93-macOS-arm64.dmg` signed, notarized, stapled, and verified with `hdiutil verify`
- LaunchServices smoke: `open -n V5/dist/macos/RadiusCentral.app --args --port 8098 --no-browser` then `curl -s http://127.0.0.1:8098/api/runtime` → `product: radius`, `app_version: 0.93`

## Assets

- `RadiusCentral-0.93-macOS-arm64.dmg`
- `RadiusCentral-0.93-macOS-arm64.dmg.sha256`

## SHA-256

```text
8bffce559e19cd8e7c5972a1456ab602af393259a38c5ac5bef27e641443cb89  RadiusCentral-0.93-macOS-arm64.dmg
```
