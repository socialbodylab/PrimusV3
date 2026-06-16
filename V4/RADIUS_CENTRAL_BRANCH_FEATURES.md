# Radius Central — `origin/radius-central` Feature Inventory

This document summarizes features found on the **`origin/radius-central`** branch (fetched June 2026) and compares them to the current **V4** Radius Central track at `V4/sender/`.

The branch integrates Radius into **V3_6 Primus Central** (`run.py --mode radius` → `/radius` SPA). V4 is a **standalone** sender with its own app bundle, V1-only firmware, and a Primus-styled UI at `/`.

**Port status (June 2026):** All branch features listed below as implemented on `origin/radius-central` @ `cc0e6e9` have been ported into V4, except **pull sync** and **conflict resolve** (push-only by design). V4 also keeps **Firmware** and **Settings** tabs the branch radius UI lacked. Per-device cue firing is implemented correctly in V4 (`fire_audio_cue` honors `actions[ip]`).

---

## Branch architecture (how it differs from V4)

| Aspect | `origin/radius-central` | V4 (current) |
|--------|-------------------------|--------------|
| Code location | `V3_6/sender/` shared with Primus | `V4/sender/` standalone |
| Entry point | `python3 V3_6/sender/run.py --mode radius` | `python3 V4/sender/run.py` or `RadiusCentral.app` |
| UI route | `/radius` → `radius.html` | `/` → `index.html` |
| UI modes | Audio, Audio Cues, Cue Map, Net Log | Audio, Audio Cues, Cue Map, Net Log, Firmware, Settings |
| Firmware UI | **Not** in `radius.html` (Primus firmware panel exists in main `index.html` only) | Full firmware panel (V1 profile) |
| Hardware target | Radius V1 + V2 (`-rv1`, `-rv2` in `V3_6/Arduino/upload.sh`) | Radius V1 only (`V4/Arduino/radius_receiver/`) |
| Art-Net opcodes | `0x8300` ArtAudioCmd, `0x8301` ArtFtpCmd (remapped on branch) | Same opcode range |
| FTP credentials | Documented as `radius` / `radius` in API docs | `radius` / `radius` in code |
| State file | Primus `.primus_state.json` | `.radius_state.json` |

---

## UI features on `radius-central`

### 1. Audio panel (`web/js/audio-panel.js`, mode: **Audio**)

Per-node SD card file manager and transport controls.

- **Transport:** Stop, Pause, volume slider (debounced ArtAudioCmd volume)
- **Now playing:** Local UI state for active file + play/loop indicator
- **File manager:** Breadcrumb navigation, folder create, rename, delete, refresh
- **WAV playback:** Play and Loop buttons on `.wav` entries only
- **Upload:** Drag-and-drop + click-to-upload with per-file progress bar
- **Device filter:** Sidebar and panel show only `is_audio` devices

**V4 status:** Implemented (same `audio-panel.js` pattern wired into `index.html`).

**Branch-only sidebar detail:** Hello button on connected nodes sends test tone with current volume (`POST /api/hello_device` + optional `volume`).

**V4 status:** Implemented (Hello button in sidebar; volume from shared `Alpine.store("audio")`).

---

### 2. Audio Cues panel (`web/js/audio-cues.js`, mode: **Audio Cues**)

Sender-side **cue sheet** stored in `audio_cues.json` (not on device SD). Production-oriented “fire cue N” workflow.

- **Cue sheet CRUD:** Numbered cues (1–255), optional note, auto-increment on add, debounced save (500 ms)
- **Per-device actions (UI model):** Each cue holds `actions: { [device_ip]: { cmd, filename, volume, duration } }`
  - Commands: `none`, `play`, `loop`, `stop`
  - Filename chosen from project library dropdown
  - Volume 0–100, duration seconds (0 = full file — UI field present; backend wiring unclear)
- **Fire cue:** `POST /api/audio_cues/fire` with per-device result badges (sent / skipped / error), auto-clear after 3 s
- **Import / export:** Download JSON attachment; upload JSON to replace sheet
- **Project audio library (UI column):**
  - List WAV files in sender `audio/` folder
  - Import WAV (client-side RIFF/WAVE header check)
  - Delete from library (does not delete from device SD)
- **Sync All button:** Opens modal; runs background push sync job with per-device/per-file progress
- **Device status column:** Online/offline indicator for each Radius node

**V4 status:** Implemented (`audio_cues.py`, panel, APIs, push sync). Per-device `actions[ip]` honored in `fire_audio_cue()`.

**Branch caveat (fixed in V4):** UI stores **per-IP actions**, but `state.fire_audio_cue()` on the branch still reads **top-level** `cue.cmd` / `cue.filename` / `cue.volume` and broadcasts the same command to all connected audio devices.

---

### 3. Cue Map panel (`web/js/cue-map.js`, mode: **Cue Map**)

Edits **`/cues.json` on the device SD card** (firmware-local cue map), separate from sender `audio_cues.json`.

- Device selector (audio nodes only)
- Load map via `GET /api/audio/cue_map?device=N` (FTP download)
- Load WAV list from device root for file picker
- Table editor: cue number (1–64), filename, duration (seconds; 0 = full file)
- Reorder rows (move up/down), add/remove rows
- Save via `POST /api/audio/cue_map` → writes `/cues.json` over FTP
- Note in UI: changes take effect after **device reboot**

**Firmware support (branch):** `V3_6/Arduino/radiusV2/cues.h` loads `/cues.json` at boot; cue numbers 1–255, max 64 entries; supports string or `{file, duration}` object form.

**V4 status:** Implemented (`cues.h` on V1 firmware, Cue Map panel, `/api/audio/cue_map`).

---

### 4. Network Log panel (`web/js/net-log.js`, mode: **Net Log**)

Live Art-Net / FTP event trace for debugging shows.

- Polls `GET /api/netlog?since=<id>` every 500 ms
- Ring buffer (1000 entries server-side)
- Typed events: ArtPoll, PollReply, rename, output config, audio_cmd, FTP ctrl/upload/rename/delete/mkdir/sync, FPS telemetry
- Auto-scroll toggle, Clear (`POST /api/netlog/clear`), Download JSON export
- Optional FPS filtering (sampled to 1 Hz per IP in `netlog.log_fps`)

**V4 status:** Implemented (`netlog.py`, artnet instrumentation, Net Log panel).

---

### 5. Styling notes

- Branch `radius.html` uses Primus navbar/sidebar/panel structure (same class names as V3_6).
- Dedicated CSS for audio file manager, cues, sync modal, and log rows lives on **`origin/feature/audio-playback`** (`V3_1/sender/web/css/style.css`), not fully merged into V3_6 CSS on `radius-central`. Some panels may render with minimal styling until those rules are ported.
- V4 copied V3_6 `style.css` and appended audio-specific rules (`.audio-fm-*`, `.cues-*`, `.sync-*`, `.log-*`) from `origin/feature/audio-playback`.

---

## Backend / API features on `radius-central`

### Device & network (shared with Primus V3_6)

Present on branch and largely **present in V4:**

- Art-Net discovery, connect/disconnect, rename (`ArtAddress`)
- Static IP / DHCP via ArtIPConfig (`0x8200`)
- Network settings panel APIs (`/api/network/*`)
- `is_audio` flag when node name/capabilities indicate Radius
- Audio devices excluded from ArtDmx pixel send loop (Primus state); V4 has no DMX loop by design

**V4 additions not on branch radius UI:**

- PTR telemetry (UDP 6455) → `current_track` in device state
- PVRAD1 capability tag parsing (V4 firmware)
- Packaged app lifecycle (dedicated browser window, UI heartbeat shutdown)

**Branch-only device feature:**

- `POST /api/hello_device` → **test tone** (ArtAudioCmd cmd 5) for `is_audio` devices instead of LED identify flash; optional `volume` in request body

**V4 status:** Implemented (`POST /api/hello_device`).

---

### Per-device SD management (ArtFtpCmd `0x8301`)

| Endpoint | Purpose | V4 |
|----------|---------|-----|
| `POST /api/audio/cmd` | play / loop / stop / pause / volume / test_tone | Yes |
| `POST /api/audio/upload?device=N&path=/file.wav` | Binary WAV upload | Yes |
| `POST /api/audio/files` | Directory listing | Yes |
| `POST /api/audio/rename` | Rename file or folder | Yes |
| `POST /api/audio/delete` | Delete file or folder | Yes |
| `POST /api/audio/mkdir` | Create folder | Yes |
| `GET /api/audio/cue_map?device=N` | Read `/cues.json` from SD | Yes |
| `POST /api/audio/cue_map` | Write `/cues.json` to SD | Yes |

---

### Sender-side audio cue sheet (`audio_cues.py`)

| Endpoint | Purpose | V4 |
|----------|---------|-----|
| `GET /api/audio_cues` | Load cue sheet | Yes |
| `POST /api/audio_cues` | Save cue sheet | Yes |
| `GET /api/audio_cues/export` | Download JSON attachment | Yes |
| `POST /api/audio_cues/import` | Replace cue sheet from JSON body | Yes |
| `POST /api/audio_cues/fire` | Fire cue by number | Yes |

**Persistence (branch):**

- `audio_cues.json` in sender data directory
- `audio/` project library folder
- `audio/.checksums.json` SHA-256 cache
- `audio/.tmp/` staging for pull conflict resolution

**Library helpers (branch):** checksum validation, duplicate-name conflict detection (`ChecksumConflictError`), temp staging + `resolve_project_audio_temp()` for merge conflicts.

---

### Project audio library & sync

Documented in branch `API_REFERENCE.md` §15; partially implemented in server code.

| Feature | Endpoint(s) | V4 |
|---------|-------------|-----|
| List library (+ device inventory metadata) | `GET /api/project_audio` | Yes |
| Upload WAV to library | `POST /api/project_audio?filename=` | Yes |
| Delete from library | `DELETE /api/project_audio/<name>` | Yes |
| **Push sync** (library → all connected nodes) | `POST /api/audio_sync`, poll `GET /api/audio_sync/status` | Yes |
| **Pull sync** (nodes → library) | `POST /api/audio_sync/pull` | **No** (documented; **not found** in branch `server.py`) |
| Resolve pull conflicts | `POST /api/audio_sync/resolve` | **No** (documented; **not found** in branch `server.py`) |

**Push sync behavior (branch, implemented):**

1. Stop all audio devices (cmd 0), wait 300 ms for SD bus
2. Collect filenames referenced by cue sheet actions
3. FTP-list each connected `is_audio` device
4. Upload missing files from project library with byte progress callbacks
5. Log sync events to netlog (`ftp_sync` type)

---

### Network log API

| Endpoint | Purpose | V4 |
|----------|---------|-----|
| `GET /api/netlog?since=N` | Incremental log fetch | Yes |
| `POST /api/netlog/clear` | Clear buffer | Yes |

Requires `netlog.log()` calls throughout `artnet.py` / server sync paths on the branch.

---

## Firmware & tooling on `radius-central`

### Present on branch, different from V4

- **`V3_6/Arduino/radiusV2/`** — ESP32-S3 Reverse TFT Radius V2 sketch with `cues.h`, SD cue map, VS1053 audio, FTP server
- **Upload profiles:** `-rv1` (HUZZAH32), `-rv2` (S3 TFT) in shared `V3_6/Arduino/upload.sh`
- **Primus receiver firmware** still available (`-v1`, `-v2`, `-v3`) in same tree
- **`tools/radius_test.py`** — CLI diagnostic (play/stop/tone/vol/ftp list/ping); uses **legacy** opcode `0x8200` and FTP user `primus` in that file (predates branch opcode remap)

### Present in V4, not on branch radius UI

- **Firmware panel** in web UI (compile/upload, WiFi/name/IP overrides)
- **V4-only V1 firmware** at `V4/Arduino/radius_receiver/` with NVS network config, PVRAD1 tag, PTR telemetry, `RADIUS_DIAG`
- **Packaged macOS app** (`RadiusCentral.app`) with LaunchServices-friendly browser launch

---

## Tests on `radius-central` (Radius-relevant)

Branch adds dedicated tests under `V3_6/sender/tests/`:

- `test_radius_audio_cmd.py`, `test_radius_ftp_paths.py`, `test_radius_is_audio.py`, `test_radius_tick_skip.py`
- `test_audio_cues_library.py` — checksum cache, project library save/delete, temp staging, conflict resolve, cue sheet roundtrip

V4 has **48 tests** under `V4/sender/tests/` including `test_audio_cues_library.py`, `test_fire_audio_cue.py`, `test_server_audio_routes.py`, and extended artnet coverage.

---

## Port complete (V4 ← branch)

All items from the recommended port list below were implemented in V4 (June 2026). Remaining intentional gaps: pull sync, conflict resolve, Radius V2 hardware profile.

~~1. **Audio Cues panel + `audio_cues.py`**~~ ✓  
~~2. **Project library + push sync**~~ ✓  
~~3. **Cue Map panel + `/api/audio/cue_map`**~~ ✓  
~~4. **Hello / test tone**~~ ✓  
~~5. **Net log**~~ ✓  
~~6. **Audio-specific CSS**~~ ✓  
7. **Pull sync + conflict resolve** — out of scope for V4

---

## Recommended port priority (V4 ← branch) — historical

If aligning V4 with the branch’s audio production workflow:

1. **Audio Cues panel + `audio_cues.py`** — highest user-visible gap; fix `fire_audio_cue` to honor per-device `actions[ip]` when porting
2. **Project library + push sync** — enables “Sync All” before show
3. **Cue Map panel + `/api/audio/cue_map`** — requires confirming V4 V1 firmware loads `/cues.json`
4. **Hello / test tone** — small API + sidebar button
5. **Net log** — debugging aid; requires artnet instrumentation
6. **Audio-specific CSS** — port `.audio-fm-*`, `.cues-*`, `.sync-*`, `.log-*` blocks from `origin/feature/audio-playback` CSS
7. **Pull sync + conflict resolve** — only if needed; design exists in API docs but server implementation was not found on the branch tip

---

## Source file index (`origin/radius-central`)

| Area | Key paths |
|------|-----------|
| Radius SPA | `V3_6/sender/web/radius.html` |
| Audio panel JS | `V3_6/sender/web/js/audio-panel.js` |
| Audio cues JS | `V3_6/sender/web/js/audio-cues.js` |
| Cue map JS | `V3_6/sender/web/js/cue-map.js` |
| Net log JS | `V3_6/sender/web/js/net-log.js` |
| Cue sheet + library | `V3_6/sender/audio_cues.py` |
| Net log backend | `V3_6/sender/netlog.py` |
| HTTP routes | `V3_6/sender/server.py` |
| State / fire cue | `V3_6/sender/state.py` |
| API docs | `API_REFERENCE.md` (§13 Audio, §15 Library Sync) |
| Radius V2 firmware cues | `V3_6/Arduino/radiusV2/cues.h` |
| CLI tool | `tools/radius_test.py` |

---

*Generated from inspection of `origin/radius-central` @ `cc0e6e9` vs V4 workspace, June 2026.*
