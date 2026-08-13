# PrimusV3 — Repository Analysis

*Generated 2026-07-06 from analysis of the working tree at `main` (tag `v0.92`).*

This document is a snapshot orientation for the PrimusV3 monorepo. It is deliberately written to be read before the existing docs (README.md, CLAUDE.md, API_REFERENCE.md), which it summarizes and cross-references. It is **not** authoritative for protocol or behavior — when this document and the per-track docs disagree, the per-track docs win.

---

## 1. Overview

### What the project is
PrimusV3 is a **WiFi-controlled LED + audio lighting system for live performance costumes**, built by the Social Body Lab. A Python "sender" running on a controller computer (laptop) drives **ESP32 receiver nodes** over **Art-Net (UDP 6454)**. The receivers drive NeoPixel LED costumes, and (in the Radius product line) play audio from SD cards.

It is a research / artistic-instrument project, not a general-purpose product. It is private/unlicensed, intended for the lab's own performances and workshops.

### The shape of the system
```
  Controller computer                    Dedicated WiFi router                 Performers (costumes)
 ┌─────────────────────────┐             ┌──────────────────┐                ┌──────────────────────┐
 │  Python "sender"        │  WiFi/Eth   │                  │   WiFi         │  ESP32 receiver node │
 │  + web UI (browser)     ├────────────►│  show router     ├───────────────►│  2× NeoPixel outputs │
 │  PrimusCentral / Radius │             │                  │   ◄ FPS/diag   │  (and Radius audio)  │
 └─────────────────────────┘             └──────────────────┘   UDP 6455     └──────────────────────┘
        ▲                                                                          
        │ OSC UDP 53001  (optional show-control: QLab, TouchDesigner, etc.)                  
        └───────────────────────────────  external tools                               
```

Two products are built from **one Python codebase** (the V4 unified sender):

| Product | Domain | Web UI |
|---------|--------|--------|
| **PrimusCentral** | LED lighting — clips / looks / cues | `/primus` |
| **RadiusCentral** | Audio playback — audio cues / cue map / net log | `/radius` |
| **DeviceManager** | PrimusCentral's discovery/firmware/settings front-end as its own app | `/devices` |

### The non-negotiable design rules
These rules explain a lot of otherwise-surprising code decisions and are worth knowing up front:

- **No external Python dependencies in the sender.** Python 3 stdlib only. OSC parsing, Art-Net framing, FTP, the HTTP server — all hand-rolled. This is the single biggest constraint on the architecture.
- **Table-driven output types on both sides.** Sender `OUTPUT_TYPES` dict + `LOOK_OUTPUT_TYPES` list (Python) ↔ C++ `OutputType` enum + `OUTPUT_TYPE_TABLE`. Adding a type is "one row each."
- **Standard Art-Net for LED data.** Any Art-Net controller (TouchDesigner, MadMapper, etc.) can drive the nodes directly. Primus-specific behavior lives in **custom opcodes (0x8000+)** and a **discovery capability tag** so non-Primus controllers never need to know about them.
- **Brightness is sender-side RGB scaling only.** The receiver LED driver stays at 255. The old receiver brightness-byte protocol is intentionally dead — do not revive it.
- **Brightness, clip/look sharing, and discovery metadata all live in V3.6+ protocol semantics** (covered below).

---

## 2. Repository Structure & History

### Version tracks (kept as parallel trees in one repo)
The repo uses **top-level version directories** rather than branches or tags-as-folders. Older versions are kept as historical references.

| Dir | Role | Status |
|-----|------|--------|
| `V4/` | **Canonical sender + packaging tree** (PrimusCentral + RadiusCentral + DeviceManager) | Active. All shipping releases v0.81+ built from here. |
| `V3_6/` | V3.6 protocol/source reference and the historical release line (v0.65–v0.7) | Historical. Still documents the Art-Net protocol; runnable from source for comparison only. |
| `V3_5/`, `V3_1/`, `V3_0/` | Earlier modular and single-file senders | Archived; see `PreviousVersions.md`. |

### Git shape
- **Remote:** `github.com/socialbodylab/PrimusV3.git`
- **Branch:** `main` is the only long-lived working branch.
- **Tags:** 16 version tags from `v0.5` (2026-04-14) → `v0.92` (2026-07-04, current HEAD).
- **Release cadence:** Roughly weekly-to-biweekly through April–July 2026, accelerating in June (v0.8 → v0.86 in ~5 days).
- **Branches present on origin:** mostly `copilot/*`, `cursor/*`, `claude/*` experiment branches plus `feature/audio-playback` and a personal `marius` branch — i.e. **agent-assisted development** and feature work, not a long-lived PR workflow.

### V4 layout (the tree that matters)
```
V4/
├── sender/                      Unified Python sender (the product)
│   ├── run.py                   Entry point; dispatches on --product / bundle name
│   ├── run_primus.py            PrimusCentral launcher + wiring
│   ├── run_radius.py            RadiusCentral launcher + wiring
│   ├── central_launcher.py      Single-instance detection; multi-frontend attach
│   ├── server.py                HTTP server + full JSON API (1453 lines)
│   ├── state.py                 Primus runtime: output tables, animation tick, ArtDmx loop (2067 lines)
│   ├── radius_state.py          Radius runtime: audio/FTP/cues
│   ├── artnet.py                Art-Net protocol (discovery, ArtDmx, custom opcodes) (1136 lines)
│   ├── osc_control.py           Inbound OSC for cue triggers (stdlib OSC 1.0 subset)
│   ├── controller.py            Cue list + per-pixel crossfade + auto-follow
│   ├── mixer.py                 Look timeline resolution
│   ├── clips.py, effects.py     Clip storage + effects engine
│   ├── sharing.py               Portable clip/look bundle import/export
│   ├── firmware.py              Firmware profiles + UI job runner
│   ├── firmware_source.py       Independent receiver-firmware-update fetcher (v0.92)
│   ├── network_settings.py      Show-router network config + static IP tooling (1105 lines)
│   ├── paths.py                 Cross-platform app-data path resolution
│   ├── netlog.py, serial_monitor.py, cue_boards.py, ui_lifecycle.py
│   ├── web/                     Static Alpine.js SPAs (no build step)
│   └── tests/                   26 stdlib unittest modules
├── Arduino/
│   ├── primusV3_receiver/       Primus LED firmware (profiles v1/v2/v3)
│   ├── radius_receiver/         Radius audio firmware (radius_v1)
│   ├── upload.sh                Primus compile/upload script
│   └── radius_upload.sh         Radius compile/upload script
├── build_sender_app.py          PyInstaller packaging (--product primus|radius, macOS+Windows)
├── build_firmware_bundle.py     GitHub-released firmware zip + SHA-256 sidecar (v0.92)
├── tools/osc_cue_sender/        Standalone OSC test utility
├── dist/                        Build output (.app / .exe / .dmg)
├── ARCHITECTURE.md, FIRMWARE_DEVELOPMENT.md, PACKAGING.md
└── 0xxReleaseNotes.md           One per release (081, 082, …, 092)
```

### Documentation map
| Doc | When to read it |
|-----|-----------------|
| `README.md` | Project overview, quick start, packaging marker. Start here. |
| `CLAUDE.md` | Agent context — conventions, sync points, runtime diagnostics. **Read this before editing.** |
| `API_REFERENCE.md` | The Art-Net wire protocol, discovery fields, custom opcodes, HTTP API, OSC. Authoritative for protocol. |
| `V4/README.md` + `V4/ARCHITECTURE.md` | The unified-sender design and product split. |
| `V4/PACKAGING.md` | macOS/Windows build, signing, notarization, DMG. |
| `V4/FIRMWARE_DEVELOPMENT.md` | Firmware profiles, opcodes, hardware notes. |
| `V3_6/SENDER_DEVELOPMENT.md` / `FIRMWARE_DEVELOPMENT.md` | Historical but still the best deep protocol reference. |
| `BOARD_UPLOAD_README.md` | First-time board-upload setup. |
| `PreviousVersions.md` | What V3.0 and V3.1 were. |

---

## 3. Current State

### Versioning
- **App version: `0.92`** (`V4/sender/version.py`). Tagged `v0.92` on 2026-07-04, the current HEAD.
- **Bundled receiver firmware: `v3.9.0`** (V3 custom PCB profile) — but as of v0.92 firmware is **no longer tied to the app version** (see §3.A below).
- Shipped apps report as `PrimusCentral`, `RadiusCentral`, and `DeviceManager` with bundle IDs `com.socialbodylab.{PrimusCentral,RadiusCentral}`.

### 3.A. The v0.92 architectural change — decoupled firmware updates ⚑

**v0.92 is the most important release in the recent arc.** It changes the project's release *model*, not just its features. Before v0.92, the ESP32 receiver firmware was **bundled inside each signed/notarized app release** — shipping a firmware fix required cutting a whole new macOS+Windows app build, re-signing, re-notarizing, and shipping a new DMG/installer. v0.92 **breaks that coupling**: receiver firmware is now its own independently-versioned release stream that the app fetches from GitHub at runtime.

**What shipped:**

| Piece | File(s) | Role |
|-------|---------|------|
| **GitHub release assets** | `V4/build_firmware_bundle.py` → `PrimusReceiverFirmware-<semver>.zip` + `.sha256` | One zip per firmware version, attached to a GitHub release, decoupled from any app version. Carry `upload.sh` + the `primusV3_receiver/` sketch. |
| **In-app update client** | `V4/sender/firmware_source.py` (389 lines, new) | Scans the GitHub releases API for `PrimusReceiverFirmware-(\d+\.\d+\.\d+)\.zip`, picks the highest non-draft semver, fetches the matching `.sha256` sidecar, compares to the installed version (15-min response cache). |
| **New firmware job action** | `V4/sender/firmware.py` — `action:"download_firmware"` | Downloads the zip, **verifies SHA-256**, extracts into app-data, atomically swaps `active` ↔ `active_backup`, writes a `manifest.json`, and chmods `upload.sh`. Exposed via `POST /api/firmware/jobs`. |
| **Bundled vs active resolution** | `V4/sender/paths.py` — `firmware_dir()`, `firmware_active_dir()`, `bundled_arduino_dir()` | Bundled firmware (read-only, in the app bundle) is the fallback. A downloaded bundle in `<app-data>/firmware/active/` takes precedence if it has an `upload.sh`. The runtime picks active-if-present, else bundled. |
| **Firmware UI** | `V4/sender/web/js/firmware.js`, `index-primus.html` | Shows installed version + source (`bundled` vs `downloaded`), latest available version, "update available" status, and a **Download** button. |

**Where firmware now lives at runtime** (`paths.py`):
- Bundled (fallback): inside the `.app`/`.exe` → `Arduino/primusV3_receiver/`.
- Downloaded (preferred): `~/Library/Application Support/PrimusV3/firmware/active/` (macOS) or `%APPDATA%\PrimusV3\firmware\active\` (Windows), tracked by `manifest.json` and `update_cache.json`. In source runs, the equivalent is `<repo>/.firmware/`.
- Downloads cached in `<firmware>/downloads/`, atomic swap via `active/` + `active_backup/` staging.

**Why it matters:**
1. **Firmware can ship without an app release.** A board fix, new output profile, or battery-telemetry tweak becomes a GitHub release asset, not a full app rebuild.
2. **Versions are now two-dimensional.** The app has its version (`0.92`); the receiver firmware has its own independent semver (`3.9.0`). `/api/firmware/status` reports both: `firmware.{version, source}` (installed) and `update.{local_version, remote_version, update_available}` (GitHub scan).
3. **Integrity is enforced.** Every downloaded bundle must match a GitHub-published `.sha256` sidecar (`_verify_file_sha256` raises on mismatch); extraction is path-traversal-guarded (`_safe_zip_extract`).
4. **Primus only.** `check_github_updates()` short-circuits to `{enabled: false}` when `sender_product() != "primus"` — RadiusCentral does not get this feature.
5. **Bundled firmware still works offline.** A fresh install with no network still has v3.9.0 in the bundle; the downloaded layer is purely additive.

**The same release also ships bundled firmware v3.9.0** — the V3 custom-PCB profile (`PRIMUS_PROFILE_V3_1`) with direct NeoPixel outputs on A0/A1 (GPIO17/18), battery telemetry on A4 (5V rail via 100k/100k divider), TFT status screens, and capability flags `RIOHBM`. The V1 Huzzah32 profile also gained battery monitoring (A13, `F:RIOHB`). The 1813-line v0.92 commit spans firmware (`config.h`, `battery.h`, `buttons.h`, `display.h`, the `.ino`), the new update pipeline, packaging docs, and a 210-line test module (`test_firmware_updates.py`).

### 3.B. The DeviceManager app

v0.91–v0.92 also formalize a **third app**, DeviceManager, built from the same V4 unified sender. It is PrimusCentral's device-discovery/connect/rename/IP/output-config/firmware front-end exposed as its own app bundle (`DeviceManager.app`, bundle id `com.socialbodylab.DeviceManager`), launched via `run_devices.py` which sets `PRIMUSV3_SENDER_PRODUCT=primus` and `PRIMUSV3_DEFAULT_FRONTEND=devices` and serves the `/devices` frontend (`index-devices.html`). Because all three apps share one backend, launching DeviceManager while PrimusCentral is running *attaches* to the existing server rather than starting a second one (`central_launcher.py`).

### Platforms & packaging
- **macOS (primary):** Developer ID signed, notarized, stapled DMG. arm64. Built via `V4/build_sender_app.py --target macos`.
- **Windows (secondary):** PyInstaller exe + Azure Artifact Signing installer (`--windows-installer`). Added around v0.86+.
- **Packaged macOS has timing protections** that must be preserved: `caffeinate -dimsu -w <pid>` process assertion, `pthread_set_qos_class_self_np` user-interactive QoS on animation/mixer threads, and low-latency frame pacing with a spin tail. **Packaged FPS validation must go through Finder/LaunchServices**, not direct binary execution — a v0.65 regression specifically reproduced only under LaunchServices.
- **Do not reintroduce** the raw `objc_msgSend`/`ctypes` app-activity bridge — it previously crashed the packaged app (SIGSEGV).

### What is mature / stable
- Art-Net protocol, discovery + capability tags, custom opcodes (rename, IP config, output config, receive mode config, FPS/battery telemetry).
- The **Clips → Looks → Cues** PrimusCentral workflow (Designer / Mixer / Controller).
- Discovery + connect/rename/IP-config/output-config device management, capability-aware with legacy fallback.
- Inbound OSC cue triggering (QLab-style) on UDP 53001.
- Portable clip/look sharing bundles.
- Radius: audio cue sheet, per-device actions, push sync to SD via FTP, device-side `/cues.json` cue-map editor.
- macOS+Windows signed/notarized packaging with checksum sidecars.
- **v0.92 introduced independent receiver firmware updates** — the Firmware page can fetch GitHub-released `PrimusReceiverFirmware-*.zip` assets and install them without upgrading PrimusCentral itself.

### What is explicitly NOT done / known limits
- **Radius push sync only.** Pull sync and conflict resolution are intentionally not implemented (push-only by design).
- **Radius firmware is V1 only** in V4 (`radius_v1`: HUZZAH32 + Music Maker). The older `radius-central` branch had V1+V2; that hasn't been ported.
- **Future unification is optional/unfinished** (per ARCHITECTURE.md): single merged device state, merged Primus+Radius web UI, shared run loop. Today they are two backends behind one HTTP server, with product-specific routes returning 503 when their backend isn't running.
- The repo carries a lot of **historical/duplicate trees** (`V3_6/`, `V3_5/`, `V3_1/`, `V3_0/`) and `previousHardware/V1`, `V2` — kept for reference, but new work should land in `V4/`.

### Uncommitted / in-flight (from `git status` at analysis time)
- Modified: `V3_6/sender/cues.json`.
- Untracked: `.cursor/`, `.firmware/`, `V4/sender/.central_server.json` (runtime registry — expected), `howToGuide.md` (empty), and two new docs: `V3_6/ARTNET_EXTERNAL_INTEGRATION.pdf` and `V3_6/WINDOWS_AZURE_SIGNING.md`.

### Recent release narrative (v0.81 → v0.92)
The last ~6 weeks of releases trace a clear arc:
1. **v0.81–v0.86** — Move PrimusCentral shipping to the V4 unified sender; multi-interface OSC listen; Cue Controller network log; Art-Net connect routing fallback; Windows installer fixes; clip-preview flicker fix.
2. **v0.9** — V4 declared the canonical track; packaged app labeled `PrimusCentral v0.9`; Windows signed release.
3. **v0.91** — Receive-mode (split/combined universes) via new opcode 0x8110, firmware v3.8.0 with V3 TFT receive-mode display, Hello serial monitor, and the first **DeviceManager.app** release.
4. **v0.92 (the inflection)** — **Decouples receiver firmware from app releases** via GitHub-served `PrimusReceiverFirmware-*.zip` bundles checked/downloaded/SHA-256-verified in-app (§3.A). Ships bundled firmware **v3.9.0** adding the **V3 custom PCB** profile (direct NeoPixel on A0/A1, battery telemetry on A4, TFT screens) and V1 battery telemetry (A13). Adds `build_firmware_bundle.py` and `firmware_source.py`. DeviceManager ships as a full peer to PrimusCentral. This is the release that changes *how the project ships*, not just what it does.

---

## 4. Key Workflows

### 4.1 Content workflow: Clips → Looks → Cues (PrimusCentral)

This is the conceptual core of the LED side. Each receiver node has **2 outputs (A0, A1)**, each independently assignable to an output type. Content is layered three deep:

| Layer | Concept | Built in | Stored as |
|-------|--------|----------|-----------|
| **Clip** | The smallest unit — one effect (colors, speed, params) for one output type | **Designer** panel | `V4/sender/clips/<id>.json` |
| **Look** | A timeline arrangement of clips across **both** outputs — what every port shows at once | **Mixer** panel | `V4/sender/looks/<id>.json` |
| **Cue** | A production trigger that fires one or more Looks (or a blackout), with crossfade, auto-follow, and per-device/group targeting | **Controller** panel | `V4/sender/cues.json` |

```
 Designer → Clips ─┐
                   ├─→ Mixer → Looks ─→ Controller → Cues ──GO──→ ArtDmx → nodes
 Designer → Clips ─┘
```

Key details:
- A look can **mix output types** (e.g. A0 = short strip, A1 = grid). One clip per output slot.
- **Playback sources** are `designer`, `mixer`, `controller`, `idle` — only one is active at a time.
- **Brightness is per-clip, per-look, and per-timeline-segment** (sender-side RGB scaling). The receiver driver never dims.
- Cue targets can be `all`, `group`, specific `devices`, or the look's own defaults.

### 4.2 Sender runtime loop (PrimusCentral)

`state.py` (`ControllerState`) is the heart of the runtime:
1. **Discovery** — broadcasts ArtPoll, parses ArtPollReply (capability tag `PV3CAP1|port:type:universe|...|B:<profile>|IP:<mode>|U:<layout>|F:<flags>`).
2. **Animation tick** — the effects engine computes pixel frames for the active playback source at ~30 FPS.
3. **Brightness scaling** — RGB values scaled per clip/look brightness before transport.
4. **ArtDmx send loop** — frames packetized per universe (split: one universe per output; combined: all outputs in one universe) and sent on UDP 6454.
5. **Telemetry in** — FPS (`PFP`) and battery (`PBT`, V1 only) packets received on UDP 6455.

Performance is observable via `GET /api/performance` (uptime, samples, counters, rates — used for packaged FPS validation).

### 4.3 Device management workflow

Discovery → connect → configure, all capability-aware with legacy fallback:

1. **Discover** (`POST /api/discover` or unsolicited ArtPollReply at boot).
2. **Add** discovered (`/api/add_discovered`) or manual (`/api/add_manual`) devices.
3. **Connect / Connect All / Disconnect** (`/api/connect`, `/api/connect_all`, …).
4. **Configure** (only enabled when discovery capabilities advertise the feature):
   - Rename (`/api/rename_node` → ArtAddress, stored in NVS)
   - Output type (`/api/set_device_output` → custom 0x8100 ArtOutputConfig)
   - Receive mode (`/api/set_device_receive_mode` → 0x8110 ArtReceiveConfig; split vs combined universes)
   - Static IP / DHCP (`/api/set_device_ip`, `/api/revert_device_dhcp` → 0x8200 ArtIPConfig, stored in NVS)
   - Identify flash (`/api/hello_device` — capability `H`)
5. **Group** devices (`/api/device_groups`) for cue targeting.

### 4.4 Firmware upload + update workflow

There are now **two distinct firmware concerns**: (a) flashing firmware *onto* a board over USB, and (b) getting the firmware *source* onto the computer in the first place. v0.92 changes (b).

**(a) Flashing a board (unchanged mechanics):** `V4/Arduino/upload.sh` (Primus) and `radius_upload.sh` (Radius) wrap `arduino-cli`. The model mimics the Arduino IDE:

```bash
./V4/Arduino/upload.sh --ports                 # inspect likely ESP32 serial ports
./V4/Arduino/upload.sh -v3 --auto              # exactly one device → upload
./V4/Arduino/upload.sh -v2 --all               # same profile on every detected port
./V4/Arduino/upload.sh -v1 /dev/cu.X /dev/cu.Y # explicit ports for mixed board types
./V4/Arduino/upload.sh -v2 -ssid "Net" -pw "pw" --auto   # bake WiFi creds for this run only
```

- **Profiles:** Primus `-v1` (Huzzah32), `-v2` (ESP32 Feather V2), `-v3` (S3 Reverse TFT + NeoPXL8, and as of v3.9.0 the custom V3 PCB). Radius `radius_v1` (HUZZAH32 + Music Maker).
- Upload commands **compile automatically**; `--compile` is verify-only.
- First-time setup: `setup_primus.py` (creates `.venv`, installs arduino-cli, ESP32 core, libraries). See `BOARD_UPLOAD_README.md`. Packaged apps can self-install Arduino CLI into a managed tools dir via the Firmware page (`action:"setup_tools"`).

**(b) Obtaining/updating firmware source (new in v0.92):** the in-app Firmware page now has two ways to source firmware, with the UI showing installed version + source and a one-click update path:

| Path | When | How |
|------|------|-----|
| **Bundled** (default) | Fresh install, offline | Firmware v3.9.0 ships inside the app bundle and is used as-is. |
| **Downloaded** (preferred when present) | User clicks Download, or a newer GitHub release exists | `POST /api/firmware/jobs {action:"download_firmware"}` → `firmware_source.install_firmware_bundle()` fetches `PrimusReceiverFirmware-<semver>.zip`, **verifies the SHA-256 sidecar**, extracts into `<app-data>/firmware/active/`, and that takes precedence over bundled on the next operation. |

GitHub release scan (`POST /api/firmware/updates/check`, 15-min cache) finds the highest non-draft `PrimusReceiverFirmware-X.Y.Z.zip` across all releases, reads its `.sha256` sibling, and reports `update_available`. Maintainers publish a firmware release with `V4/build_firmware_bundle.py`, which zips `upload.sh` + `primusV3_receiver/` and writes the `.sha256` sidecar — no app rebuild, re-sign, or re-notarize required.

> **Net effect:** firmware has its own semver and its own release cadence, independent of the `0.9x` app version. App version and firmware version are now reported separately in `/api/firmware/status`.

### 4.5 External show-control integration

Two complementary paths:

- **Outbound (the nodes are an Art-Net sink):** Any Art-Net software (TouchDesigner, MadMapper, QLab+lighting, etc.) sends RGB ArtDmx to the receiver's advertised universes on UDP 6454. No Primus-specific extensions required. Documented in `API_REFERENCE.md` and `V3_6/ARTNET_EXTERNAL_INTEGRATION.pdf`.
- **Inbound OSC cue triggers (sender-side):** `osc_control.py` listens on UDP 53001 (QLab-default) using a stdlib-only OSC 1.0 subset. Enables `/cue/<n>/go`-style triggers and a network log shown in the Cue Controller. See `V3_6/exteriorIntegration.md` and the standalone test tool `V4/tools/osc_cue_sender/`.

### 4.6 Radius audio workflow

Distinct from the LED side:
1. **Audio Cues panel** — sender-side cue sheet (`audio_cues.json`) with per-device actions (`play`/`loop`/`stop` + filename + volume + duration) referencing a project WAV library in `V4/sender/audio/`.
2. **Cue Map panel** — edits `/cues.json` *on the device SD card* (firmware-local cue map, separate from the sender sheet).
3. **Sync All** — stops playback on connected nodes, then FTP-uploads missing WAVs to each node's SD root. Poll `GET /api/audio_sync/status` for progress. **Push-only.**
4. **Audio panel** — per-node SD file manager + transport (stop/pause/volume, play/loop WAVs, drag-and-drop upload).
5. **Firmware opcodes:** `0x8300` ArtAudioCmd (play/loop/stop/pause/volume/test_tone/play_cue/loop_cue), `0x8301` ArtFtpCmd (start/stop FTP). Capability tag `PVRAD1|B:v1|IP:D|F:RA`. Track telemetry on UDP 6455 with magic `PTR`.

### 4.7 Development workflow

- **Run from source:**
  ```bash
  python3 V4/sender/run.py --product primus          # PrimusCentral (default URL :8080)
  python3 V4/sender/run.py --product radius          # RadiusCentral
  python3 V4/sender/run.py --product primus --no-browser --port 0   # auto port, CI-friendly
  ```
- **Single-instance behavior:** `central_launcher.py` probes for an existing server; subsequent launches *attach* by opening the requested frontend view rather than starting a second server. Use `--replace` to stop the existing one.
- **Test:** `python3 -m unittest discover -s V4/sender/tests` (26 modules covering artnet, brightness, controller targets, cue boards, device sync/config, firmware profiles/updates, mixer wrapping, OSC, packaging builder, paths, performance, sharing, transport stability, UI lifecycle, etc.). No external test deps.
- **Compile check:** `python3 -m py_compile V4/sender/*.py`.
- **Critical sender↔receiver sync points** (must stay in agreement — see CLAUDE.md):
  - Output type IDs: `LOOK_OUTPUT_TYPES` indices ↔ C++ `OutputType` enum values.
  - Pixel counts: `OUTPUT_TYPES` (Python) ↔ `OUTPUT_TYPE_TABLE` (C++).
  - Custom opcodes 0x8100 (output config), 0x8110 (receive config), 0x8200 (IP config).
  - Discovery capability tag format and feature-flag letters (`R I O M H`).
  - FPS telemetry (`PFP`, 7 bytes, UDP 6455).

### 4.8 Release / packaging workflow

```bash
# macOS (sign + notarize + staple)
python3 V4/build_sender_app.py --target macos --product primus --name PrimusCentral \
    --sign-identity "Developer ID Application: Nicholas Puckett (SAV2V7GXQ5)" \
    --notary-profile "PrimusCentral Notary" --notary-timeout 1h

# Windows (Azure-signed installer)
py V4\build_sender_app.py --target windows --product primus --windows-installer

# Firmware-only release bundle (v0.92+)
python3 V4/build_firmware_bundle.py
```

Release identity: `com.socialbodylab.PrimusCentral`, Developer ID `SAV2V7GXQ5`, notary profile `PrimusCentral Notary`. Output → `V4/dist/macos/PrimusCentral.app`. DMG staging copies only the `.app` + an `/Applications` symlink, built UDZO, signed/notarized/stapled/verified, with the SHA-256 sidecar generated *after* final stapling. GitHub release assets are the DMG + `.dmg.sha256` (and for v0.92, the firmware zip + its sha256). Each release gets a `0xxReleaseNotes.md` in `V4/`.

---

## 5. Hardware Reference (quick)

| Board | Profile | Outputs | Indicator |
|-------|---------|---------|-----------|
| Adafruit Huzzah32 ESP32 Feather | `v1` | NeoPixel GPIO32/GPIO12 | `LED_BUILTIN` |
| Adafruit ESP32 Feather V2 | `v2` | NeoPixel GPIO32/GPIO12 | onboard NeoPixel |
| Adafruit ESP32-S3 Reverse TFT Feather + NeoPXL8 | `v3` (`PRIMUS_PROFILE_V3_1`) | FeatherWing outs 6/7 on GPIO14/GPIO15 (A4/A3), 240×135 ST7789 TFT, D0/D1 buttons | TFT status display |
| V3 custom PCB (firmware 3.9.0+, same `v3` profile) | `v3` | Direct NeoPixel on A0/A1 (GPIO17/18), battery telemetry on A4 (5V rail via 100k/100k divider), TFT screens | — |
| Radius: HUZZAH32 + Music Maker (VS1053 + SD) | `radius_v1` | Audio out | — |

**Limits:** 2 active ports per node, ≤122 LEDs per port, RGB color order (3 bytes/pixel), serpentine grid layout.

**Output types:** `none`, `short_strip` (30), `long_strip` (72), `grid` 8×8 (64), `small_grid` 8×4 (32), `extra_long_strip` (122).

**Effects:** solid, pulse, linear, constrainbow, rainbow, noise, static_noise, sparkle_noise, knight_rider, chase, radial (grid), spiral (grid).

---

## 6. Protocol Summary (quick)

| Function | Port | Opcode / magic |
|----------|------|----------------|
| LED data (ArtDmx) | UDP 6454 | `0x5000` |
| Discovery (ArtPoll/Reply) | UDP 6454 | `0x2000` / `0x2100` |
| Device naming (ArtAddress) | UDP 6454 | `0x6000` |
| Output config (custom) | UDP 6454 | `0x8100` |
| Receive mode (custom) | UDP 6454 | `0x8110` |
| Static IP / DHCP (custom) | UDP 6454 | `0x8200` |
| Radius audio cmd | UDP 6454 | `0x8300` |
| Radius FTP cmd | UDP 6454 | `0x8301` |
| FPS telemetry | UDP 6455 | `PFP` |
| Battery telemetry (V1) | UDP 6455 | `PBT` |
| Radius track telemetry | UDP 6455 | `PTR` |
| Sender HTTP API | TCP 8080 (auto) | JSON |
| Inbound OSC cue control | UDP 53001 | OSC 1.0 subset |

Discovery capability tag: `PV3CAP1|port:type_id:universe|…|B:<profile>|IP:<D|S>|U:<S|C>:<base>|F:<RIOHM>`. Feature flags: `R` rename, `I` IP config, `O` output config, `M` receive-mode config, `H` identify flash. Full packet layouts are in `API_REFERENCE.md`.

---

## 7. Where to start reading

If you are new to this codebase, in order:

1. **`README.md`** — orientation, quick start, hardware table.
2. **`CLAUDE.md`** — conventions, sync points, runtime diagnostics, "do not reintroduce" warnings.
3. **`V4/ARCHITECTURE.md`** — the unified-sender design and product split.
4. **`V4/sender/run.py` → `run_primus.py` → `server.py` → `state.py`** — trace one PrimusCentral launch.
5. **`API_REFERENCE.md`** — the wire protocol, discovery, custom opcodes, HTTP/OSC API.
6. **`V4/FIRMWARE_DEVELOPMENT.md`** + `V4/Arduino/primusV3_receiver/config.h` — the receiver side.
7. **`V4/0xxReleaseNotes.md`** — recent change narrative.
