# V5 Backend API Reference

The complete HTTP surface of the unified V5 backend — the one server process
behind PrimusCentral (`/primus`), RadiusCentral (`/radius`), and DeviceManager
(`/devices`). Every route the server dispatches is listed here.

Companion documents: [PORTS_AND_LANES.md](PORTS_AND_LANES.md) for the UDP lane
model, [FIRMWARE_REFERENCE.md](FIRMWARE_REFERENCE.md) for Art-Net opcodes and
telemetry byte layouts, [ARCHITECTURE.md](ARCHITECTURE.md) for how the pieces
fit. Integration recipes for external tools are at the end of this file.

## General behavior

- **Transport:** HTTP/1.1 with keep-alive (65 s idle timeout). All request and
  response bodies are JSON unless noted (audio upload routes take raw bytes).
- **Bind:** `127.0.0.1` by default; `--lan` binds `0.0.0.0`
  (DeviceManager's own fresh backend does this for the Mobile/Tablet View).
- **Auth: none, anywhere.** The stated posture for a trusted, isolated show
  network. Anything that can reach the port can flash firmware, write device
  SD cards, and stop the server. Treat any bind wider than loopback as a
  security decision (see [REMOTE_BACKEND_NOTES.md](REMOTE_BACKEND_NOTES.md)).
- **Errors:** `{"error": "<message>"}`, sometimes with `"error_code"` and
  extra fields. Common statuses: `400` bad input · `404` not found ·
  `409` conflict (capability not advertised, job already running, output
  live, management-only route on a non-management backend) · `501`/`503`
  unsupported platform / unavailable subsystem.
- **Device addressing:** `{device: N}` is an index into the unified device
  list. Indices are identical in every frontend and in
  `/api/state?product=radius` (which returns *all* devices, radius-shaped).
- **Path ids** (`clips/<id>` etc.) accept `[a-zA-Z0-9_-]+` only.
- Routes marked **[mgmt]** pass through the Primus management gate and return
  `409 NotAvailable` on a standalone (legacy) Radius backend. On the unified
  backend they always work.

---

## 1. State, runtime, and server control

| Route | Purpose |
|---|---|
| `GET /api/state` | Full Primus-shaped state: `fps`, `output_types`, `look_output_types`, `look`, `devices[]`, `device_groups[]`, `playback_source`, `playback`. |
| `GET /api/state?product=radius` | Radius-shaped view of the same device list: `{product:"radius", products:[…], devices:[…]}`. **All devices are included** (indices aligned); the Radius UI filters on `is_radius`. Per-device fields include identity (name/character/performer, `device_uid`, mac), connection, capabilities, IP config, resolved lane ports, battery/RSSI/uptime, `current_track`, `playback_state`, and the PRS flag fields (`sd_ready`, `ftp_running`, `audio_playing`, `audio_looping`, `marius_*`, `test_mode_active`). |
| `GET /api/runtime` | Discovery probe — shape-stable for old clients: `{product, products[], app_version, ui_lifecycle, frontends:{primus,radius,devices}, default_frontend, monitor_only, lan_enabled, server_control}`. `products` lists everything this backend can serve (the unified backend: `["primus","radius"]`). |
| `GET /api/server/status` | Operational detail (deliberately separate from `/api/runtime` so it can grow): `{pid, host, port, product, products[], app_version, monitor_only, lan_enabled, ui_lifecycle, client_sessions[], client_session_count, live_output, uptime_seconds}`. |
| `POST /api/server/stop` | `{force?}` — ask this server to shut down so another launcher can take the port. `409` while `live_output` is true unless forced, so one app can never black out a show another is running. |
| `GET /api/performance` | Rolling timing diagnostics: `{uptime_seconds, samples:{name:{count,last,avg,max}}, counters, rates_per_second}`. Includes tick/lock/send timings and, new in V5, `api_state_lock_wait_ms`/`api_state_lock_held_ms`. Cumulative rates include startup time — compute steady-state FPS from counter deltas. |

**UI lifecycle** (used by the packaged apps' windows; harmless elsewhere):

| Route | Purpose |
|---|---|
| `POST /api/ui/heartbeat` | `{session_id?}` — marks a UI window alive (2 s cadence from the apps; 150 s staleness). The server auto-quits only when no sessions remain **and** no output is live. |
| `POST /api/ui/closed` | `{session_id?}` — explicit close, starts the short quit grace period. |
| `POST /api/ui/focus` | Raise the packaged app's window on the server's desktop. `404` when no focus callback is installed. Same-machine legacy — do not build new signalling on it. |

## 2. Devices and discovery

| Route | Body | Purpose |
|---|---|---|
| `POST /api/discover` | `{}` | ArtPoll sweep (~3.5 s). Returns an array of nodes: `{ip, short_name, long_name, node_report, capabilities, num_ports, universes}`. |
| `POST /api/devices/sync` | `{}` | Discover, add newly-seen compatible devices (Primus `PV3CAP1` **and** Radius `PVRAD1`), refresh known ones. Returns `{added, skipped, connected, nodes}` — **`connected` is always `[]`**: sync never arms output, on any backend (see [ARCHITECTURE.md](ARCHITECTURE.md)). Concurrent calls coalesce into one sweep. Every frontend calls this every 20 s. |
| `POST /api/connect` | `{device}` | Explicitly arm DMX output to one device (re-probes it first). `409` under `--monitor-only`; `503` if unreachable. No-op for Radius devices. |
| `POST /api/connect_all` / `disconnect` / `disconnect_all` | `{device}` / `{}` | Same semantics, fleet-wide / disarm. |
| `POST /api/add_discovered` | node dict | Add a node from `/api/discover` output; returns `{status:"added"\|"updated", device_index}`. |
| `POST /api/add_manual` | `{ip}` | Add by IP — unicast probe first, bare device fallback. |
| `POST /api/remove_device` | `{device}` | Remove from the list (silently no-ops on a bad index). |
| `POST /api/rename_node` | `{device, name}` | ArtAddress rename (17 chars max, stored in receiver NVS). `409` if not advertised. |
| `POST /api/hello_device` | `{device, volume?}` | Physically identify: Primus flashes red for 1 s (only works while the sender is streaming to it — there is no opcode); Radius plays a test tone at `volume` (default 80). |
| `POST /api/device_show_info` | `{device, character_name?, performer_name?}` (≥ 1) | Write show identity to the receiver (ArtShowInfo, when supported) and the sender's store — Primus devices persist in `.primus_state.json`, Radius in `.radius_state.json`. |

## 3. Device configuration

Config writes go over the Setup lane and are capability-gated: routes return
`409` with an `error_code` when the device doesn't advertise the feature.
On management-capable Primus nodes (firmware 3.14+) writes are ACK/NACK'd and
followed by a config readback; production-locked devices NACK everything
except reads and the boot-window unlock.

| Route | Body | Purpose |
|---|---|---|
| `POST /api/set_device_output` | `{device, output, output_type}` | Change one output's type (legacy table-index path). Note the field is `output_type`, not `type`. |
| `POST /api/apply_device_output_descriptor` **[mgmt]** | `{device, output, descriptor}` | Full 12-byte descriptor model: layout, pixel count, grid geometry, traversal, virtual pixels — all-or-nothing. |
| `POST /api/set_device_receive_mode` | `{device, receive_mode:"split"\|"combined", base_universe?}` | Universe layout. Combined requires total virtual pixels ≤ 170. |
| `POST /api/set_device_virtual_resolution` | `{device, output, virtual_pixels?\|virtual_percent?}` | Virtual send resolution (transport compression; receiver upscales). |
| `POST /api/set_device_ip` | `{device, ip, gateway, subnet}` | Static IP via ArtIPConfig / management op. Device reboots; response may carry `pending_reconnect: true`. |
| `POST /api/revert_device_dhcp` | `{device}` | Back to DHCP; device reboots. |
| `POST /api/set_device_telemetry_target` **[mgmt]** | `{device, telemetry_target}` (`null`/`"0.0.0.0"` clears) | Point the receiver's Watch-lane telemetry at an IP. Primus sends nothing until this is set — the target is explicit so third-party ArtDmx can never redirect monitoring. |
| `GET /api/device_full_config?device=N` **[mgmt]** | — | Cached full receiver config: names, operating mode, lock state, receive config, telemetry target, IP config, outputs. |
| `POST /api/refresh_device_full_config` **[mgmt]** | `{device}` | Live GET_CONFIG readback over the Setup lane; updates the cache. |
| `GET /api/device_lock_state?device=N` **[mgmt]** | — | `{management_supported, operating_mode, production_mode, management_locked, unlock_window_open, unlock_remaining_seconds}`. |
| `POST /api/enter_device_production_mode` **[mgmt]** | `{device}` | Lock the receiver (rejects all commissioning writes until unlocked). |
| `POST /api/unlock_device_boot_window` **[mgmt]** | `{device}` | Unlock a headless production device — only within 60 s of its boot. Button boards (V3.1) use the D1 long-press instead. |
| `GET /api/device_lane_ports?device=N` | — | Resolved per-device lane ports: `{port_show, port_setup, port_watch, ftp_port, is_radius, management_capable}`. |
| `POST /api/device_lane_ports` | `{device, port_show, port_setup, port_watch}` | Move a device's lanes (Primus: mgmt op `0x17`, ACK'd; Radius: opcode `0x8220`, fire-and-forget). See [PORTS_AND_LANES.md](PORTS_AND_LANES.md) for caveats. |
| `POST /api/device_groups` | `{id, name, device_ips}` | Create/update a named device group. `DELETE /api/device_groups/<id>` removes one. |

**Output presets** **[mgmt]** — named descriptor presets stored in sender app
data; they reach receiver NVS only when explicitly applied:

| Route | Purpose |
|---|---|
| `GET /api/output_presets` / `GET /api/output_presets/<id>` | List (built-ins included) / fetch one. |
| `POST /api/output_presets` | Create `{name, descriptor}` or update `{id, name? descriptor?}`. |
| `DELETE /api/output_presets/<id>` | Delete. Error codes: `OutputPresetValidation`, `OutputPresetNotFound`, `DuplicateOutputPresetName/Id`, `BuiltInOutputPreset`. |

## 4. Clips, Looks, Mixer, Controller, Cues

The Primus show workflow. On a backend without the Primus product these
return errors; on the unified backend they always work.

| Route | Purpose |
|---|---|
| `GET /api/clips` | List clips. Query: `?type=<output_type>`, `?search=`, `?sort=modified\|created\|name`. |
| `GET /api/clips/<id>` · `DELETE /api/clips/<id>` | Load / delete one clip. |
| `POST /api/clips/save` | Save from designer outputs (`{name, outputs}`) or a raw clip dict. |
| `POST /api/clips/save_single` | Save/update one clip dict (id and timestamps auto-filled). |
| `POST /api/clip/preview` | `{clip_id, t?}` → one frame: `{pixels, grid, count}`. |
| `GET /api/looks` · `GET /api/looks/<id>` · `DELETE /api/looks/<id>` | List / load / delete looks. |
| `POST /api/looks/save` | Save/update a look (timeline tracks + segments + master brightness). |
| `GET /api/clips/<id>/export` · `GET /api/looks/<id>/export` | Portable sharing bundles (`primus.v3.6.bundle`, version 1). Look bundles embed referenced clips and list `missing_clip_ids`. |
| `POST /api/import_bundle` | Import a bundle (or bare clip/look object). IDs are remapped when unsafe/taken (`clip_id_map`/`look_id_map`); imported looks clear saved `device_ips` so a shared file can't target someone else's receivers. |
| `POST /api/mixer/frame` | `{look, t?}` → stateless full-look frame `{outputs:[{pixels, grid, type}]}`. |
| `POST /api/mixer/preview` | Look dict + optional `device_filter`, `play_time`, `transport_time`, `playing`, `seq` — start live preview on connected devices. |
| `POST /api/mixer/update` | Lightweight transport update (`play_time`/`transport_time`/`playing`/`seq`/`device_filter`) without resending the look. |
| `POST /api/mixer/stop_preview` | Back to idle. |
| `POST /api/set_playback_source` | `{source:"designer"\|"idle"\|"controller"}`. |
| `POST /api/update` | The designer's catch-all mutation: fps, look name, per-output effect/colors/speed/brightness/params, device IP assignment, grid rotation. |
| `GET /api/cues` · `POST /api/cues` | Cue list state (cues, current index, playing, crossfade progress, blackout) / replace the list. Cues use the assignment model: `{number, name, fade_time, auto_follow, follow_delay, assignments:[{action:"look"\|"blackout", look_id?, target_mode:"look"\|"all"\|"group"\|"devices", …}]}`; legacy single-look cues are normalized. |
| `POST /api/cues/go` · `/api/cues/stop` · `/api/cues/goto` | Fire next / stop and release output / `{number}` jump. |
| `POST /api/controller/activate` · `activate_many` · `deactivate_look` · `blackout` | Direct look control with optional `fade_time`. |

**Cue boards** — named saved cue lists:

| Route | Purpose |
|---|---|
| `GET /api/cue_boards` / `GET /api/cue_boards/<id>` | List `{boards:[{id,name,cue_count,…}]}` / load one. |
| `POST /api/cue_boards` | `{name, id?, cues?}` — omit `cues` to snapshot the live cue list. |
| `POST /api/cue_boards/<id>` | Overwrite `{name?, cues?}`. |
| `POST /api/cue_boards/<id>/load` | Load a board into the live cue list. |
| `DELETE /api/cue_boards/<id>` | Delete. |

## 5. Audio and device FTP (Radius surface)

Served by the unified backend for `is_radius` devices. Audio commands go out
on the device's Show lane; FTP operations gate the device's FTP server over
the Setup lane and use TCP 21 for data. FTP sessions are serialized per
device (concurrent sessions to one node tear each other down).

| Route | Body | Purpose |
|---|---|---|
| `POST /api/audio/cmd` | `{device, cmd:"play"\|"loop"\|"stop"\|"pause", filename?, volume?, duration?}` or `{cmd:"volume", volume}` | Transport control (ArtAudioCmd). Filenames up to 64 chars (firmware 4.18+). Volume is 0–100 but the usable range is **50–100** — the byte maps onto the codec's full 127 dB attenuation, so below ~50 is inaudible; the UIs clamp accordingly. Pause holds position; resume by re-sending play. |
| `POST /api/audio/files` | `{device, path?}` | SD directory listing `{entries:[{name,is_dir,size?}]}`. Handles both tab-separated and legacy space-padded FTP LIST formats; hides dotfiles. |
| `POST /api/audio/upload?device=N&path=/x.wav` | raw WAV bytes | Upload to the device SD (RIFF/WAVE magic enforced). |
| `POST /api/audio/rename` · `delete` · `mkdir` | `{device, src,dst}` / `{device, path, is_dir?}` / `{device, path}` | SD file management. |
| `GET /api/audio/cue_map?device=N` | — | Read `/cues.json` from the device SD. Missing or corrupt file returns `{}` (an empty editable table), not an error. |
| `POST /api/audio/cue_map` | `{device, cues}` | Write `/cues.json` to the device SD. |
| `GET /api/audio_cues` · `POST /api/audio_cues` | — / cue-sheet object | The sender-side audio cue sheet (persisted as `audio_cues.json`). |
| `GET /api/audio_cues/export` · `POST /api/audio_cues/import` | — / raw JSON | Download / replace the cue sheet. |
| `POST /api/audio_cues/fire` | `{number}` | Fire a cue across devices; returns per-IP results `{"<ip>":{status:"sent"\|"skipped"\|"error", reason}}`. Disconnected devices are skipped, not errored. |
| `GET /api/project_audio` | — | Project WAV library `{files:[{name,size,checksum}]}`. |
| `POST /api/project_audio?filename=` | raw WAV bytes | Add to the library. `DELETE /api/project_audio/<name>` removes. |
| `POST /api/audio_sync` | `{}` | Start push sync: stop playback everywhere, then FTP-upload cue-referenced WAVs missing from each SD. Returns `{job_id}`; if already running, the running job's id (HTTP 200). Pull sync / conflict resolution intentionally do not exist. |
| `GET /api/audio_sync/status` | — | `{job_id, status:"planning"\|"running"\|"done"\|"error", items:[{device_ip, filename, bytes_sent, bytes_total, status, error}]}` or `{status:"idle"}`. |
| `GET /api/netlog?since=N` · `POST /api/netlog/clear` | — | Network event log for the Radius UI. |

## 6. Firmware and serial monitor

Wraps `V5/Arduino/upload.sh` / `radius_upload.sh` via a managed `arduino-cli`.
One job at a time (`409` otherwise, including while the serial monitor runs);
WiFi passwords are redacted from job output.

| Route | Purpose |
|---|---|
| `GET /api/firmware/status` | Tool availability, profile catalog, current/last job, installed firmware info, and the GitHub update scan. `?scope=mixed` returns all five profiles (`v1 v2 v3 radius_v1 radius_v2`) — DeviceManager's mixed panel; default scope stays product-filtered. |
| `POST /api/firmware/jobs` | `{action, profile, scope?, …}` — actions: `setup_tools`, `list_ports`, `install`, `compile`, `upload`, `download_firmware`. Upload takes `port_mode:"auto"\|"selected"\|"all"` + `port?`. Compile/upload overrides: `device_name` (≤17), `character_name`/`performer_name` (≤64), `wifi_ssid`+`wifi_password` (together), `ip_mode:"keep"\|"static"\|"dhcp"` (+`static_ip`/`gateway`/`subnet`), and Primus-only `receive_mode_mode:"keep"\|"split"\|"combined"` + `base_universe`. |
| `GET /api/firmware/jobs/<id>` | Poll a job: `{id, action, profile, status:"queued"\|"running"\|"succeeded"\|"failed", command, output[], result, error, …}`. |
| `POST /api/firmware/updates/check` | `{force?}` — refresh the GitHub firmware release scan (15-min cache). Returns `{enabled, local_version, remote_version, update_available, …}`; non-Primus products get `{enabled:false}` with HTTP 200. |
| `GET /api/serial/status` | `{active, port, started_at, output[]}` — rolling serial monitor output. |
| `POST /api/serial/monitor/start` / `stop` | `{port, baud?}` — start/stop the serial monitor (mutually exclusive with firmware jobs). |

## 7. Sender network settings

Manage the sender computer's own network posture (not receivers'). Responses
share the `GET /api/network/status` shape; validation errors are 400 with
`{"error"}`; host IP changes are macOS-only (`501` elsewhere, and they
escalate through an interactive admin prompt — laptop feature, not headless).

| Route | Purpose |
|---|---|
| `GET /api/network/status` | Host interfaces with addresses/subnets, selected + recommended Art-Net route, saved profiles, show-router summary, warnings. |
| `POST /api/network/preferred_interface` | `{id}` / `{interface_id}` / `{service, device}` to pin the Art-Net source interface; `{mode:"auto"}` or `{}` to clear. Re-points the discovery/output sockets live. |
| `POST /api/network/controller_connection` | `{ssid, …}` tag the show-router SSID; `{mode:"clear"}` untags. |
| `POST /api/network/ssid_profile` | `{scope:"ssid"\|"service", mode:"static"\|"dhcp", ip, gateway, subnet, …}` — saved per-SSID/service sender IP profiles. |
| `POST /api/network/apply_static_ip` · `set_dhcp` | macOS-only host IP apply/revert through `networksetup`. |
| `GET /api/network/lane_ports` · `POST /api/network/lane_ports` | The editable global lane-port defaults `{port_show_primus, port_show_radius, port_setup, port_watch}` (all four required on POST; `port_setup` must differ from the Show ports and from `port_watch`). Persisted in sender state; the Watch value takes effect at next server start. Does not move already-configured devices — use `/api/device_lane_ports` for that. |

## 8. OSC integration (Primus cue control)

The sender (not receivers) listens for OSC. Defaults to UDP 53001; runs with
the server; a failed OSC bind never blocks HTTP.

| Route | Purpose |
|---|---|
| `GET /api/integrations/osc` | Settings, listener status, bound sockets, listen addresses, recent history (with per-message ok/error), supported address examples, and per-cue trigger hints (including QLab-friendly slugs). `503` when no OSC service is attached (non-Primus backends). |
| `POST /api/integrations/osc` | `{enabled?, port?}` — persist and restart the listener. `port: 0` asks the OS for a free port. (A `host` field is accepted but ignored — the listener manages its own binds; use the GET response's `listen_addresses` to see where to aim.) |

OSC addresses: `/primus/cue/go` (aliases `/cue/go`, `/go`), `/primus/cue/goto <n>`,
`/primus/cue/name <name>`, `/primus/cue/<slug>`, `/cue/<slug>/start` (QLab),
`/primus/cue/stop` (aliases `/cue/stop`, `/stop`), `/primus/blackout [fade]`
(aliases `/blackout`, `/panic`). Name lookup is exact case-insensitive first,
then unique slug; ambiguous triggers are rejected into the history log.

## 9. Static serving

`GET /` serves the active product's default frontend directly. `/primus`,
`/radius`, `/devices` serve their respective apps; `/css/*`, `/js/*`,
`/icons/*` serve shared assets (path-escape attempts get 403). The mobile
monitor view is `/devices?mode=mobile` — a curated read-only UI, not an auth
boundary.

---

## Art-Net quick reference (for external integrators)

Full byte layouts, capability tags, and NVS behavior:
[FIRMWARE_REFERENCE.md](FIRMWARE_REFERENCE.md). The short version for driving
Primus nodes from TouchDesigner, EOS, MadMapper, Processing, or raw UDP:

- **Discovery:** broadcast ArtPoll (`0x2000`) to `:6454`; nodes answer
  ArtPollReply (`0x2100`, 239 bytes) with IP, name, MAC, and a capability tag
  in the Node Report. Nodes also announce themselves at power-on.
- **LED data:** standard ArtDmx (`0x5000`) to the node's IP on `:6454`, one
  packet per universe per frame. RGB, 3 bytes/pixel, serpentine grids, pad to
  even length, increment the sequence byte. ~30 FPS is the sweet spot.
- **Brightness is your job:** there is no receiver brightness channel — send
  the exact RGB you want rendered.
- **Universe layout:** per-device — split (one universe per output, base+N) or
  combined (all outputs packed in one universe), advertised in the capability
  tag as `U:S:<base>` / `U:C:<base>`.
- **Virtual resolution:** a node may ask for fewer pixels than it physically
  has (capability tuple `port:type:universe:virtual`) and upscale on-device —
  send `virtual` pixels, not the physical count.
- **Radius nodes are not LED nodes:** they answer discovery on 6454 but never
  accept ArtDmx; audio control is the vendor opcode `0x8300` on `:6456`.
- **Telemetry:** receivers unicast status packets to the sender on UDP
  `:6455` (`PST`/`PFP`/`PTR`/`PRS`). Listen there if you want live FPS or
  playback state in your own tooling.
- PrimusV3 speaks Art-Net only, not sACN — bridge with OLA if needed.

Minimal Python sender:

```python
import socket, struct

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

def send_artdmx(ip, universe, rgb_bytes, sequence=1):
    if len(rgb_bytes) % 2:
        rgb_bytes += b"\x00"
    pkt = (b"Art-Net\x00" + struct.pack("<H", 0x5000) + struct.pack(">H", 14)
           + bytes([sequence, 0]) + struct.pack("<H", universe)
           + struct.pack(">H", len(rgb_bytes)) + rgb_bytes)
    sock.sendto(pkt, (ip, 6454))

send_artdmx("192.168.1.100", 0, bytes([255, 0, 0] * 30))  # 30 px red
```

For QLab: send OSC network cues to the sender (`/cue/<slug>/start`,
`/primus/cue/goto 3`, `/primus/blackout 0.5`) — slugs are listed in
`GET /api/integrations/osc` and the Cue Controller panel.

---

## Appendix — wire formats for the custom opcodes

Byte-exact layouts for anyone building or parsing these packets directly.
All packets begin `Art-Net\0` (8 bytes) + opcode (2 bytes little-endian) +
protocol version `0x000E` (2 bytes big-endian) unless noted. Standard Art-Net
(ArtPoll/ArtPollReply/ArtDmx/ArtAddress) follows the published spec; the key
custom fields:

**ArtPollReply fields the sender reads:** IP at 10–13, short name at 26–43,
long name at 44–107, Node Report (capability tag) at 108–171 — hard 64-byte
budget, see [PORTS_AND_LANES.md](PORTS_AND_LANES.md) — port/universe info at
172–193, **MAC at 201–206** (becomes `device_uid`).

**ArtOutputConfig `0x8100`** (Primus) — total 13 + N bytes:
byte 12 = NumOutputs (1–2), byte 13+ = one output-type table ID per output
(0 Off · 1 Short Strip 30 px · 2 Long Strip 72 · 3 Grid 8×8 · 4 Grid 8×4 ·
5 Extra Long Strip 122).

**ArtReceiveConfig `0x8110`** (Primus 3.8+) — 15 bytes:
byte 12 = mode (0 split, 1 combined), bytes 13–14 = base universe u16 LE.
Combined mode requires total virtual pixels ≤ 170.

**ArtVirtualResolution `0x8130`** (Primus 3.11+) — 13 + 2N bytes:
byte 12 = NumOutputs, then one u16 LE virtual pixel count per output
(1 … physical count).

**ArtIPConfig `0x8200`** (both families) — 25 bytes:
byte 12 = mode (0 DHCP, 1 static), bytes 13–16 IP, 17–20 gateway,
21–24 subnet (network byte order). The node replies, then reboots.

**ArtShowInfo `0x8210`** (both) — 143 bytes:
byte 12 = mode (0 read, 1 write, 2 response), character name length at 13 /
data from 14, performer name length at 78 / data from 79 (≤ 64 chars each).

**ArtLanePorts `0x8220`** (Radius only) — 18 bytes:
three u16 **big-endian** ports at 12–17: show, setup, watch. No ACK.
(Primus moves lanes via management op `0x17` instead.)

**ArtAudioCmd `0x8300`** (Radius) — 15+ bytes:
byte 12 = command (1 play · 2 loop · 3 pause · 4 volume · 5 test tone ·
6 play cue# · 7 loop cue# · **anything else = stop**), byte 13 = volume 0–100
(doubles as the cue number for commands 6/7), byte 14+ = NUL-terminated
filename (≤ 64 chars), optionally followed by u16 LE duration seconds.

**ArtFtpCmd `0x8301`** (Radius) — 13 bytes:
byte 12 = 1 to stop audio and start the FTP server; any other value stops FTP.
FTP credentials `radius`/`radius` on TCP 21.

**Management protocol `0x8140`/`0x8141`** (Primus 3.14+): 20-byte header =
magic(8) · opcode(2 LE) · protver(2 BE) · mgmtVer(1) · op(1) · requestId(2 BE)
· payloadLen(2 BE) · status(1) · error(1). Ops: `0x01` GET_CONFIG,
`0x10` SET_OUTPUT_DESCRIPTORS, `0x11` SET_TELEMETRY_TARGET,
`0x12` SET_OPERATING_MODE, `0x13` SET_RECEIVE_CONFIG, `0x14` SET_IP_CONFIG,
`0x15` SET_IDENTITY, `0x16` BOOT_WINDOW_UNLOCK, `0x17` SET_LANE_PORTS.
Replies are idempotency-cached (30 s, keyed on requester+request) so retries
replay rather than re-execute. Full op semantics:
[FIRMWARE_REFERENCE.md](FIRMWARE_REFERENCE.md) §4.

**Telemetry packets** (`PST` 28 B, `PBT` 9 B, `PFP` 7 B, `PTR` 5–69 B,
`PRS` 17 B, all on UDP 6455): byte layouts in
[FIRMWARE_REFERENCE.md](FIRMWARE_REFERENCE.md) §11.
