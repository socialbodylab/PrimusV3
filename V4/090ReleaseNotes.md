# PrimusCentral v0.9

macOS release built from the V4 unified sender (`--product primus`).

## Changes

- **Clip preview flicker fix** — hover previews in the Clip Library and Look Designer palette overlay the thumbnail instead of expanding the card, preventing layout reflow and flashing on narrow windows.
- **V4 as canonical PrimusCentral track** — repo docs now point development, packaging, and firmware work at `V4/`; shipped app reports `PrimusCentral v0.9`.
- **UI** — navbar shows `PrimusCentral v0.9`.

## Validation

- `python3 -m unittest discover -s V4/sender/tests`
- `PrimusCentral.app` Developer ID signed with network entitlements, notarized, and stapled
- `PrimusCentral-0.9-macOS-arm64.dmg` signed, notarized, stapled, and verified with `hdiutil verify`

## Assets

- `PrimusCentral-0.9-macOS-arm64.dmg`
- `PrimusCentral-0.9-macOS-arm64.dmg.sha256`

## SHA-256

```text
b845fc7077f7c6512cb1c551a9a290c7a3347afa6a318c9bea560821442b0ad6  PrimusCentral-0.9-macOS-arm64.dmg
```
