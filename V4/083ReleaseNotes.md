# PrimusCentral v0.83

macOS release built from the V4 unified sender (`--product primus`).

## Changes

- **OSC always on all interfaces** — listener binds `0.0.0.0` automatically; accepts `127.0.0.1` locally and LAN IP from remote machines. Host field removed from External Control UI.
- **OSC settings fix** — port no longer saves as `0`; form fields no longer reset while editing.
- **Art-Net routing fix** — retries on default route when preferred interface binding causes errno 65 (no route to host).

## Validation

- `python3 -m unittest discover -s V4/sender/tests`
- `PrimusCentral.app` Developer ID signed, notarized, and stapled
- `PrimusCentral-0.83-macOS-arm64.dmg` signed, notarized, stapled, and verified with `hdiutil verify`

## Assets

- `PrimusCentral-0.83-macOS-arm64.dmg`
- `PrimusCentral-0.83-macOS-arm64.dmg.sha256`

## SHA-256

```text
(checksum added after DMG build)
```
