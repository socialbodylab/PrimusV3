# V5 — What changed and why (2026-08-12)

This document marks the point where V5 became the shared base for everyone's
work. Primus and Radius were built by different people on different branches,
and until now they met only at the network protocol. The
`overnight-radius-integration` branch (32 commits, merged to `main` on
2026-08-13) ended that split: **one backend process now serves all three
apps**, one device list models both product families, and the firmware for
both families lives canonically under `V5/Arduino/`.

Read this first; the reference docs carry the detail:

| Topic | Doc |
|---|---|
| How the backend is put together now | [ARCHITECTURE.md](ARCHITECTURE.md) |
| Every HTTP endpoint | [API_REFERENCE.md](API_REFERENCE.md) |
| UDP ports and lanes | [PORTS_AND_LANES.md](PORTS_AND_LANES.md) |
| Firmware behavior, byte layouts, capability tags | [FIRMWARE_REFERENCE.md](FIRMWARE_REFERENCE.md) |
| Primus firmware internals map | [PRIMUS_FIRMWARE_MAP.md](PRIMUS_FIRMWARE_MAP.md) |
| Mixed Primus/Radius monitoring | [RADIUS_INTEGRATION.md](RADIUS_INTEGRATION.md) |

Everything below was verified against a 442-test suite plus live browser and
wire-level smoke tests. Radius firmware 4.16–4.20 was additionally verified on
real hardware (bench unit E8) on 2026-08-12. Items that could **not** be
verified are listed under [What still needs work](#what-still-needs-work).

---

## The unified backend

**Before:** PrimusCentral and DeviceManager shared one server; RadiusCentral
ran its own separate backend (`RadiusState`). Starting RadiusCentral while a
Primus server was running silently attached it to the wrong backend — the UI
loaded and looked healthy, but every audio route failed. Worse, both backends
wanted the same UDP 6455 telemetry socket, which is single-owner: whoever
bound it second simply got no telemetry. There was no fix inside the
two-process model; the second process was the bug.

**Now:** RadiusCentral is a third frontend on the one shared server, exactly
the way DeviceManager already was. Concretely:

- `run.py --product radius` no longer starts a Radius backend. It flips the
  process to the `primus` product with `/radius` as the default frontend and
  delegates to `run_primus.main()`. One process serves `/primus`, `/radius`,
  and `/devices`.
- **One device list.** `ControllerState` models Radius devices as records
  tagged `is_radius: true`. They never get an `ArtNetSender` and are excluded
  from the DMX tick by explicit guards; they carry `current_track` and
  `playback_state` instead. `ControllerState` also gained the full lane-aware
  Radius command surface — `send_audio_command`, `fire_audio_cue`, and the
  `ftp_*` family — so every audio and FTP route works on the shared server.
- **One telemetry listener.** `PrimusTelemetryListener` binds UDP 6455 once
  and demuxes all five magics: `PST`/`PBT`/`PFP` (Primus) and `PTR`/`PRS`
  (Radius). The port conflict is gone by construction, not worked around.
- **`GET /api/state?product=radius`** returns the radius-shaped view. It
  deliberately returns **all** devices, radius-shaped, so array indices mean
  the same thing in every frontend; the Radius UI filters on `is_radius`
  client-side. `{device: N}` in any API call now refers to the same device no
  matter which app sent it.
- **Loud launchers.** The registry (`central_server.json`) and `/api/runtime`
  advertise `products: ["primus", "radius"]`. A launcher that needs a product
  the running server can't serve gets a dialog — Restart shared server /
  Cancel — never a silent attach. A backend that won't say what it serves is
  treated as a mismatch too. The Radius UI double-checks by verifying that
  `/api/state?product=radius` actually answers with `product: "radius"` and
  shows a blocking banner if not.
- **Data migration.** Packaged RadiusCentral data now lives in the PrimusV3
  app-data tree. On first launch, legacy `RadiusV3` data (`.radius_state.json`,
  `audio_cues.json`, the `audio/` library) is copied across — copied, never
  moved or deleted — and device lists saved by the old standalone backend are
  imported at startup.
- **Escape hatch.** `PRIMUSV3_RADIUS_STANDALONE=1` still runs the legacy
  separate `RadiusState` backend. It exists for tests and as a fallback; it
  has not been kept feature-current with the unified path (see
  [What still needs work](#what-still-needs-work)).

Radius records default to `connected: true` on discovery. This is deliberate
and differs from Primus: the Radius connected flag gates one-shot audio
commands, not a standing DMX stream, and defaulting it off would silently
no-op cues after every restart.

## Monitoring is passive — the mode is gone

`POST /api/devices/sync` (the 20-second background sync every frontend runs)
is now discovery-and-refresh **only**, on every backend, no matter which app
started it. It never connects devices. Connecting is what arms DMX output —
the tick then streams frames including keepalive blackouts, which would fight
an external console (EOS, TouchDesigner) that owns production color — so it is
always an explicit operator action.

This one invariant replaced the old `monitor_only` mode and its
restart-in-full-mode launcher choreography. Every backend now behaves
identically; DeviceManager no longer needs to be special to be safe. The
`--monitor-only` flag is still accepted (it 409s `/api/connect` for scripts
that relied on that), but nothing injects it anymore.

Sync calls also **coalesce** now: three frontends each polling every 20 s used
to stack 3.5-second discovery sweeps behind one lock; concurrent callers now
share a single in-flight sweep's result.

## Stable device identity

Discovery parses the MAC address from ArtPollReply bytes 201–206 into
`device_uid` (falling back to `ip:<addr>`), and it persists across restarts.
Performer grouping in DeviceManager and all client-side card state hang off
this key, so DHCP churn, battery changes, or online/offline flapping can never
reorder or reset anything in the Monitor view.

## Radius firmware: 4.16 → 4.20

All five versions landed on 2026-08-12. 4.16 was the overnight merge; 4.17
through 4.20 were each found and fixed the same day by hands-on testing with
real show audio on the bench unit. `V5/Arduino/radius_receiver/` is the
canonical source; the fleet should be flashed to **4.20**.

**4.16 — the V5 merge, and telemetry that never preempts audio.** The V5 copy
of the sketch had interrupt-driven audio feeding, which cannot work on ESP32
(SPI takes FreeRTOS semaphores; an ISR may not). V4's polled feed was restored
wholesale, along with WAV validation, the SD-ready/hardware-ready split, and
hiss-kill on stop. On top of that:

- New **PRS status packet** (17 bytes, 1 Hz): sequence, uptime, flags
  (SD/FTP/playing/looping/Marius/test-tone), RSSI, and battery. Battery is one
  ADC sample per second with an EMA — deliberately *not* the Primus 8-sample
  pattern, which blocks ~16 ms while the VS1053's FIFO drains in ~11.6 ms.
  The whole 4.16 design constraint was that nothing may block longer than
  that: extra `audioUpdate()` calls after Marius and UDP drains, BLE connect
  deferred while audio plays, buttons compiled out on the HUZZAH32 (they
  shared pins with the SD and VS1053 chip-selects).
- **PTR is byte-frozen** — nothing existing changed.
- Node Report rewritten with the whole-token-or-nothing guard and `F:` early
  (a truncated `|MGMT:645` parses as a plausible port and black-holes Setup
  traffic). Features became `RIHASB` — `B` is battery.
- Flash overflow solved by `build_opt.h`, which compiles out NimBLE's
  peripheral/broadcaster roles (Marius only needs scanner + client). Do not
  delete that file; without it the v1 build no longer fits.

**4.17 — pause actually pauses.** The Adafruit library clears its "playing"
flag on pause, so 4.16 treated a paused track as ended: a paused loop
restarted itself, a paused one-shot got cleaned up. Pause is now tracked
explicitly; PTR reports state 2 with the track name held. There is no resume
command — resume is "send Play again".

**4.18 — 64-character filenames.** Real show files
(`Radius_Overature_soundscapetocrackle.wav`) failed with "file not found":
the 32-char cap lived in three places (sender packet builder, firmware parse,
firmware buffers) that all truncated independently. Everything now agrees
on 64, matching the PTR clamp and show-info fields.

**4.19 — sequential playback went silent.** Three paths mute the codec
directly (track end hiss-kill, pause, the test tone's internal reset) behind a
volume-write cache. The next play at an unchanged volume matched the cache,
skipped the hardware write, and decoded into silence — while telemetry
honestly reported "playing". The mute paths now invalidate the cache.

**4.20 — track switches played slow.** Aborting a WAV mid-stream leaves the
VS1053 with stale stream state; the next track decoded at the wrong rate.
Explicit stops and mid-play switches now soft-reset the decoder (~100 ms,
never in the streaming path; natural track end doesn't need it).

**Companion finding — the volume scale.** The volume byte maps linearly onto
the codec's full 127 dB attenuation range, so the bottom half of the scale is
effectively silent (measured: 80 ≈ −25 dB, 50 ≈ −64 dB, 30 ≈ silence). The
mapping was deliberately kept — existing cue tuning survives — and the UIs
clamp volume input to 50–100 instead.

Also found on hardware the same day, sender-side: newer SimpleFTPServer builds
emit tab-separated LIST lines, which the parser silently dropped — the SD
browser came up empty against a real card. The parser handles both formats
now (tabs also preserve filenames containing spaces) and skips macOS dotfile
junk.

## Primus firmware: where it stands

This branch changed no Primus firmware. The current version is **3.14.1**, and
it matters to this story because the lanes work happened there:

- **3.12** moved `F:` (feature flags) to the front of the Node Report. The
  report is a hard 64-byte Art-Net field; `F:` was written last and silently
  truncated away under routine conditions, demoting devices to "unconfirmed
  legacy hardware" with every capability disabled.
- **3.14.0** added the versioned management protocol (opcode `0x8140`):
  GET_CONFIG, output descriptors, atomic CRC'd NVS records, the 28-byte `PST`
  status packet, and production mode with the 60-second boot unlock window.
- The **lane split** (Show 6454 / Setup 6457 / Watch 6455) shipped after
  3.14.0 **without a version bump** — two materially different firmwares both
  report 3.14.0. If a device says 3.14.0, you cannot tell from the version
  string whether it binds a Setup lane; the `L` feature flag is the truth.
- **3.14.1** fixed the regression the lane split introduced: it advertised
  `SHOW:/MGMT:/TELE:` unconditionally, and that 30-byte triple alone overflowed
  the Node Report on every device, silently dropping `IP:`, `U:`, `G:` and all
  per-output tuples. The fix: the `L` flag means "lane-aware", lane tokens are
  emitted only for a lane moved off its default, and every token appends
  whole-or-not-at-all. See [PORTS_AND_LANES.md](PORTS_AND_LANES.md).

## Ports and lanes

The full treatment is in [PORTS_AND_LANES.md](PORTS_AND_LANES.md); the short
version: receiver traffic is split into three UDP lanes — **Show** (6454
Primus ArtDmx / 6456 Radius audio), **Setup** (6457, all commissioning and
config), and **Watch** (6455, telemetry back to the sender) — so a burst of
setup traffic can never sit in front of show data in a socket queue, and
firewall rules can say something meaningful. Every lane port is overridable
and persisted in device NVS; discovery advertises only lanes moved off their
defaults. Both firmwares currently run **dual-listen** (Setup opcodes are
still accepted on the Show lane) as the migration bridge — and that bridge is
load-bearing today, see below.

## The apps (packaged lifecycle)

A run of fixes made the three packaged apps behave like real citizens when
sharing one backend:

- Each frontend gets its own Chromium profile and window, with its own app
  icon. Attaching to a running server opens the *right* frontend's window
  instead of focusing whichever one existed.
- Relaunch-after-close works. Stale profile markers and Chromium's
  single-instance handoff both used to eat the window (the app "launched" to
  nothing); attach launches now use a fresh profile subdir every time, and
  liveness is judged by processes, not marker files.
- An idle server (no UI windows, no live output) quits itself after a short
  grace period — and before judging "idle" it releases zombie mixer previews
  that used to hold servers alive forever. If output *is* live, the server
  refuses to die headless and **reopens its window** instead. No more
  invisible resident apps driving costumes.
- The auto-quit monitor and `POST /api/server/stop` share one
  `live_output_fn` — Primus show output OR any Radius device reporting
  playback — so they can never disagree about whether quitting is safe. Both
  fail toward "live".
- Orphaned servers are operator-recoverable: `run.py --server-status` and
  `--stop-server [--force]`.

## API changes

The full endpoint-by-endpoint reference is [API_REFERENCE.md](API_REFERENCE.md)
— it now documents the entire surface (111 routes), including ~25 that were
never written down anywhere. Highlights of what changed on this branch:

- **New:** `GET /api/state?product=radius` (radius-shaped shared state),
  `products[]` and `server_control` in `/api/runtime`, richer
  `/api/server/status`.
- **Changed:** `/api/devices/sync` never connects (its `connected` result
  field is always empty now); `GET /api/audio/cue_map` returns `{}` instead of
  a 500 for a missing/corrupt `/cues.json`; sync calls coalesce.
- **Newly documented, previously invisible:** the device management surface
  (`device_full_config`, `device_lock_state`, `enter_device_production_mode`,
  `unlock_device_boot_window`, `device_show_info`, `set_device_telemetry_target`,
  `apply_device_output_descriptor`), lane ports (`/api/network/lane_ports`,
  `/api/device_lane_ports`), output presets, cue boards, the serial monitor,
  and the UI lifecycle heartbeats.
- The server speaks HTTP/1.1 with keep-alive now (it was
  connection-per-request before). This branch initially shipped a bug where
  ~60 POST routes wrote a stray second 404 response onto the kept-alive
  socket, desyncing the next request; fixed and regression-tested
  (`tests/test_http_keepalive.py`) before release.

## Bugs found and fixed along the way

Worth recording because each one says something about the system:

1. **Fleet smear regression** — V5 had dropped V4's guard scoping post-flash
   name overrides to the flashed device, so a reflash pushed name overrides to
   *every online device*. Guard restored.
2. **"Sync All" hard-coded port 6454** for stop/list/upload — broken for any
   node with moved lanes. Now lane-aware.
3. **Concurrent FTP sessions to one node tore each other down** (the Cue Map
   panel loads in parallel). Per-device FTP serialization added.
4. A node with no `/cues.json` returned a 500; now an empty editable table.
5. The keep-alive double-response bug above.

## What still needs work

The honest list. None of these block using V5 as the shared base; all of them
should be known before building on the relevant area.

**Protocol / firmware**

- **Dual-listen is still load-bearing for Radius Setup traffic.** The audio
  half was fixed on 2026-08-13 (a token-less Radius node's audio now resolves
  to 6456, matching the fix first made on the `radius-central` branch), but a
  token-less node's *Setup* traffic still resolves to the Show port and lands
  only because `PORT_DUAL_LISTEN=1` accepts it — Radius has no `L`-flag
  equivalent. Flipping the flag off still requires that gap closed first.
  The rest of the `radius-central` branch should still be diffed against
  main by its owner.
- ~~The `G:` capability token is parsed, despite comments saying otherwise~~ —
  **fixed in firmware 3.14.2** (2026-08-13): `G:` now rides directly behind
  `B:`, where it always fits, since the sender gates `management_supported`
  on it. Devices on 3.14.0/3.14.1 (which emitted it last and could silently
  lose management under a crowded Node Report) should be reflashed — only
  two units ever received 3.14.1.
- **Primus replies are pinned to literal 6454** (ArtPollReply, management
  replies, show-info responses) rather than the runtime Show port. Move the
  Show lane and the node answers on the old port.
- **Radius `0x8220` (lane move) is fire-and-forget** — no ACK, and the sender
  applies the change optimistically. A dropped packet leaves sender and node
  split-brained on the Setup port. Port validation also differs across the
  three layers (global profile / per-device API / firmware), so some inputs
  pass the sender and are rejected by the device.
- **Watch-port changes are not paired**: changing the sender's Watch port
  needs a process restart to rebind, and nothing pushes `portWatch` to
  receivers — either direction of change can silently lose telemetry.
- Radius emits a 46-byte `0x8302` audio-status packet nothing parses, and that
  packet still truncates filenames at 32 chars (everything else moved to 64).
- Radius has no production lock — any host on the LAN can move a Radius
  node's lanes or rewrite its config with one unauthenticated UDP packet.

**Untested (needs hardware)**

- **Marius/Puck.js pairing** has not been tested since the NimBLE
  peripheral/broadcaster roles were compiled out for flash space.
  Compile-verified only; needs a Puck in hand.
- **`RADIUS_DIAG` loop timing** has never been measured on hardware. The
  "telemetry never preempts audio" claim rests on reasoning and budgets, not
  measurement. Flash once with `-DRADIUS_DIAG=1` and confirm `loopMaxUs`
  stays under ~8000 during playback with Marius configured.
- The v1 Radius build sits at 99% flash. The next meaningful addition
  overflows it again.

**Backend**

- **`run_radius.py` (the standalone escape hatch) has drifted**: no window
  reopen, no `products`/`lan_enabled` registration, and its mismatch dialog
  still describes the pre-unification world. Treat it as legacy; don't extend
  it.
- **No auth anywhere**, by policy, on the isolated-show-network assumption —
  but DeviceManager's own fresh backend now binds the LAN by default
  (`--lan`, for the Mobile View), which exposes firmware flash, device FTP,
  and server stop to the whole network. The levers and the decision point are
  written down in [REMOTE_BACKEND_NOTES.md](REMOTE_BACKEND_NOTES.md) — decide
  the hardening story in the same change that widens any bind.
- Several persistence paths swallow `OSError` silently (device state,
  show-info, groups) — a full disk loses state with no signal.
- PrimusCentral's own sidebar still shows Radius devices with LED-ish
  controls. Pre-existing; DeviceManager is the intended mixed view.
- `/api/state` polling rates were tuned for loopback (100 ms Primus, 500 ms
  Radius, 1 s Devices). Fine today; the wrong shape for remote clients —
  see REMOTE_BACKEND_NOTES.md before adding more polling.

## Release ledger

- **Apps v0.99** (2026-08-13): first release where PrimusCentral,
  RadiusCentral, and DeviceManager ship together under one tag, all built from
  this unified tree. Earlier: PrimusCentral/DeviceManager shared the `v0.9x`
  stream (0.97, 0.98 from V5) while RadiusCentral tagged separately as
  `RadiusCentral-v0.9x` — that split ends here.
- **Primus receiver firmware 3.14.2** and **Radius receiver firmware 4.20**
  published to GitHub releases (the in-app update check compares against
  GitHub, which had been sitting at 3.11.0).
- Remaining: reflash the Radius fleet to 4.20 over USB
  (`./V5/Arduino/radius_upload.sh -rv1 --auto`, one unit at a time), and the
  hardware verification items above.
