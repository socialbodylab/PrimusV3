# PrimusCentral and DeviceManager v0.98

macOS release built from the V5 unified sender.

Bundled receiver firmware: **Primus 3.14.1**, **Radius 4.1.1** (unchanged from v0.97).

## Headline: launching is no longer silent

These apps are one backend process plus several browser frontends. The launcher
made every attach decision invisibly, and packaged apps are windowed with no
console — so a wrong decision was indistinguishable from "the app won't launch."
Three separate failures in practice traced to this one gap.

A launcher now answers three questions before attaching, and refuses rather than
guessing when it cannot:

| Question | v0.97 | v0.98 |
|---|---|---|
| Is a Central running? | ✅ | ✅ |
| Can it serve **my product**? | ❌ ignored | ✅ checked |
| Can it serve **my capabilities**? | ❌ ignored | ✅ checked |

## What you will notice

- **A window that cannot be raised now tells you where the UI is** instead of the
  app exiting with no feedback. This was the "installed DMG won't launch"
  symptom: the app had attached correctly to a server already holding the port.
- **PrimusCentral opening onto DeviceManager's monitor-only backend** now offers
  **Restart in full mode / Open read-only / Cancel**. Previously it silently
  inherited monitor-only, and every attempt to connect a device returned `409` —
  a PrimusCentral that could not drive a single light, with nothing explaining why.
- **RadiusCentral refuses a non-Radius backend** instead of serving `/radius`
  from Primus state, where it returned HTTP 200 with no audio endpoints and no
  `radius_state` loaded.

## Operator control

```bash
python3 V5/sender/run.py --server-status
python3 V5/sender/run.py --stop-server [--force]
```

`--stop-server` is refused while the server is driving output unless `--force` is
given, so one app can never black out a show another is running. This is also the
supported way to clear an orphaned server holding the port.

New endpoints: `GET /api/server/status` (pid, port, product, monitor_only,
lan_enabled, client sessions, live output, uptime) and `POST /api/server/stop`.
`/api/runtime` is unchanged — it is the discovery probe and stays stable.

## Reliability

- Attaching now reserves a UI session, closing the window where a running Central
  saw zero clients and shut itself down just as a new one arrived.
- The auto-shutdown monitor and `POST /api/server/stop` share one `live_output_fn`,
  so they cannot disagree about whether quitting is safe.
- RadiusCentral gained the idle guard PrimusCentral already had: it will not quit
  while any receiver reports playback.
- The Central registry records capabilities (`monitor_only`, `lan_enabled`,
  `app_version`), not just host and port.

## Validation

- 400 stdlib unittests pass; `py_compile` clean across `V5/sender`
- Verified on hardware against a V1 Huzzah32 and a V2 Feather at 30 fps:
  monitor-only restart takes `connect_all` from **409 to 200**; RadiusCentral
  refuses a Primus backend; `--stop-server` refused while driving and succeeded
  with `--force`
- LaunchServices smoke test on every built app before publishing
- Both apps Developer ID signed with network entitlements, notarized, and stapled
- Both DMGs signed, notarized, stapled, and verified with `hdiutil verify`

## Assets

- `PrimusCentral-0.98-macOS-arm64.dmg`
- `PrimusCentral-0.98-macOS-arm64.dmg.sha256`
- `DeviceManager-0.98-macOS-arm64.dmg`
- `DeviceManager-0.98-macOS-arm64.dmg.sha256`

## SHA-256

```text
PRIMUS_DIGEST  PrimusCentral-0.98-macOS-arm64.dmg
DEVICES_DIGEST  DeviceManager-0.98-macOS-arm64.dmg
```
