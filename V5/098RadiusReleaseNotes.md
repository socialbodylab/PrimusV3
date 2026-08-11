# RadiusCentral v0.98

macOS release built from the V5 unified sender (`--product radius`).

Version jumps 0.93 → 0.98 to line up with the shared `APP_VERSION` used by
PrimusCentral and DeviceManager. RadiusCentral keeps its own `RadiusCentral-v*`
tag stream.

## Changes

- **Refuses to attach to a non-Radius backend.** Launching RadiusCentral while a
  Primus Central was running silently attached to it and served `/radius` from
  Primus state: HTTP 200, no audio or FTP endpoints, `radius_state` never
  loaded, and nothing telling the user. It now explains the conflict and offers
  to open the running interface or cancel.
- **Idle guard on shutdown.** RadiusCentral previously quit as soon as the last
  window closed, even mid-cue — PrimusCentral has had a guard against this for
  some time. It now stays up while any receiver reports playback, via the new
  `RadiusState.has_live_playback()` (derived from `PTR` telemetry, since playback
  state lives on the device rather than the sender).
- **A window that cannot be raised now reports where the UI is** rather than the
  app exiting silently.
- **Server control**: `GET /api/server/status` and `POST /api/server/stop`, plus
  `run.py --server-status` / `--stop-server [--force]`. Stop is refused while
  audio is playing unless forced.
- Bundle `CFBundleShortVersionString` / `CFBundleVersion` are stamped with the
  release version. Earlier builds reported `0.0.0` to Finder.

## Known limitation

RadiusCentral still **cannot run at the same time as PrimusCentral or
DeviceManager**. It needs its own backend, and the Watch-lane telemetry listener
binds `0.0.0.0:6455` single-owner, so a second backend cannot start. This release
makes that fail *honestly* instead of silently; the real fix is to serve Radius
as a third frontend on one shared backend. See
[V5/RADIUS_INTEGRATION.md](RADIUS_INTEGRATION.md).

## Validation

- 400 stdlib unittests pass; `py_compile` clean across `V5/sender`
- Verified that RadiusCentral refuses a running Primus backend rather than
  serving `/radius` from it
- `RadiusCentral.app` Developer ID signed with network entitlements, notarized, and stapled
- `RadiusCentral-0.98-macOS-arm64.dmg` signed, notarized, stapled, and verified with `hdiutil verify`
- LaunchServices smoke: `open -n V5/dist/macos/RadiusCentral.app --args --port 8098 --no-browser`
  then `curl -s http://127.0.0.1:8098/api/runtime`

## Assets

- `RadiusCentral-0.98-macOS-arm64.dmg`
- `RadiusCentral-0.98-macOS-arm64.dmg.sha256`

## SHA-256

```text
RADIUS_DIGEST  RadiusCentral-0.98-macOS-arm64.dmg
```
