# RadiusCentral v0.92

macOS release built from the V5 unified sender (`--product radius`).

## Changes

- First GitHub-published RadiusCentral macOS DMG from the V5 packaging pipeline.
- Same Developer ID + shared `PrimusCentral Notary` profile used by PrimusCentral and DeviceManager.
- Release assets produced with `V5/build_sender_app.py --dmg` (clean staging, DMG notarization, sha256 after staple).

## Validation

- `RadiusCentral.app` Developer ID signed with network entitlements, notarized, and stapled
- `RadiusCentral-0.92-macOS-arm64.dmg` signed, notarized, stapled, and verified with `hdiutil verify`
- LaunchServices smoke: `open -n V5/dist/macos/RadiusCentral.app --args --port 8098 --no-browser` then `curl -s http://127.0.0.1:8098/api/runtime` → `product: radius`, `app_version: 0.92`

## Assets

- `RadiusCentral-0.92-macOS-arm64.dmg`
- `RadiusCentral-0.92-macOS-arm64.dmg.sha256`

## SHA-256

```text
8f156f1d64c36461c98476e207ba4d00e81a13192ff56368bed3f9e2555aa581  RadiusCentral-0.92-macOS-arm64.dmg
```
