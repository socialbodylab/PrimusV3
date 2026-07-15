# PrimusCentral v0.85

macOS release built from the V4 unified sender (`--product primus`).

## Changes

- **OSC LAN receive fix** — signed app now includes incoming-network entitlements so remote OSC packets reach the listener (local `127.0.0.1` worked before; LAN did not under hardened runtime).
- **Cue Controller OSC debug panel** — larger incoming log with Time / Source / Message / Result columns, LAN target addresses, and local vs LAN packet counters.
- **OSC diagnostics** — millisecond timestamps, up to 100 log entries, firewall hint when only local packets are received.

## Validation

- `python3 -m unittest discover -s V4/sender/tests`
- `PrimusCentral.app` Developer ID signed with network entitlements, notarized, and stapled
- `PrimusCentral-0.85-macOS-arm64.dmg` signed, notarized, stapled, and verified with `hdiutil verify`

## Assets

- `PrimusCentral-0.85-macOS-arm64.dmg`
- `PrimusCentral-0.85-macOS-arm64.dmg.sha256`

## SHA-256

```text
befc10f4ca6cec7d21481527edb0b5f7036b0cf51de6c1dc4fe7f29ccedc3ad8  PrimusCentral-0.85-macOS-arm64.dmg
```
