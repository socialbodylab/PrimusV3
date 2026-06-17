# PrimusCentral v0.82

macOS release built from the V4 unified sender (`--product primus`).

## Changes

- **OSC LAN listen** — default OSC bind is now `0.0.0.0:53001`, accepting triggers from this Mac (`127.0.0.1`) and other machines on the network. Saved `127.0.0.1` settings migrate automatically on startup.
- **Cue boards** — save/load named cue boards in the Cue Controller.
- **Shared Central lifecycle** — multi-window UI heartbeats keep one backend alive when PrimusCentral and Device Manager are open together; attach mode no longer kills the primary browser window.
- **OSC Cue Sender** — standalone test utility (`V4/tools/osc_cue_sender/`) with live target addressing and raw debug OSC send.

## Validation

- `python3 -m unittest discover -s V4/sender/tests`
- `PrimusCentral.app` Developer ID signed, notarized, and stapled
- `PrimusCentral-0.82-macOS-arm64.dmg` signed, notarized, stapled, and verified with `hdiutil verify`

## Assets

- `PrimusCentral-0.82-macOS-arm64.dmg`
- `PrimusCentral-0.82-macOS-arm64.dmg.sha256`
