# PrimusCentral v0.8

macOS release built from the V4 unified sender (`--product primus`).

## Changes

- **V4 PrimusCentral packaging** — signed/notarized app bundles the V4 sender, web UI, starter clips/looks/cues, and `V4/Arduino/` firmware sources.
- **Default brightness 40%** — new Clips, Looks, and designer output defaults start at 40% instead of 100%.
- **Cue Controller fix** — Edit Cue dialog now restores the saved Look instead of defaulting to the first dropdown item.
- **V1 firmware 3.7.0** — battery telemetry (`PBT` on UDP 6455, capability `F:RIOHB`), V1 default outputs (Badge + Collar), and bundled firmware sources for in-app flashing.
- **Device card UI** — compact battery percentage readout and per-port output type dropdowns without reflash.
- **Transport stability** — UDP send failures (including macOS broken pipe) no longer drop live device connections during streaming or output changes.

## Validation

- V1 firmware compile verified before release build (`./V4/Arduino/upload.sh -v1 --compile`).
- `PrimusCentral.app` was Developer ID signed, notarized, stapled, and accepted by Gatekeeper.
- `PrimusCentral-0.8-macOS-arm64.dmg` was signed, notarized, stapled, verified with `hdiutil verify`, and accepted by Gatekeeper.

## Assets

- `PrimusCentral-0.8-macOS-arm64.dmg`
- `PrimusCentral-0.8-macOS-arm64.dmg.sha256`

## SHA-256

```text
199432d3b304e45ca7df4030e1be0c85eae9914e0a07974f1cd5a4acbe10919e  PrimusCentral-0.8-macOS-arm64.dmg
```
