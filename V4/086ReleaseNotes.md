# PrimusCentral v0.86

macOS release built from the V4 unified sender (`--product primus`).

## Changes

- **OSC multi-interface listener** — binds UDP on all interfaces, each active LAN IP, and loopback with `SO_REUSEPORT` so remote packets reach the listener on multi-homed Macs.
- **OSC network log** — Cue Controller shows bind results, socket list, and per-packet local/LAN receipt for debugging.
- **No OSC host setting** — only enable and port are configurable; host bind is always automatic.
- **Packaging fix** — signs the inner app executable with network entitlements before the bundle; embeds app version at build time.
- **UI** — navbar shows `PrimusCentral v0.86`.

## Validation

- `python3 -m unittest discover -s V4/sender/tests`
- `PrimusCentral.app` Developer ID signed with network entitlements, notarized, and stapled
- `PrimusCentral-0.86-macOS-arm64.dmg` signed, notarized, stapled, and verified with `hdiutil verify`

## Assets

- `PrimusCentral-0.86-macOS-arm64.dmg`
- `PrimusCentral-0.86-macOS-arm64.dmg.sha256`

## SHA-256

```text
TBD
```
