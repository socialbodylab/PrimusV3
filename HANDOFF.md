# Session Handoff — overnight-radius-integration (2026-08-12)

**Purpose of this file:** everything a fresh session needs to finish and ship
this branch. The full narrative lives in `OVERNIGHT_REPORT.md` (overnight
build) and the commit messages (each one explains its why); this is the
pickup guide.

## Where things stand

Branch `overnight-radius-integration` (28 commits over checkpoint `6c863f5`
on `port-organization`), fully pushed to origin. **441 tests green.**
Everything below is implemented, unit-tested, live-smoke-tested, AND
manually verified by Nick on real hardware today unless marked otherwise.

- **Unified backend**: one server process serves /primus, /radius, /devices;
  one device list (`ControllerState`, radius records tagged `is_radius`,
  connected-by-default for radius since their flag gates one-shot audio not
  DMX); one telemetry listener demuxing PST/PBT/PFP/PTR/PRS on 6455;
  launcher/registry advertise `products: ["primus","radius"]`.
- **Passive monitoring, no modes**: `/api/devices/sync` never auto-connects
  (external consoles own production color); connecting is an explicit
  operator action; monitor-only mode retired.
- **DeviceManager**: performer-grouped Monitor (stable ordering via
  `device_uid` from the ArtPollReply MAC), Unassigned section, group-level
  Edit identity, mixed Primus+Radius firmware upload.
- **RadiusCentral**: full parity UI (DM-style firmware flow, telemetry
  cards without fps, on-demand SD listings, telemetry-driven now-playing,
  stable cue ids, 50-100 volume clamp — the VS1053 scale makes lower values
  inaudible; kept V4-compatible on purpose).
- **App lifecycle (packaged)**: cross-frontend attach opens the right
  window; per-frontend Chromium profiles + per-page app icons; relaunch
  after close works (liveness-checked markers, no single-instance handoff —
  fresh profile subdir per attach launch); last-window-close quits an idle
  server in ~10 s, releases zombie mixer previews, and REOPENS the window
  when output is genuinely live (no headless residents).
- **Radius firmware 4.20** on the bench unit (E8, 192.168.8.157) —
  canonical source `V5/Arduino/radius_receiver/`. Version ledger, all
  found on hardware today: 4.16 PRS battery/status telemetry + V5 merge;
  4.17 pause fix; 4.18 64-char filenames; 4.19 volume-cache mute fix;
  4.20 decoder soft-reset on mid-play track switch (slow-playback fix).
  PTR byte-frozen; PRS layout in `V5/FIRMWARE_REFERENCE.md`.
- Apps built unsigned at `V5/dist/macos/` from head — these are TEST builds.

## Next session: the release train

1. **Version bump**: `V5/sender/version.py` APP_VERSION is 0.98.
   PrimusCentral + DeviceManager share one `v0.9x` tag stream — pick the
   next free number in that stream (check existing git tags, don't
   increment per-product). RadiusCentral tags separately as
   `RadiusCentral-v0.9x`.
2. **Sign + notarize** all three apps (identity
   `Developer ID Application: Nicholas Puckett (SAV2V7GXQ5)`, profile
   `PrimusCentral Notary`) — full commands + DMG method in CLAUDE.md
   §Packaging. Packaged-FPS validation must launch via Finder/
   LaunchServices, never the bare binary.
3. **Firmware releases**: publish Primus 3.14.1 and Radius 4.20 to GitHub
   releases — the in-app "Check for Updates" compares against GitHub, where
   the latest published is 3.11.0, so other machines can't get current
   firmware until this happens.
4. **Fleet reflash**: remaining Radius units → 4.20 over USB
   (`./V5/Arduino/radius_upload.sh -v1 --auto`, one unit at a time).
5. **PR to main**: `overnight-radius-integration` → `main`
   (https://github.com/socialbodylab/PrimusV3/pull/new/overnight-radius-integration).

## Known-open items (not blockers)

- **Marius/Puck.js pairing untested** since NimBLE peripheral/broadcaster
  roles were compiled out for flash space (`build_opt.h`) — needs a Puck in
  hand. Compile-verified only.
- **RADIUS_DIAG loop-timing measurement** never run on hardware (flash once
  with `-DRADIUS_DIAG=1`, confirm loopMaxUs < ~8000 during playback with
  Marius configured).
- PrimusCentral's own sidebar still shows Radius devices with LED-ish
  controls (pre-existing; DeviceManager is the intended mixed view).
- Packaged RadiusCentral data now lives under the PrimusV3 app-data tree
  (legacy RadiusV3 data auto-copied on first run, never deleted).
- Remote-backend future: `V5/REMOTE_BACKEND_NOTES.md` — audit, structural
  items, and standing rules for interim work.
- Bench unit E8 still carries test artifacts: `hwtest.wav` on its SD and
  show-info "HW-Test / Bench Rig".

## Doc map

- `CLAUDE.md` — updated to current architecture (read first).
- `V5/FIRMWARE_REFERENCE.md` — PTR/PFP/PRS byte layouts, Node Report order,
  filename/volume rules, pause semantics.
- `V5/RADIUS_INTEGRATION.md` — mixed monitoring + performer Monitor contract.
- `V5/REMOTE_BACKEND_NOTES.md` — remote-backend readiness.
- `OVERNIGHT_REPORT.md` — the overnight build story + original checklist.
