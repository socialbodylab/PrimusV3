# RadiusCentral vVERSION

macOS release built from the V5 unified sender (`--product radius`).

## Changes

- Describe user-facing changes here.

## Validation

- `RadiusCentral.app` Developer ID signed with network entitlements, notarized, and stapled
- `RadiusCentral-VERSION-macOS-arm64.dmg` signed, notarized, stapled, and verified with `hdiutil verify`
- LaunchServices smoke: `open -n V5/dist/macos/RadiusCentral.app --args --port 8098 --no-browser` then `curl -s http://127.0.0.1:8098/api/runtime`

## Assets

- `RadiusCentral-VERSION-macOS-arm64.dmg`
- `RadiusCentral-VERSION-macOS-arm64.dmg.sha256`

## SHA-256

```text
PASTE_DIGEST_HERE  RadiusCentral-VERSION-macOS-arm64.dmg
```
