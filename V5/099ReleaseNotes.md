# PrimusCentral, RadiusCentral, and DeviceManager v0.99

macOS release built from the V5 unified sender. **First release where all
three apps ship together under one tag** — the separate `RadiusCentral-v0.9x`
stream ends here.

Receiver firmware published alongside: **Primus 3.14.1**, **Radius 4.20**
(the in-app update check now finds current firmware on GitHub).

## Headline: one backend for all three apps

RadiusCentral no longer runs its own backend. It is a third frontend on the
same server PrimusCentral and DeviceManager share — one process, one device
list, one telemetry listener on UDP 6455 demuxing both product families
(`PST`/`PBT`/`PFP` Primus, `PTR`/`PRS` Radius).

What this fixes, concretely:

- Launching RadiusCentral next to a running PrimusCentral used to silently
  attach it to the wrong backend — a healthy-looking UI where every audio
  route failed. Now there is nothing to mismatch: the shared server serves
  both products, launchers verify the advertised `products` list, and the
  Radius UI shows a blocking banner if it is ever served by a backend that
  cannot answer radius-shaped state.
- Two backends used to race for the single-owner telemetry socket; the loser
  showed every device offline. There is only one listener now.
- `{device: N}` means the same device in every app —
  `GET /api/state?product=radius` returns the radius view of the one shared
  list, indices aligned.

Packaged RadiusCentral data moves into the PrimusV3 app-data tree; legacy
RadiusV3 data is copied forward automatically on first launch (copied, never
deleted).

## Monitoring is passive everywhere

Background device sync (all three apps, every 20 s) discovers and refreshes
but **never connects**. Connecting arms DMX output — which would fight an
external console like EOS or TouchDesigner — so it is always an explicit
operator action. This invariant replaced the old monitor-only mode outright:
every backend now behaves identically no matter which app started it.

## DeviceManager: performer-first Monitor

Cards group by performer (Primus and Radius cards side by side), sorted only
by name/role/stable device id — battery changes, online flapping, and sync
order can never reorder them. Status shows in place (pills, border tints,
per-performer rollup, an "Attention only" filter). Devices without a
performer collect in an Unassigned section; a performer-level Edit identity
panel writes character/performer to all of that performer's devices in one
save. Device identity is keyed off the receiver MAC (`device_uid`), so DHCP
churn no longer scrambles anything.

## RadiusCentral UI parity

DeviceManager-style firmware flow (family toggle defaults to Radius), sidebar
cards with status/battery/firmware and telemetry-driven now-playing, SD
listings loaded on demand instead of stampeding FTP at page load, stable cue
ids with duplicate-number protection, volume controls clamped to the codec's
usable 50–100 range.

## Radius firmware 4.16 → 4.20 (published with this release)

- **4.16** — V5 canonical merge: restored polled audio feeding (interrupt
  feeding cannot work on ESP32), added the PRS battery/status packet, Node
  Report truncation guards, flash-size fix via `build_opt.h`.
- **4.17** — pause no longer self-restarts loops or cleans up one-shots;
  paused tracks hold position and report state 2.
- **4.18** — filenames to 64 chars everywhere (32-char truncation made real
  show files "not found").
- **4.19** — volume cache invalidated when muting behind it (sequential
  playback went silent after the first track).
- **4.20** — decoder soft-reset on explicit stop/track-switch (mid-play
  switches decoded audibly slow).

## Reliability

- Every window opens reliably: per-frontend browser profiles and icons,
  attach opens the requesting app's own frontend, relaunch-after-close fixed
  (stale profile markers and Chromium single-instance handoff both used to
  eat the window).
- No more headless residents: an idle server quits (releasing zombie mixer
  previews that used to block shutdown forever); a server with live output
  reopens its window instead of running invisibly.
- Fixed an HTTP keep-alive regression where most POST routes wrote a stray
  second 404 response, desyncing subsequent requests on the connection.
- Fleet-smear guard restored: post-flash name overrides apply only to the
  flashed device, never the whole online fleet.
- "Sync All" is lane-aware (was hard-coded to port 6454); concurrent FTP
  sessions to one node are serialized; a device with no `/cues.json` opens an
  empty cue table instead of erroring.

## Documentation

The V5 tree now carries the full documentation set for the unified system:
`V5/CHANGES.md` (what changed and what still needs work), `ARCHITECTURE.md`,
`API_REFERENCE.md` (every route), `PORTS_AND_LANES.md`, and updated firmware
references.

## Validation

- 442 stdlib unittests pass; `py_compile` clean across `V5/sender`
- Radius firmware 4.16–4.20 verified on hardware (HUZZAH32 bench unit) with
  real show audio on 2026-08-12; wire-level smoke of the unified backend
  (synthetic PVRAD1 node, PTR/PRS injection, ArtAudioCmd capture, server-stop
  refusal during playback)
- LaunchServices smoke test on every built app before publishing
- All three apps Developer ID signed with network entitlements, notarized,
  and stapled; all three DMGs signed, notarized, stapled, and verified with
  `hdiutil verify`

## Assets

- `PrimusCentral-0.99-macOS-arm64.dmg` + `.sha256`
- `RadiusCentral-0.99-macOS-arm64.dmg` + `.sha256`
- `DeviceManager-0.99-macOS-arm64.dmg` + `.sha256`

## SHA-256

```text
PRIMUS_DIGEST  PrimusCentral-0.99-macOS-arm64.dmg
RADIUS_DIGEST  RadiusCentral-0.99-macOS-arm64.dmg
DEVICES_DIGEST  DeviceManager-0.99-macOS-arm64.dmg
```
