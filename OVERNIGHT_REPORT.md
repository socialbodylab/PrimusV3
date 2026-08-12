# Overnight Report — 2026-08-12 — Radius Integration

Branch: **`overnight-radius-integration`** (your working tree was first checkpointed as
`6c863f5` on `port-organization`, so nothing pre-existing was lost; revert is one
`git checkout port-organization` away).

## What you asked for, and what happened

| Goal | Status |
|---|---|
| RadiusCentral as PrimusCentral's twin on the shared backend (**must-have**) | ✅ Done, live-verified |
| Radius firmware caught up to V5 + telemetry that never preempts audio | ✅ Done, compile-verified (flash tomorrow) |
| DeviceManager monitoring by performer, stable ordering, unassigned tab | ✅ Done, browser-verified |
| RadiusCentral UI audit + parity (telemetry, firmware flow like DeviceManager) | ✅ Done, browser-verified |
| Shared API / interfaces / firmware that work together | ✅ One backend, one device list, one telemetry listener |

All work is committed in eight commits on the branch. The full unit suite is green —
**428 tests** (baseline was 412) — plus a live 26-point end-to-end smoke test and
browser verification of all three frontends running off **one** server process.

## The architecture that landed

**One backend, three launchers.** `run.py --product radius` no longer starts a separate
server: it boots (or attaches to) the same unified backend PrimusCentral and
DeviceManager use, with `/radius` as its frontend — exactly the DeviceManager pattern.
`ControllerState` now carries the full lane-aware Radius audio/FTP surface
(`send_audio_command`, `ftp_*`, `fire_audio_cue`), the single telemetry listener
demuxes `PST/PBT/PFP/PTR/PRS` on port 6455, and `GET /api/state?product=radius`
serves the radius-shaped view with device indices aligned across every frontend.
The launcher/registry now advertises `products: ["primus", "radius"]`; a backend that
can't serve the requested product produces a dialog offering **Restart shared server**
— never a silent attach — and the Radius UI shows a blocking banner if it's ever
served by a non-radius-capable backend. Legacy standalone mode remains behind
`PRIMUSV3_RADIUS_STANDALONE=1`. Packaged RadiusCentral data (RadiusV3 tree) is
auto-copied into the unified tree on first launch, and device lists saved by the old
standalone backend are imported on startup.

**Stable device identity.** Discovery now parses the MAC from ArtPollReply
(bytes 201-206) into `device_uid` (persisted; `ip:<addr>` fallback). This is the key
performer grouping and card state hang off, so DHCP churn no longer scrambles anything.

## Radius firmware 4.16 (`V5/Arduino/radius_receiver/` is now canonical)

- **Fixed a real defect:** the V5 tree's interrupt-driven audio feed is broken on
  ESP32 (ISR can't take SPI semaphores) — V4's polled `audio.h` restored wholesale,
  along with WAV validation, the SD/hardware readiness split, hiss-kill on stop, and
  the sineTest SCI-write hazard fix.
- **New PRS status packet** (17 bytes, 1 Hz, MAC-jittered, anti-phased from the PTR
  tick): sequence, uptime, flags (wifi/static/test/battery-valid/SD/FTP/playing/
  looping/Marius), RSSI, battery. Battery is one ADC sample per second with an EMA on
  the stock A13 divider — provably inside the VS1053's ~11.6 ms feed budget. **PTR is
  byte-frozen**; nothing existing changes.
- Loop hardening: extra `audioUpdate()` calls after Marius and the UDP drains; Marius
  BLE connect (blocks ~5 s) now deferred while audio plays; buttons compiled out on
  HUZZAH32 (they shared pins with SD/VS1053 chip-selects); `senderIP` re-latches on
  real controller packets instead of the first packet ever.
- Node Report reordered `F:` first with the whole-token guard (features can no longer
  be silently truncated); features now `RIHASB`; `|V:4.16` restored.
- Flash overflow solved by compiling out unused NimBLE roles (`build_opt.h`) — v1 now
  has **more** headroom than the shipped baseline. Compiles: radius_v1 99%, radius_v2 45%.

## DeviceManager — performer-first Monitor

Cards group by performer (Primus card + Radius card side by side), sorted only by
name/role/uid so **battery, online flapping, errors, and sync order can never reorder
them**. Status lives in the cards (pills, border tints, per-performer rollup,
"Attention only" filter). Devices without a performer sit in an **Unassigned** section;
inline-editing a performer name there moves them into their group. A performer-level
**Edit identity** panel writes character/performer to all of that performer's devices
in one save, with datalists of known names. Dead bulk-action UI removed.

## RadiusCentral UI

Firmware tab is now the DeviceManager step flow (family toggle correctly defaults to
Radius — this exposed and fixed an Alpine init race that could have offered Primus
profiles); sidebar cards show status pill, battery, FPS, firmware version, and
telemetry-driven now-playing; the Audio tab derives playback from PTR/PRS instead of
an optimistic local flag; SD file listings load on demand instead of stampeding FTP at
page load; audio cues have stable ids + duplicate-number protection; all
`alert()`-style errors now flow through the app's notice system; Net Log polls only
while open.

## Bugs found and fixed along the way

1. **Fleet-smear regression** — V5 had dropped V4's guard, so post-flash name
   overrides were pushed to *every online device* (the failure your xlsx-restore tool
   exists to repair). Guard restored in both states.
2. **"Sync All" used hard-coded port 6454** for stop/list/upload — broken for any
   node with moved lanes. Now lane-aware.
3. **Concurrent FTP sessions to one node tore each other down** (Cue Map's parallel
   load) — per-device FTP serialization added.
4. A node with no `/cues.json` returned a 500 — now opens an empty editable table.
5. RadiusCentral's firmware job log never auto-scrolled (missing `x-ref`).

## Synthetically verified tonight

- 428 unit tests green (14 new shared-backend tests + DM contract/runtime tests).
- Live smoke, 26/26: synthetic PVRAD1 node added, MAC→uid, PTR/PRS injected over UDP
  and visible in both state views, ArtAudioCmd captured on the wire with correct
  bytes, cue fire, and `/api/server/stop` refusing (409) during radius playback then
  allowing after stop.
- Browser: `/radius`, `/primus`, `/devices` all served by one process; DM performer
  grouping + identity editor round-trip against the live API.

## ⚠️ Must verify physically tomorrow (cannot be done synthetically)

1. **Flash 4.16 to ONE HUZZAH32 first.** Verify WAV play/loop/pause/test-tone, FTP
   transfer, no audible dropouts. Optional: flash once with `-DRADIUS_DIAG=1` and
   confirm `loopMaxUs` stays under ~8000 µs during playback with Marius configured.
2. PRS packets at ~1 Hz on 6455 with sane battery mV/%, and switch-off detected ~2 s
   after flipping the power switch.
3. **Marius/Puck.js still connects** with NimBLE peripheral/broadcaster roles compiled
   out, and a connect attempt no longer interrupts playback.
4. Discovery shows `F:RIHASB` / `V:4.16`; a lane moved via 0x8220 advertises its token.
5. Launch RadiusCentral while PrimusCentral is running → it should attach to the
   shared server and be fully functional (audio, cue map, battery on cards).
6. Real fleet in DeviceManager: groups by performer, cards stay put as battery/status
   change; old-firmware nodes degrade gracefully (blank battery, PTR-only now-playing).
7. Old 0.98 PrimusCentral + new RadiusCentral → dialog offers "Restart shared server",
   no silent attach.

## Decisions you may want to review

- Packaged RadiusCentral now lives in the PrimusV3 data tree (legacy data auto-copied,
  never deleted).
- The identity editor flattens differing character names across one performer's
  devices on save (mixed state is shown in the heading first).
- PrimusCentral's own sidebar still shows Radius devices with LED-ish controls
  (pre-existing mixed-fleet behavior; DeviceManager is the intended mixed view) —
  candidate for a follow-up polish pass.
- Radius PFP always reports 0 fps by design; the radius card shows it. Cosmetic.
