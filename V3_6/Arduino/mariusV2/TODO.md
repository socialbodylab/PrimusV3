# Marius — TODO

See `MARIUS_REFERENCE.md` for project overview, architecture, `marius.json` format, and action reference.

---

## Phase 1 — BLE scaffolding ✓

- [x] `NimBLE-Arduino` added to `upload.sh` library check list
- [x] `mariusInit()`: NimBLE client (central) role; scan filter matches `puck_name`
- [x] `mariusUpdate()`: scan → connect → subscribe state machine
- [x] Notification callback: buffer bytes, split on `\n`, dispatch complete lines
- [x] Track state: `mariusIsConnected()`, `mariusPuckName()`, `mariusIsActive()`
- [x] `mariusRevert()`: stops BLE for the session without deleting `marius.json`
- [x] `radiusV2.ino`: `mariusLoad()` + `mariusInit()` in `setup()`; `mariusUpdate()` in `loop()`

---

## Phase 2 — JSON loader + audio actions ✓

- [x] `mariusLoad()`: open `/marius.json` from SD with ArduinoJson
- [x] Parse `puck_name`, `actions.press[]`, `actions.release[]`
- [x] Flat C structs (`MariusAction`) — max 8 actions per event
- [x] `mariusIsConfigured()` — true if `marius.json` loaded successfully
- [x] `mariusFireActions()` dispatches `audio_play` / `audio_stop` on press and release
- [x] Volume: explicit 0–100 used; omitted → device's current volume

---

## Phase 3 — Network actions ✓

- [x] `osc` → OSC 1.0 packet; UDP to `target_ip:target_port` (defaults: sender, 53001)
- [x] `artnet_audio` → `ArtAudioCmd` (0x8300); cmds 0–7; UDP to `target_ip:6454`
- [x] `artnet_dmx` → `ArtDmx` (0x5000); single channel; UDP to `target_ip:6454`
- [x] `_mariusResolveTarget()` / `_mariusHasDest()` — routing with sender fallback
- [x] All three types parsed from `_mariusParseActionArray()` with field validation

### Reliability fixes (landed with Phase 3 testing)

- [x] Per-event-type pending flags replace single shared flag — press and release arriving
      in the same BLE notification packet are both dispatched
- [x] `btn/sleep` handler: proactively disconnects and restarts scan to avoid supervision
      timeout delay when user wakes the Puck
- [x] `press_cycle` event: fires one action per press, round-robin through the list
- [x] File-size based hot-reload replaces mtime (ESP32 has no RTC; FAT mtime stays epoch)

---

## Phase 4 — Display + sender UI + editor ✓

- [x] Screen 5 (ESP32-S3 V2): Marius BLE status — state, puck name, last event
- [x] D1 on Screen 5 simulates PRESS; D1 release simulates RELEASE; D2 reverts BLE
- [x] `artnet.py`: parse `MC:0/1` and `MP:name` from ArtPollReply capability tag
- [x] `state.py`: `marius_connected` and `marius_puck` in device state + API response
- [x] `radius.html`: "BLE" badge on audio device card when `marius_connected` is true
- [x] Radius Central Marius tab: device selector, `puck_name` field, press/release action
      editor, move up/down, Save (FTP upload) / Load (FTP download), Export / Import JSON
- [x] `server.py`: `GET /api/marius?ip=...` and `POST /api/marius/push`

---

## Phase 5 — Accel actions (stretch goal)

- [ ] `mariusDispatch()` handles `"accel"` event with parsed x/y/z floats
- [ ] `osc` action for accel: send `/marius/accel` with three float args to sender
- [ ] `audio_play` with `"volume_from": "accel_magnitude"` — map magnitude to volume
- [ ] Rate-limit accel dispatch (Puck sends at 12.5 Hz)
- [ ] Radius Central editor: add Accel event section

---

## Decisions

- **Always-on**: `/marius.json` present at boot activates Marius automatically. Revert is
  session-only (does not delete the file); reboot restores Marius mode.
- **OSC default target**: `senderIP` from Art-Net discovery. Per-action `target_ip` overrides.
- **`artnet_dmx` default**: sender IP. Sender routes to LED devices and tracks state.
- **Accel actions**: deferred to Phase 5. Lines are parsed and logged but not dispatched.
- **Multiple Pucks**: deferred. One Puck per Marius device.

---

## Testing

- [x] Flash Puck.js with `puckjsbutton.js` via espruino CLI
- [x] Confirm `btn/press` / `btn/release` / `accel` lines arrive on Radius serial
- [x] Flash Radius with Marius build; confirm BLE scanning and connects to Puck
- [x] `osc` action with `press_cycle` — `/cue/1` and `/cue/3` alternate on each press
- [x] Sleep: triple-tap sends `btn/sleep`, Radius disconnects and rescans immediately
- [x] Wake: single press calls `NRF.wake()`, Radius reconnects, next press fires cue
- [x] Hot-reload: FTP new `marius.json` → Radius picks up change within 5 s
- [ ] `audio_play` / `audio_stop` on press/release
- [ ] `artnet_audio` — second Radius device plays audio
- [ ] `artnet_dmx` — LED receiver responds

---

## Radius Audio — Pending

### Sample rate bug fix

- [x] Flash E10 (192.168.8.159) with V4 firmware that includes WAV header read + `softReset()` on sample rate change (`V4/Arduino/radius_receiver/audio.h`) — flashed 2026-07-08 with all fixes (sample-rate soft reset, volume-cache mute, audioLoop order, post-connect WiFi.setSleep)
- [ ] Verify fix: play `hello.wav` (suspected different sample rate) then a second file — subsequent file must play correctly
- [ ] Check serial log for `[Audio] Sample rate change X→Y Hz — soft reset` line on rate transition

### Test suite — mixed sample rate playback

Automated in `V4/sender/tests/test_hw_sample_rate.py` (hardware-in-the-loop,
skipped unless `PRIMUS_HW_TEST_IP` is set). It generates and uploads 44100 Hz
and 48000 Hz fixtures, plays 44100 → 48000 → 44100, and detects a wedged SD
bus via a missing 0x8302 "stopped" status corroborated by a blocked FTP
connect (both must fail — telemetry missing alone is UDP loss, reported
separately). Sends a stop command to recover the card before failing.

- [x] Add WAV files at 44100 Hz and 48000 Hz to SD card test fixture (or sender test assets) — generated + FTP-uploaded by the test
- [x] Write a test that plays a 44100 Hz file, then a 48000 Hz file, then a 44100 Hz file again
- [x] Confirm `sdBusy` is cleared after each track ends (FTP accessible between tracks) — asserted by the test
- [ ] Confirm each file plays at correct pitch — needs a human ear; run the test and listen
- [ ] Run against E10 (192.168.8.159) after flashing V4 firmware:
      `cd V4/sender && PRIMUS_HW_TEST_IP=192.168.8.159 python3 -m unittest tests.test_hw_sample_rate -v`

### Audio cues — fade out / fade stop (planned 2026-07-09)

Decision: schema-first (Option C) → firmware ramp (Option A).

- [ ] Add `fade_ms` to the audio cue action schema + Audio Cues / Cue Map UIs
      (field next to Dur/Dly); device cue map schema gets `"fade"`
- [ ] Firmware: extend ArtAudioCmd stop (cmd 0) with optional uint16 fade_ms;
      non-blocking volume ramp in audioUpdate() (linear in the 0-100 domain =
      linear-dB on the VS1053, perceptually correct), audioStop() at zero
- [ ] MUST restore pre-fade volume after the fade completes and keep
      `_lastAppliedVolume` coherent (same failure class as the mute-cache
      silent-playback bug) — add a firmware source contract test
- [ ] Optional interim: sender-side volume-step ramp ("fadestop" in
      fire_audio_cue) works on unflashed fleet; ~90 packets/device for 2 s,
      audible steps on packet loss — rehearsal stopgap only
- [ ] Sibling once the ramp exists: `fade_in` on play (ramp up after
      startPlayingFile)
- [ ] Decide: new play command during an active fade wins instantly
      (recommended) or waits for fade completion
- [ ] Convert cue 99 ALL STOP to a 2 s fade-all once implemented

### Performer / character names + Radius battery (ported 2026-07-11)

Investigated 2026-07-11: origin/main already implemented show info; ported
to radius-central the same day (main's wire protocol kept intact so the
eventual branch merge is clean). Radius battery is new on this branch —
main has battery for Primus only.

Ported/implemented on radius-central:
- ArtShowInfo 0x8210 in both firmware families + sender + all three
  frontends; `POST /api/device_show_info`; NVS storage with read-back
  verification; `show_info_store.py` sender-side backup map
- Radius rv1 battery: `battery.h` port (A13), `B` caps flag, PBT parsing
  in RadiusTelemetryListener, battery chip in Radius/Devices UI
- NOT ported (comes with the merge): flash-time show-info overrides
  (`PRIMUSV3_FORCE_CHARACTER_NAME_OVERRIDE`), rename read-back
  (`sync_device_name_to_receiver`), main's generalized battery.h (ADC
  scale/rail boards), character-name monitor filtering
- rv2 battery still open: needs `Adafruit_MAX1704X` over I2C (0x36) —
  verify the fuel gauge on real hardware first
- [ ] Flash the fleet and verify: names survive reboot, battery shows in
      sidebar on battery power, no audio underruns during playback

- Names: ArtShowInfo opcode **0x8210** (commit a17ad3e, firmware v3.10) —
  character/performer stored in receiver NVS, 64-byte fields, read/write/
  response modes, 143-byte packet, read-back verification (89d6936),
  `POST /api/device_show_info`, inline sidebar editing in both frontends,
  character-name monitor filtering (v0.93), flash-time overrides (v0.95).
  Receiver-NVS design won over the sender-side plan drafted here.
- Battery: main's `battery.h` (since b7644a1, 2026-06-16) is a superset of
  the radius-central copy — configurable ADC scaling + rail-powered board
  support. Main also integrated Radius devices into DeviceManager/
  RadiusCentral (1d8c914).
- Branches diverged at 4b5ede3 (2026-06-15): 62 commits unique to
  radius-central, 52 to origin/main, heavy overlap in V4/sender and
  V4/Arduino/radius_receiver. Merge will conflict; radius-central's VS1053
  silence fixes, FTP cue-reload trigger, and upload.sh consolidation
  (main still has radius_upload.sh) must survive the merge.

### Sender — discovery port race (deferred)

Seen 2026-07-08 during a session with heavy unrelated network traffic:
`OSError: [Errno 48] Address already in use` from `discover_artnet_nodes`
(`V4/sender/artnet.py` — `sock.bind(("", ARTNET_PORT))`). ArtPollReply always
arrives on UDP 6454, the HTTP server is threaded, and discovery runs from
five routes plus startup restore — overlapping calls race for the 6454 bind
and the loser crashes that request (device then looks offline).

- [ ] Serialize `discover_artnet_nodes` with a module-level lock so
      concurrent callers queue instead of raising EADDRINUSE
- [ ] Do NOT use SO_REUSEPORT instead — the kernel load-balances UDP between
      sockets sharing a port, so each discovery would see only a subset of replies
- [ ] Add a two-threads-discover-concurrently regression test (mock
      `_discovery_destinations` to avoid real broadcasts; skip if 6454 unavailable)
