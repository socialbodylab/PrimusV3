# PrimusCentral v0.84

macOS release built from the V4 unified sender (`--product primus`).

## Changes

- **Art-Net connect fix** — `ArtOutputConfig`, rename, and other one-shot Art-Net packets now retry on the OS default route when preferred-interface binding causes errno 65 (no route to host). Matches the v0.83 DMX-stream fallback.
- **Cue Controller OSC log** — External Control shows a scrollable incoming OSC log (time, remote address, args, result) plus packet counter and bind-error banner.
- **OSC polling** — Cue Controller refreshes OSC status every 500 ms while active.

## Validation

- `python3 -m unittest discover -s V4/sender/tests`
- `PrimusCentral.app` Developer ID signed, notarized, and stapled
- `PrimusCentral-0.84-macOS-arm64.dmg` signed, notarized, stapled, and verified with `hdiutil verify`

## Assets

- `PrimusCentral-0.84-macOS-arm64.dmg`
- `PrimusCentral-0.84-macOS-arm64.dmg.sha256`

## SHA-256

```text
TBD
```
