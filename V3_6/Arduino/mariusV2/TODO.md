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

- [ ] Flash E10 (192.168.8.159) with V4 firmware that includes WAV header read + `softReset()` on sample rate change (`V4/Arduino/radius_receiver/audio.h`)
- [ ] Verify fix: play `hello.wav` (suspected different sample rate) then a second file — subsequent file must play correctly
- [ ] Check serial log for `[Audio] Sample rate change X→Y Hz — soft reset` line on rate transition

### Test suite — mixed sample rate playback

- [ ] Add WAV files at 44100 Hz and 48000 Hz to SD card test fixture (or sender test assets)
- [ ] Write a test (pytest or manual checklist) that plays a 44100 Hz file, then a 48000 Hz file, then a 44100 Hz file again
- [ ] Confirm each file plays at correct pitch and does not leave the device in a stuck state
- [ ] Confirm `sdBusy` is cleared after each track ends (FTP accessible between tracks)
