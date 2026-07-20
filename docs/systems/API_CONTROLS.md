# Device API controls — Primus & Radius

Authoritative control tables for **what you can do to a receiver**. Apps (DeviceManager, PrimusCentral, RadiusCentral) are HTTP facades over these surfaces.

**Sources:** Primus V5 (`npuckett-create-v5-tree`); Radius `origin/radius-central` (Art-Net **:6456**).  
**Diagram hub:** [README.md](README.md) · narrative [SYSTEMS_OUTLINE.md](SYSTEMS_OUTLINE.md)

---

## Gates (read first)

| Gate | Effect |
|------|--------|
| **monitor_only** (DeviceManager-owned backend) | `POST /api/connect`, `/api/connect_all` → **409**. Sync discovers only. One-off hello/config may use a transient socket. No standing ArtDmx. |
| **production / management_locked** (Primus firmware `opMode`) | Management `SET_*` → NACK `LOCKED` → HTTP **409**. ArtDmx, discovery, PST, Hello stay live. Unlock: V3 D1 long-press; V1/V2 boot-window + `BOOT_WINDOW_UNLOCK`. |
| **Radius product mode** | Primus management HTTP facade → **409 NotAvailable**. |
| **`is_radius` device on Primus backend** | No ArtDmx; no management-v2; Hello = test tone; rename/IP/show-info via legacy opcodes. |
| **Capability flags** | Legacy Primus mutations require advertised caps (`R/H/I/O/M/S/…`). Management-capable Primus prefers `0x8140`. |

---

## 1. Shared discovery & identity (both products)

| Surface | Method | Path / opcode | Controls on device | Primus | Radius | Notes |
|---------|--------|---------------|--------------------|:------:|:------:|-------|
| HTTP | POST | `/api/discover` | ArtPoll refresh | ✓ | ✓ | Does not auto-connect |
| HTTP | POST | `/api/devices/sync` | Discover + add; connect unless monitor_only | ✓ | ✓ (mixed DM) | DM auto ~20s |
| HTTP | POST | `/api/add_discovered` | Add + connect | ✓ | ✓ | |
| HTTP | POST | `/api/add_manual` | Unicast add + connect | ✓ | ✓ | Body `{ip}` |
| HTTP | POST | `/api/connect` | Mark connected / open ArtDmx (Primus) | ✓ | ✓ (flag only) | monitor_only **409** |
| HTTP | POST | `/api/disconnect` | Disconnect | ✓ | ✓ | |
| HTTP | POST | `/api/connect_all` | Connect online Primus | ✓ | — | monitor_only **409** |
| HTTP | POST | `/api/disconnect_all` | Disconnect all | ✓ | ✓ | |
| HTTP | POST | `/api/remove_device` | Remove from sender list | ✓ | ✓ | Sender-only |
| HTTP | POST | `/api/rename_node` | Technical / short name | ✓ | ✓ | ≤17; mgmt `SET_IDENTITY` or ArtAddress `0x6000` |
| HTTP | POST | `/api/device_show_info` | Character + performer | ✓ | ✓ | mgmt `SET_IDENTITY` or ArtShowInfo `0x8210` |
| HTTP | POST | `/api/hello_device` | Identify | flash | tone | Radius: ArtAudioCmd cmd=5; optional `volume` |
| HTTP | POST | `/api/set_device_ip` | Static IP (NVS, reboot) | ✓ | ✓ | mgmt `SET_IP_CONFIG` or `0x8200` |
| HTTP | POST | `/api/revert_device_dhcp` | DHCP (NVS, reboot) | ✓ | ✓ | |
| Art-Net | — | `0x2000` ArtPoll | Discovery | ✓ | ✓ | |
| Art-Net | — | `0x2100` ArtPollReply | Caps / name / universes (inbound) | `PV3CAP1` | `PVRAD1` | |
| Art-Net | — | `0x6000` ArtAddress | Rename | ✓ | ✓ | |
| Art-Net | — | `0x8200` ArtIPConfig | DHCP/static | ✓ | ✓ | |
| Art-Net | — | `0x8210` ArtShowInfo | Show names | ✓ | ✓ | Feature `S` |
| Telemetry | UDP 6455 | `PFP` | Packet-rate / FPS-ish heartbeat | ✓ | ✓ | |
| HTTP | GET | `/api/state` | Sender mirror (devices + telemetry) | ✓ | ✓ | Poll surface |
| HTTP | GET | `/api/runtime` | `monitor_only`, `lan_enabled`, … | ✓ | ✓ | Sender-only |

---

## 2. Primus-only — LED / management / show

### 2.1 HTTP management facade (management-capable firmware)

| Method | Path | Device effect | Wire op | Blocked when |
|--------|------|---------------|---------|--------------|
| GET | `/api/device_full_config?device=` | Cached full config | (from last GET_CONFIG) | Radius product/device |
| GET | `/api/device_lock_state?device=` | Lock / unlock-window state | — | Radius product/device |
| POST | `/api/refresh_device_full_config` | Authoritative readback | `0x8140` **GET_CONFIG** `0x01` | no management cap |
| POST | `/api/apply_device_output_descriptor` | Replace one slot descriptor (A0/A1) | **SET_OUTPUT_DESCRIPTORS** `0x10` | production LOCKED |
| POST | `/api/set_device_telemetry_target` | PST unicast target; `null`/`0.0.0.0` clears | **SET_TELEMETRY_TARGET** `0x11` | production LOCKED |
| POST | `/api/enter_device_production_mode` | Enter production lock | **SET_OPERATING_MODE** `0x12` | Radius |
| POST | `/api/unlock_device_boot_window` | V1/V2 recovery unlock | **BOOT_WINDOW_UNLOCK** `0x16` | outside boot window |
| GET/POST/DELETE | `/api/output_presets[/{id}]` | Sender preset library | — | apply via `apply_device_output_descriptor` |

### 2.2 HTTP legacy / capability-aware (also used when management not advertised)

| Method | Path | Device effect | Wire |
|--------|------|---------------|------|
| POST | `/api/set_device_output` | Built-in output type on slot | mgmt descriptors or `0x8100` |
| POST | `/api/set_device_virtual_resolution` | Virtual send px | mgmt or `0x8130` |
| POST | `/api/set_device_receive_mode` | Split/combined + base universe | mgmt `0x13` or `0x8110` |

### 2.3 Management protocol operations (`0x8140` / reply `0x8141`)

| Op | Name | Device effect | Production |
|----|------|---------------|------------|
| `0x01` | GET_CONFIG | Full authoritative snapshot | Allowed |
| `0x10` | SET_OUTPUT_DESCRIPTORS | Atomic A0+A1 descriptors (layout, phys/virtual px) | LOCKED |
| `0x11` | SET_TELEMETRY_TARGET | PST destination IPv4 | LOCKED |
| `0x12` | SET_OPERATING_MODE | Prototype ↔ production | Enter locks |
| `0x13` | SET_RECEIVE_CONFIG | Split/combined + base universe | LOCKED |
| `0x14` | SET_IP_CONFIG | DHCP/static | LOCKED |
| `0x15` | SET_IDENTITY | Technical + character + performer | LOCKED |
| `0x16` | BOOT_WINDOW_UNLOCK | Open unlock window (V1/V2) | Recovery only |

NACK `ErrorCode.LOCKED` → HTTP **409**. Timeout → **504**.

### 2.4 ArtDmx show path & related HTTP

| Surface | Path / opcode | Device effect | Notes |
|---------|---------------|---------------|-------|
| Art-Net | `0x5000` ArtDmx | RGB pixels / hello flash / blackout | Only connected Primus; never Radius |
| HTTP | POST `/api/update` | Designer look → ArtDmx | |
| HTTP | POST `/api/set_playback_source` | designer/mixer/controller/idle | Sender routing |
| HTTP | POST `/api/controller/*`, `/api/mixer/*`, `/api/cues*` | Cue/mixer → ArtDmx | |
| OSC | `/primus/cue/go`, `/goto`, `/name`, `/stop` | Fire Primus cues → ArtDmx | Into PrimusCentral |
| OSC | `/primus/blackout` | Blackout frames | Optional fade |
| Telemetry | UDP 6455 `PST` | Unified status (FPS, batt, lock, seq, …) | Only if `teleTarget` set |
| Telemetry | UDP 6455 `PBT` | Legacy battery | Older firmware |

### 2.5 Groups, bulk, firmware (Primus side)

| Method | Path | Device effect | Notes |
|--------|------|---------------|-------|
| POST | `/api/device_groups` | Sender-only membership | Bulk UI filters by group |
| DELETE | `/api/device_groups/{id}` | Sender-only | |
| — | *(no bulk HTTP)* | Client loops rename / output / receive | See DeviceManager |
| POST | `/api/firmware/jobs` | USB flash Primus profile | `scope=mixed` in DM |
| GET | `/api/firmware/status` | Tool/job status | |

**Sender network** (`/api/network/*`) configures the **host NIC**, not receiver ArtIPConfig — except `ssid_profile` used at flash time.

---

## 3. Radius-only — audio / FTP / cues

Branch Art-Net control port: **UDP 6456**. Telemetry remains **UDP 6455**.

### 3.1 ArtAudioCmd `0x8300`

| cmd | Name | Device effect |
|-----|------|---------------|
| 0 | stop | Stop playback |
| 1 | play | Play WAV from SD (filename + optional duration) |
| 2 | loop | Loop WAV |
| 3 | pause | Pause |
| 4 | volume | VS1053 volume 0–100 |
| 5 | test_tone | Identify burst (Hello) |
| 6 | play_cue | Cue number in byte 13 → `/cues.json` |
| 7 | loop_cue | Loop mapped cue |

### 3.2 ArtFtpCmd `0x8301`

| Byte | Effect |
|------|--------|
| 1 | Start FTP (stop audio first); TCP 21; user/pass `radius`/`radius` |
| 0 | Stop FTP |

SD contention: FTP refused while `sdBusy`; play stops FTP first.

### 3.3 HTTP audio / SD

| Method | Path | Device effect | Notes |
|--------|------|---------------|-------|
| POST | `/api/audio/cmd` | play/loop/stop/pause/volume | Maps to cmds 0–4 |
| POST | `/api/audio/files` | List SD dir | FTP LIST |
| POST | `/api/audio/upload` | Store file on SD | FTP STOR |
| POST | `/api/audio/rename` | Rename on SD | |
| POST | `/api/audio/delete` | Delete on SD | |
| POST | `/api/audio/mkdir` | Mkdir on SD | |
| GET | `/api/audio/cue_map?device=` | Read `/cues.json` | FTP RETR |
| POST | `/api/audio/cue_map` | Write `/cues.json` | Reboot/reload to apply |
| POST | `/api/audio/osc_cue` | Fire device cue via OSC | **Branch:** `/cue/N` → :53001 |
| GET/POST | `/api/audio_cues` | Sender cue sheet | Not on device until fire/sync |
| POST | `/api/audio_cues/fire` | Per-IP ArtAudioCmd from sheet | |
| POST | `/api/audio_cues/preview_cue_maps` | Preview derived maps | **Branch;** no device I/O |
| POST | `/api/audio_cues/push_cue_maps` | Push maps to SD | **Branch;** reboot to load |
| GET/POST/DELETE | `/api/project_audio[…]` | Sender WAV library | Sync source |
| POST | `/api/audio_sync` | Push missing WAVs to SD | STOP → FTP upload |
| GET | `/api/audio_sync/status` | Sync progress | |
| GET/POST | `/api/netlog` | Sender event log | Observer |
| Art-Net | `0x8302` ArtAudioStatus | Device→sender status | Inbound |
| Telemetry | `PTR` | Track name + play state | UDP 6455 |
| OSC | `/cue/N`, `/stop`, `/hello` | Device cue map / stop / tone | UDP **53001** on device (branch) |

### 3.4 Firmware

| Method | Path | Effect |
|--------|------|--------|
| POST | `/api/firmware/jobs` | Flash `radius_v1` / `radius_v2` |
| GET | `/api/firmware/status` | Status (`scope=mixed` in DM) |

---

## 4. Quick “which API for what?”

| Goal | Primus | Radius |
|------|--------|--------|
| See devices | `/api/devices/sync`, `/api/state` | same (+ PTR) |
| Name cast / tech | `/api/device_show_info`, `/api/rename_node` | same |
| Identify | `/api/hello_device` (flash) | `/api/hello_device` (tone) |
| IP | `/api/set_device_ip` | same |
| LED geometry / universe | management facade or `set_device_output` / `receive_mode` / virtual | — |
| Lock for show | `/api/enter_device_production_mode` | *(operational only)* |
| Monitor health | PST via `set_device_telemetry_target` | PTR automatic while playing |
| Drive pixels | ArtDmx / cues / Eos | — |
| Play sound | — | `/api/audio/cmd` or `/api/audio_cues/fire` |
| Load media | — | upload / `audio_sync` / cue_map |
| Flash firmware | `/api/firmware/jobs` profile v1–v3 | jobs profile radius_v* |

---

## 5. Diagram cross-references

| Diagram | API sections |
|---------|----------------|
| [L2a DeviceManager params](png/L2a-devicemanager-params.png) | §1, §2.1–2.2 |
| [L2b Prototype/production](png/L2b-prototype-production.png) | §2.3, Gates |
| [L2c Eos](png/L2c-eos-control.png) | §2.4 ArtDmx + OSC |
| [D1–D3 Primus device](png/D1-primus-device-block.png) | §2 |
| [L3a–b / D4–D5 Radius](png/D4-radius-device-block.png) | §3 |
| [L4 Ports](png/L4-protocol-ports.png) | Wire columns above |
