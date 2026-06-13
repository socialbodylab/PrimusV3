# PrimusCentral v0.75

Workshop controller update built on the current V3.6 sender.

## Changes

- Workshop **Collar** now presets receivers to `long_strip` (72 LEDs) through sender-side ArtOutputConfig, so existing V3.6 firmware does not need a reflash.
- Cue Controller applies the workshop output preset (Badge + 72-LED Collar) before connecting saved devices.
- Legacy Collar clips saved as `short_strip` still load in the workshop UI through a sender-side clip alias.
- Removed the sender FPS slider from the Clips designer toolbar.

## Validation

- Python compile and V3.6 sender unit tests passed before release build.
- `PrimusCentral.app` was Developer ID signed, notarized, stapled, and accepted by Gatekeeper.
- `PrimusCentral-0.75-macOS-arm64.dmg` was signed, notarized, stapled, verified with `hdiutil verify`, and accepted by Gatekeeper.

## Assets

- `PrimusCentral-0.75-macOS-arm64.dmg`
- `PrimusCentral-0.75-macOS-arm64.dmg.sha256`

## SHA-256

```text
f7bbf3fd83b221f95872d2b27868b6b0c62fae4cb136ad4a42e72d0b611d8f2b  PrimusCentral-0.75-macOS-arm64.dmg
```
