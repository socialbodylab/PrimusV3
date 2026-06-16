# PrimusCentral v0.81

macOS release built from the V4 unified sender (`--product primus`).

## Changes

- **Device Manager** — new `/devices` frontend with filterable device grid, network sync on load, and standard device-card actions.
- **Shared Central server** — launchers attach to an already-running backend instead of replacing it; open Primus, Radius, or Device Manager views against one server with `--frontend`.
- **macOS dropdown fixes** — Look Designer Clips output type, Effect/Playback selects, Cue Controller group/target/look dropdowns, device-card output type, and related dynamic `<select>` controls now use reliable WebKit-safe binding.
- **Shared device UI** — extracted `device-conn.js` for consistent device management across Primus, Radius, and Device Manager views.

## Validation

- `python3 -m unittest discover -s V4/sender/tests`
- `PrimusCentral.app` Developer ID signed, notarized, and stapled
- `PrimusCentral-0.81-macOS-arm64.dmg` signed, notarized, stapled, and verified with `hdiutil verify`

## Assets

- `PrimusCentral-0.81-macOS-arm64.dmg`
- `PrimusCentral-0.81-macOS-arm64.dmg.sha256`

## SHA-256

```text
99b5a52b8495e9dc3f6dd0cd300ecb009c87895d4040dc2c277bf4e28105ad9a  PrimusCentral-0.81-macOS-arm64.dmg
```
