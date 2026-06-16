# PrimusV3 Art-Net API Reference

This document describes the network API exposed by PrimusV3 LED receiver nodes and strategies for integrating them into common creative-coding and lighting-control environments. It reflects the current V3.6 protocol used by reflashed V1, V2, and V3.1 receiver hardware.

---

## Network Overview

| Function | Protocol | Port | Direction |
|---|---|---|---|
| **LED data** (ArtDmx) | UDP / Art-Net | 6454 | Sender → Node |
| **Discovery** (ArtPoll / ArtPollReply) | UDP / Art-Net | 6454 | Bidirectional |
| **Device naming** (ArtAddress) | UDP / Art-Net | 6454 | Sender → Node |
| **Output config** (custom 0x8100) | UDP / Art-Net | 6454 | Sender → Node |
| **IP config** (custom 0x8200) | UDP / Art-Net | 6454 | Sender → Node |
| **Audio control** (custom 0x8300) | UDP / Art-Net | 6454 | Sender → Radius node |
| **FTP control** (custom 0x8301) | UDP / Art-Net | 6454 | Sender → Radius node |
| **FPS telemetry** (custom) | UDP | 6455 | Node → Sender |
| **Sender HTTP API** | TCP / HTTP JSON | 8080 or auto-selected | Browser/tool → Sender |
| **OSC cue control** | UDP / OSC | 53001 default | Show-control tool → Sender |

Receiver communication is standard Art-Net 4 over IPv4 UDP, plus custom Art-Net opcodes for output/IP configuration and a small UDP FPS telemetry packet. No TCP, no HTTP, no proprietary LED-data framing is required to drive receiver nodes directly. The V3.6 sender also exposes a local HTTP JSON API for Primus Central and an inbound OSC listener for external cue triggers.

---

## 1. Discovery — ArtPoll / ArtPollReply

### How It Works

1. A controller broadcasts an **ArtPoll** packet (14 bytes) to port **6454**.
2. Every PrimusV3 node on the network replies with an **ArtPollReply** (239 bytes) containing its IP, name, port count, and universe mapping.
3. Nodes also broadcast an unsolicited ArtPollReply at startup, so controllers that are already listening will see them appear automatically.

### ArtPoll Packet (sender → network)

| Offset | Length | Field | Value |
|--------|--------|-------|-------|
| 0–7 | 8 | Header | `Art-Net\0` (ASCII + null) |
| 8–9 | 2 | Opcode | `0x2000` (little-endian) |
| 10–11 | 2 | ProtVer | `0x000E` (14, big-endian) |
| 12 | 1 | TalkToMe | `0x00` |
| 13 | 1 | Priority | `0x00` |

**Total: 14 bytes.** Send to `<broadcast>:6454` (255.255.255.255 or subnet broadcast like 192.168.1.255).

### ArtPollReply Packet (node → sender)

Key fields in the 239-byte reply:

| Offset | Length | Field | Description |
|--------|--------|-------|-------------|
| 0–7 | 8 | Header | `Art-Net\0` |
| 8–9 | 2 | Opcode | `0x2100` (little-endian) |
| 10–13 | 4 | IP Address | Node's IPv4 address (4 bytes) |
| 14–15 | 2 | Port | `0x1936` (6454, little-endian) |
| 26–43 | 18 | Short Name | `"PrimusV3"` or custom name (null-terminated) |
| 44–107 | 64 | Long Name | Human-readable summary, e.g. `"PrimusV3.6 LED Node \| A0:Short Strip A1:Long Strip"` |
| 108–171 | 64 | Node Report | Status plus capability tag, e.g. `"#0001 [0482] OK\|PV3CAP1\|0:1:0\|1:2:1\|B:v31\|F:RIOH"` |
| 172–173 | 2 | NumPorts | Number of active outputs (big-endian) |
| 174–177 | 4 | PortTypes | `0xC0` per active port (DMX output) |
| 190–193 | 4 | SwOut | Universe assignment per port (low nibble) |
| 201–206 | 6 | MAC Address | Node's WiFi MAC |

PrimusV3 sender discovery prefers the `PV3CAP1` capability tag in Node Report.
Each output tuple is `port_index:type_id:universe`, where `type_id` matches the
receiver `OutputType` enum and the sender `LOOK_OUTPUT_TYPES` index. V3.6 nodes
also append `B:<profile>` where profile is `v1`, `v2`, or `v31`, and `IP:D` or
`IP:S` to report whether the receiver is currently using DHCP or saved static IP
settings. Feature flags are appended as `F:<letters>`; current letters are `R`
for remote rename via ArtAddress, `I` for remote IP configuration via
ArtIPConfig, `O` for remote output configuration via ArtOutputConfig, and `H` for
the identify flash used by `POST /api/hello_device`. Older nodes without this tag
still fall back to the human-readable Long Name parser, and older PrimusV3 nodes
without feature flags are treated as legacy-compatible for rename/hello/IP/output-config
control.

Example current V3.6 reports:

```text
#0001 [0000] OK|PV3CAP1|0:4:0|1:2:1|B:v1|IP:D|F:RIOH
#0001 [0000] OK|PV3CAP1|0:1:0|1:2:1|B:v31|IP:S|F:RIOH
```

The ArtPollReply IP-address field remains the source of truth for the node's
current address. The compact `IP:` token is intentionally mode-only so the report
stays within Art-Net's 64-byte Node Report limit.

### Discovery Tips

- **Broadcast or unicast both work.** If broadcast is unreliable on your network, send ArtPoll directly to the node's IP.
- **Timeout of 2 seconds** is usually sufficient for WiFi nodes.
- Nodes re-broadcast their ArtPollReply at power-on, so persistent listeners will see new nodes appear without polling.

---

## 2. LED Data — ArtDmx

### Output Types

Each physical output maps to one Art-Net universe. Outputs can be dynamically reassigned at runtime via ArtOutputConfig (see §5).

| Output Type | Pixels | Bytes (RGB×3) | Layout |
|-------------|-------:|----:|---------|
| Off (none) | 0 | 0 | — |
| Short Strip | 30 | 90 | Linear |
| Long Strip | 72 | 216 | Linear |
| Grid 8×8 | 64 | 192 | Grid (serpentine) |
| Small Grid 8×4 | 32 | 96 | Grid (serpentine) |
| Extra Long Strip | 122 | 366 | Linear |

### Default Universe Layout

V3.6 receiver profiles expose two logical outputs per node. Each output maps to one Art-Net universe.

| Profile | Hardware | Output A0 / Universe 0 | Output A1 / Universe 1 |
|--------|----------|--------------------------|--------------------------|
| `v1` | Huzzah32 direct NeoPixel | Small Grid 8×4, GPIO32 | Long Strip, GPIO12 |
| `v2` | ESP32 Feather V2 direct NeoPixel | Small Grid 8×4, GPIO32 | Short Strip, GPIO12 |
| `v31` | ESP32-S3 Reverse TFT + NeoPXL8 | Short Strip, FeatherWing output 6 / GPIO14 | Long Strip, FeatherWing output 7 / GPIO15 |

All data fits within the 512-byte Art-Net universe limit. One ArtDmx packet per universe, per frame.

### ArtDmx Packet Structure

| Offset | Length | Field | Value |
|--------|--------|-------|-------|
| 0–7 | 8 | Header | `Art-Net\0` |
| 8–9 | 2 | Opcode | `0x5000` (little-endian) |
| 10–11 | 2 | ProtVer | `0x000E` (14, big-endian) |
| 12 | 1 | Sequence | 1–255 (incrementing), 0 = disable |
| 13 | 1 | Physical | `0x00` |
| 14–15 | 2 | Universe | Universe number (little-endian) |
| 16–17 | 2 | Length | Data length in bytes (big-endian) |
| 18+ | N | Data | RGB pixel data (R, G, B, R, G, B, …) |

### Pixel Data Format

- **Color order:** RGB (3 bytes per pixel)
- **Channel mapping:** Pixel 0 = bytes 0–2, Pixel 1 = bytes 3–5, etc.
- **Brightness:** Controlled entirely by the RGB values you send. There is no receiver brightness channel or legacy V2 brightness byte. V3.6 Primus Central brightness controls scale RGB values in the sender before ArtDmx transport; direct Art-Net integrations should send the exact RGB values they want rendered.
- **Padding:** Art-Net requires even-length data. If your byte count is odd, pad with one `0x00`.
- **Grid pixel order:** Grids always use serpentine ordering — even rows left-to-right, odd rows right-to-left.

### Frame Rate

- The node renders data as fast as it arrives. For smooth animation, **30 FPS** is a good default. The hardware supports up to ~60+ FPS depending on strip length.
- Packets for active output universes within a **5 ms window** are assembled into a single frame. If a universe is missing, the timeout fires and the frame renders with the most recent data for the other output.
- The **sequence byte** (offset 12) should increment 1→255→1 with each frame. This lets the node detect and discard out-of-order packets.
- Primus Central v0.65 is the packaged macOS sender FPS baseline. Validate packaged app timing through Finder or LaunchServices, not by directly executing `Contents/MacOS/PrimusCentral`. The sender exposes `/api/performance` for local timing diagnostics.

---

## 3. FPS Telemetry Back-Channel (Optional)

When enabled, the node sends a small status packet to the sender's IP on port **6455** once per second.

| Offset | Length | Field | Description |
|--------|--------|-------|-------------|
| 0–2 | 3 | Magic | `"PFP"` (ASCII) |
| 3–4 | 2 | FPS | Frames per second (uint16, big-endian) |
| 5–6 | 2 | Packet Rate | Packets per second (uint16, big-endian) |

**Total: 7 bytes.** This is a custom (non-Art-Net) packet. Listen on UDP port 6455 if you want real-time performance data from the node. This is optional — the node functions identically whether or not anything is listening.

---

## 4. Device Naming — ArtAddress

PrimusV3 nodes support remote renaming via the standard Art-Net **ArtAddress** opcode (`0x6000`). The custom name is stored in NVS (non-volatile storage) and persists across reboots. The TFT display header updates immediately.

### ArtAddress Packet (sender → node)

| Offset | Length | Field | Value |
|--------|--------|-------|-------|
| 0–7 | 8 | Header | `Art-Net\0` |
| 8–9 | 2 | Opcode | `0x6000` (little-endian) |
| 10–11 | 2 | ProtVer | `0x000E` (14, big-endian) |
| 12–13 | 2 | Reserved | `0x0000` |
| 14–31 | 18 | Short Name | New name (null-terminated, max 17 chars) |

The node stores the name in ESP32 NVS Preferences, updates the TFT display header, and broadcasts an updated ArtPollReply.

---

## 5. Remote Output Configuration — ArtOutputConfig (custom opcode 0x8100)

PrimusV3 nodes support runtime output type changes via a custom Art-Net opcode. This allows the sender to change what type of LED (strip, grid, off) is connected to each physical output without reflashing firmware.

### ArtOutputConfig Packet (sender → node)

| Offset | Length | Field | Value |
|--------|--------|-------|-------|
| 0–7 | 8 | Header | `Art-Net\0` |
| 8–9 | 2 | Opcode | `0x8100` (little-endian) |
| 10–11 | 2 | ProtVer | `0x000E` (14, big-endian) |
| 12 | 1 | NumOutputs | Number of outputs to configure (1–2) |
| 13+ | N | Type IDs | One byte per output; IDs are listed below. |

**Total: 13 + NumOutputs bytes.** The node updates its output configuration, clears pixel buffers, recounts active outputs, and broadcasts an updated ArtPollReply.

### Type ID Mapping

| ID | Type | Pixels |
|----|------|--------|
| 0 | Off | 0 |
| 1 | Short Strip | 30 |
| 2 | Long Strip | 72 |
| 3 | Grid 8×8 | 64 |
| 4 | Small Grid 8×4 | 32 |
| 5 | Extra Long Strip | 122 |

---

## 6. Static IP Configuration — ArtIPConfig (custom opcode 0x8200)

PrimusV3 nodes support remote IP configuration via a custom Art-Net opcode. Nodes default to DHCP but can be assigned a static IP address that persists across reboots (stored in ESP32 NVS). The node reboots automatically after any IP configuration change.

### ArtIPConfig Packet (sender → node)

| Offset | Length | Field | Value |
|--------|--------|-------|-------|
| 0–7 | 8 | Header | `Art-Net\0` |
| 8–9 | 2 | Opcode | `0x8200` (little-endian) |
| 10–11 | 2 | ProtVer | `0x000E` (14, big-endian) |
| 12 | 1 | Mode | `0` = DHCP, `1` = Static IP |
| 13–16 | 4 | IP Address | Static IP (4 bytes, only when Mode=1) |
| 17–20 | 4 | Gateway | Gateway address (4 bytes, only when Mode=1) |
| 21–24 | 4 | Subnet Mask | Subnet mask (4 bytes, only when Mode=1) |

**Total: 25 bytes.**

### Mode 0 — Revert to DHCP

Clears the static IP, gateway, and subnet from NVS. The node reboots and obtains an IP via DHCP.

### Mode 1 — Set Static IP

Stores the IP, gateway, and subnet in NVS. The node reboots and uses the static configuration. The IP/gateway/subnet fields are each 4 bytes in network byte order (e.g. `192.168.1.100` = `0xC0 0xA8 0x01 0x64`).

### NVS Keys

| Key | Type | Description |
|-----|------|-------------|
| `staticIP` | 4 bytes | Static IP address |
| `gateway` | 4 bytes | Gateway address |
| `subnet` | 4 bytes | Subnet mask |

If no NVS keys are present at boot, the node uses DHCP (default behavior).

---

## 7. Effects Engine

The sender provides a built-in effects engine (`V3_6/sender/effects.py` in the current compatibility track) with the following effects:

| Effect | Description | Extra Parameters |
|--------|-------------|------------------|
| none | Output off (black) | — |
| solid | Static color | — |
| pulse | Breathing/fading | speed |
| linear | Color gradient sweep | speed, angle (grid) |
| constrainbow | Constrained rainbow gradient | speed |
| rainbow | Full-spectrum rainbow | speed |
| noise | Smooth coherent color texture | speed |
| static_noise | Fast per-pixel noise flicker | speed |
| sparkle_noise | Sparse twinkling noise flecks | speed |
| knight_rider | Bouncing highlight bar | speed, highlight_width |
| chase | Progressive color fill | speed, chase_origin, angle (grid) |
| radial | Radial gradient from center (grid only) | speed |
| spiral | Spiral pattern (grid only) | speed |

### Look Architecture

The effects engine uses a **Look** architecture. In **V3.0**, animation state is computed once per frame and sent identically to all connected devices, with 3 output slots matching the 3 physical outputs.

In **V3.6**, this is extended with a clip/look workflow:
- **Clips** are saved effect presets (effect type, colors, speed, playback mode) scoped to an output type.
- **Looks** are timeline-based compositions of clips across multiple tracks, with per-segment timing and crossfades.
- **Cues** are triggerable production steps. A cue contains one or more assignments, where each assignment triggers a Look against its own target set, or triggers a virtual blackout.
- **Playback sources** determine what drives the outputs: `designer` (live effect editing), `mixer` (look preview), `controller` (cue list playback), or `idle` (black).
- **Brightness** is sender-side RGB scaling. Clips store a normalized brightness value, Timeline segments can override it, and Looks apply a final master brightness after fades/crossfades.

Each Look has two output slots matching the current V3.6 receiver profile contract. Each slot has its own type, effect, colors, speed, brightness, and parameters.

---

## 8. HTTP Control API (V3.6 Sender)

The V3.6 sender (`V3_6/sender/run.py`) serves a web UI and exposes a JSON API. All POST/DELETE bodies and responses are JSON. The server defaults to `http://127.0.0.1:8080`, falls back to an auto-selected port if 8080 is busy, and prints the active URL at startup.

### GET Endpoints

| Route | Description |
|---|---|
| `GET /` | HTML control interface (Alpine.js SPA) |
| `GET /api/runtime` | Sender runtime flags such as UI lifecycle ownership |
| `GET /api/state` | Full JSON state dump (look, devices, FPS, playback source) |
| `GET /api/performance` | Rolling sender timing diagnostics, counters, and per-second rates for FPS/debug validation |
| `GET /api/network/status` | Sender host network interfaces, selected/recommended Art-Net route, saved Settings profiles, and show-router network summaries |
| `GET /api/clips` | List all clips. Query params: `?type=short_strip`, `?search=fire`, `?sort=modified\|created\|name` |
| `GET /api/clips/:id` | Load a single clip by ID |
| `GET /api/clips/:id/export` | Download a portable Clip bundle JSON file |
| `GET /api/looks` | List all saved looks |
| `GET /api/looks/:id` | Load a single look by ID |
| `GET /api/looks/:id/export` | Download a portable Look bundle JSON file, including referenced Clips when available |
| `GET /api/cues` | Get cue list state (cues, current index, playing flag) |
| `GET /api/integrations/osc` | OSC listener settings, bound endpoint, recent message history, examples, and per-cue trigger hints |
| `GET /api/firmware/status` | Source-checkout firmware upload availability plus current/last job state |
| `GET /api/firmware/jobs/:id` | Poll a firmware upload job, including redacted output and structured results |

### Sender Performance Diagnostics

`GET /api/performance` is local sender instrumentation for validating live-output timing, especially packaged macOS builds. It returns rolling sample summaries, counters, uptime, and cumulative rates:

```json
{
  "uptime_seconds": 42.0,
  "samples": {
    "animation_tick_ms": {"count": 1200, "last": 1.2, "avg": 1.1, "max": 7.8},
    "animation_sleep_latency_ms": {"count": 1200, "last": 0.2, "avg": 0.3, "max": 5.4},
    "tick_send_packets": {"count": 1200, "last": 2.0, "avg": 2.0, "max": 2.0}
  },
  "counters": {"animation_frames": 1200, "artnet_packets": 2400},
  "rates_per_second": {"animation_frames": 28.57, "artnet_packets": 57.14}
}
```

Useful samples include `animation_tick_ms`, `animation_sleep_requested_ms`, `animation_sleep_latency_ms`, `tick_lock_wait_ms`, `tick_lock_held_ms`, `tick_send_batch_ms`, `tick_send_packets`, `tick_total_ms`, and `artnet_send_ms`. Useful counters include `animation_frames`, `animation_frame_overruns`, `artnet_packets`, `artnet_frames_with_packets`, `animation_thread_qos_enabled`, and `mixer_controller_thread_qos_enabled`.

The cumulative `rates_per_second` values include startup, browser launch, restore, and reconnect time. For steady-state FPS, compare `animation_frames` deltas over a short interval after the app has settled, or watch the receiver FPS telemetry.

For packaged macOS validation, launch the app through LaunchServices and then query the API:

```bash
open -n V3_6/dist/macos/PrimusCentral.app --args --port 8097
curl -s http://127.0.0.1:8097/api/performance
```

The v0.65 packaged app keeps live output responsive with a `caffeinate -dimsu -w <pid>` process assertion, user-interactive QoS for animation/render threads, and low-latency frame pacing. Set `PRIMUSV3_DISABLE_MACOS_ACTIVITY=1` only for diagnostics that intentionally disable the `caffeinate` assertion. Do not use direct `Contents/MacOS/PrimusCentral` execution as the primary packaged FPS test.

### Packaged Sender Build And Release Touchpoints

The API surface above is the same in source and packaged runs. The release build path for the packaged sender is:

```bash
python3 V3_6/build_sender_app.py \
  --target macos \
  --sign-identity "Developer ID Application: Nicholas Puckett (SAV2V7GXQ5)" \
  --notary-profile "PrimusCentral Notary" \
  --notary-timeout 1h
```

Build-time overrides are `PRIMUSV3_CODESIGN_IDENTITY`, `PRIMUSV3_NOTARY_PROFILE`, and `PRIMUSV3_NOTARY_TIMEOUT`. Runtime/storage overrides are `PRIMUSV3_DATA_DIR`, `PRIMUSV3_USE_APP_DATA=1`, and `PRIMUSV3_TOOLS_DIR`. The macOS timing assertion override is `PRIMUSV3_DISABLE_MACOS_ACTIVITY=1`.

The app bundle uses ID `com.socialbodylab.PrimusCentral` and output path `V3_6/dist/macos/PrimusCentral.app`. Release DMGs should be created from a clean staging directory containing only the app and an `/Applications` symlink, then signed, notarized, stapled, verified with `hdiutil verify`, and checksummed after stapling. The canonical command checklist lives in [V3_6/PACKAGING.md](V3_6/PACKAGING.md).

### POST Endpoints — Device Management

| Route | Body | Description |
|---|---|---|
| `POST /api/update` | Various fields | Update state: output type, effect, color, speed, FPS, device IP, grid rotation, angle, highlight_width, chase_origin, playback mode |
| `POST /api/connect` | `{device: N}` | Connect device by index |
| `POST /api/disconnect` | `{device: N}` | Disconnect device by index |
| `POST /api/connect_all` | `{}` | Connect all devices |
| `POST /api/disconnect_all` | `{}` | Disconnect all devices |
| `POST /api/discover` | `{}` | Run ArtPoll discovery, returns `[{ip, short_name, long_name, node_report, capabilities, num_ports, universes}]` |
| `POST /api/add_discovered` | `{ip, short_name, ...}` | Add discovered node as device and auto-connect |
| `POST /api/add_manual` | `{ip: "..."}` | Add device by IP address (tries unicast discovery first, falls back to bare device) |
| `POST /api/remove_device` | `{device: N}` | Remove device by index |
| `POST /api/rename_node` | `{device: N, name: "..."}` | Rename device — sends ArtAddress to firmware, updates TFT, returns `409` if rename support is not advertised |
| `POST /api/hello_device` | `{device: N}` | Flash device red for 1 second to identify it physically, returns `409` if hello support is not advertised |
| `POST /api/set_device_ip` | `{device: N, ip: "...", gateway: "...", subnet: "..."}` | Set static IP on device — sends ArtIPConfig, device reboots, returns `409` if IP-config support is not advertised |
| `POST /api/revert_device_dhcp` | `{device: N}` | Revert device to DHCP — sends ArtIPConfig mode 0, device reboots, returns `409` if IP-config support is not advertised |
| `POST /api/device_groups` | `{id, name, device_ips}` | Create or update a named device group |
| `POST /api/set_playback_source` | `{source: "designer"\|"idle"}` | Set the active playback source |

### POST Endpoints — Sender Settings

These endpoints back the Settings tab. They manage the sender computer's Art-Net source route and host network profile; receiver static/DHCP controls remain under the device endpoints above. Responses are the same shape as `GET /api/network/status` unless noted.

| Route | Body | Description |
|---|---|---|
| `POST /api/network/preferred_interface` | `{id}` or `{interface_id}` or `{service, device}` | Select the sender interface/source IP used for Art-Net discovery and output sockets. |
| `POST /api/network/preferred_interface` | `{mode:"auto"}` or `{}` | Clear the preferred interface and return to automatic routing. |
| `POST /api/network/controller_connection` | `{ssid, id?, service?, device?}` | Tag the dedicated show-router WiFi SSID. If an active WiFi interface is supplied, its source IP is remembered for that SSID. |
| `POST /api/network/controller_connection` | `{mode:"clear"}` | Clear the saved controller/show-router SSID tag. |
| `POST /api/network/ssid_profile` | `{scope:"ssid/service", mode:"static", ip, gateway, subnet, ssid?, service?, device?}` | Save a static sender IP profile for a WiFi SSID or wired service. `static_ip` is also accepted instead of `ip`. |
| `POST /api/network/ssid_profile` | `{scope:"ssid/service", mode:"dhcp", ssid?, service?, device?}` | Save a DHCP sender profile for a WiFi SSID or wired service. |
| `POST /api/network/apply_static_ip` | `{id?, interface_id?, service?, device?, ip, gateway, subnet}` | macOS-only: save and apply a static sender IP profile through `networksetup` with an administrator prompt. |
| `POST /api/network/set_dhcp` | `{id?, interface_id?, service?, device?}` | macOS-only: set the selected macOS network service back to DHCP and save that profile. |

`GET /api/network/status` returns:

```json
{
  "supported": true,
  "platform": "darwin",
  "interfaces": [
    {
      "id": "en7:USB 10/100/1000 LAN",
      "service": "USB 10/100/1000 LAN",
      "device": "en7",
      "type": "ethernet",
      "ipv4": "192.168.1.10",
      "source_ip": "192.168.1.10",
      "subnet": "255.255.255.0",
      "gateway": "192.168.1.1",
      "network": {"cidr": "192.168.1.0/24", "usable_range": "192.168.1.1 - 192.168.1.254"},
      "connected": true,
      "is_default": false,
      "is_preferred": true,
      "is_controller": false,
      "warnings": []
    }
  ],
  "selected_interface": {},
  "recommended_interface": {},
  "selected_network": {},
  "recommended_network": {},
  "preferred": {},
  "controller_connection": {},
  "ssid_profiles": {},
  "service_profiles": {},
  "last_applied": {},
  "warnings": []
}
```

For `ssid_profile`, `scope` must be either `"ssid"` or `"service"`. Host IP apply/revert is currently macOS-only. Unsupported platforms return `supported:false` from status and `501` for host network changes. Validation errors return JSON as `{"error":"..."}` with an appropriate HTTP status.

### POST Endpoints — Clips

| Route | Body | Description |
|---|---|---|
| `POST /api/clip/preview` | `{clip_id, t}` | Compute one preview frame for a clip at time `t`. Returns `{pixels, grid, count}` |
| `POST /api/clips/save` | `{name, outputs}` or clip dict | Save clip(s) from designer outputs, or save a single clip dict |
| `POST /api/clips/save_single` | Clip dict | Save or update a single clip. Auto-generates ID and timestamp if missing |
| `POST /api/import_bundle` | Bundle JSON | Import a Clip or Look export bundle. Imported IDs are remapped when needed |

### Clip And Look Sharing Bundles

Portable sharing bundles use schema `primus.v3.6.bundle`, `version:1`, and `kind:"clip"` or `kind:"look"`.

Clip export response:

```json
{
  "schema": "primus.v3.6.bundle",
  "version": 1,
  "kind": "clip",
  "created": "2026-05-19T00:00:00+00:00",
  "clip": {"id": "clip-id", "name": "Pulse", "output_type": "short_strip"}
}
```

Look export response:

```json
{
  "schema": "primus.v3.6.bundle",
  "version": 1,
  "kind": "look",
  "created": "2026-05-19T00:00:00+00:00",
  "look": {"id": "look-id", "name": "Opening", "tracks": []},
  "clips": [],
  "missing_clip_ids": []
}
```

`POST /api/import_bundle` accepts current bundles, older `{kind, clip/look}` objects, a raw Clip object with `output_type` and `effect`, or a raw Look object with `tracks` and `outputs`. Imported Clips and Looks keep their original IDs only if those IDs are safe and unused; otherwise new UUIDs are generated and returned in `clip_id_map` and `look_id_map`. Imported Looks clear saved `device_ips` so a shared Look does not target someone else's receiver IPs by accident.

### POST Endpoints — Looks & Mixer

| Route | Body | Description |
|---|---|---|
| `POST /api/looks/save` | Look dict | Save or update a look (timeline with tracks, segments, metadata) |
| `POST /api/mixer/frame` | `{look: {...}, t: 0.0}` | Compute one preview frame for a full look at time `t`. Returns `{outputs: [{pixels, grid, type}, ...]}`. Stateless — no hardware output |
| `POST /api/mixer/preview` | Look dict (+ optional `device_filter`, `play_time`, `playing`) | Start previewing a look on connected devices |
| `POST /api/mixer/update` | `{play_time, playing, device_filter}` | Lightweight update of mixer preview time/playing state and optional live preview target list without resending full look |
| `POST /api/mixer/stop_preview` | `{}` | Stop mixer preview, return to idle |

### POST Endpoints — Cue Controller

Cue payloads use the assignment model below. Older single-Look cues with top-level `look_id`, `target_mode`, `device_group_id`, and `device_ips` are still accepted and normalized into a one-item `assignments` list.

```json
{
  "number": 1,
  "name": "Opening",
  "fade_time": 2.0,
  "auto_follow": false,
  "follow_delay": 5.0,
  "assignments": [
    {"action": "look", "look_id": "look-a", "target_mode": "look"},
    {"action": "look", "look_id": "look-b", "target_mode": "devices", "device_ips": ["192.168.1.2"]},
    {"action": "blackout"}
  ]
}
```

`target_mode` values are `look`, `all`, `group`, and `devices`. A cue containing a `blackout` assignment is treated as a virtual blackout cue.

| Route | Body | Description |
|---|---|---|
| `POST /api/cues` | `{cues: [...]}` | Set the full cue list |
| `POST /api/cues/go` | `{}` | Advance to next cue (fire) |
| `POST /api/cues/stop` | `{}` | Stop cue playback |
| `POST /api/cues/goto` | `{number: N}` | Jump to a specific cue number |
| `POST /api/controller/activate` | `{look_id, fade_time}` | Activate a look directly with optional fade time |
| `POST /api/controller/activate_many` | `{look_ids: [...], fade_time}` | Activate multiple looks directly with optional fade time |
| `POST /api/controller/deactivate_look` | `{look_id}` | Remove one directly activated look from the active controller set |
| `POST /api/controller/blackout` | `{fade_time}` | Fade to black with optional fade time |

### HTTP Endpoints — OSC Integration

The OSC integration endpoints configure and report on the sender's inbound UDP OSC listener. The listener defaults to `127.0.0.1:53001`, starts with the sender, and does not prevent the HTTP server from running if the OSC port cannot be bound.

| Route | Body | Description |
|---|---|---|
| `GET /api/integrations/osc` | — | Return OSC settings, listener status, recent history, supported examples, and cue trigger hints. |
| `POST /api/integrations/osc` | `{enabled, host, port}` | Persist OSC settings and restart the listener. `port:0` asks the OS for an available UDP port. |

Example response:

```json
{
  "settings": {"enabled": true, "host": "127.0.0.1", "port": 53001},
  "enabled": true,
  "running": true,
  "last_error": "",
  "bound": {"host": "127.0.0.1", "port": 53001},
  "history": [
    {"time": "12:26:02", "ok": true, "remote": "127.0.0.1:64817", "address": "/primus/blackout", "args": [0.1], "action": "blackout", "error": ""}
  ],
  "examples": [
    {"address": "/primus/cue/go", "description": "Advance to the next cue"}
  ],
  "cue_triggers": [
    {"number": 1, "name": "Opening Look", "slug": "opening-look", "primus_address": "/primus/cue/opening-look", "qlab_address": "/cue/opening-look/start"}
  ]
}
```

### Inbound OSC Cue Control

OSC packets are received by the sender, not by receiver nodes. The parser supports ordinary OSC messages and simple bundles, with `int32`, `float32`, and string arguments for the cue commands below. Bundles are processed immediately in packet order; timetags are ignored in this first implementation.

| OSC address | Arguments | Action |
|---|---|---|
| `/primus/cue/go` | none | Fire the next cue. |
| `/cue/go` or `/go` | none | Fire the next cue using a shorter alias. |
| `/primus/cue/goto` | integer cue number | Fire a cue by number. |
| `/cue/goto` | integer cue number | Fire a cue by number using a shorter alias. |
| `/primus/cue/name` | string cue name | Fire a cue by exact name, then unique slug fallback. |
| `/cue/name` | string cue name | Fire a cue by name using a shorter alias. |
| `/primus/cue/<slug>` | none | Fire a cue by number or slug. |
| `/cue/<slug>/start` | none | Fire a cue by number or slug using a QLab-friendly path. |
| `/primus/cue/stop`, `/cue/stop`, `/stop` | none | Stop cue playback and release controller output. |
| `/primus/blackout`, `/blackout`, `/panic` | optional fade seconds | Fade or cut to blackout. |

Cue lookup for name-based OSC triggers is exact case-insensitive name first, then unique slug fallback. A slug is the lowercase cue name with non-alphanumeric runs replaced by hyphens, so `Opening Look` becomes `opening-look`. Ambiguous names or slugs are rejected and appear in OSC history with `ok:false`.

### POST Endpoints — Firmware Upload

These endpoints are local sender helpers for firmware tool setup, compile, and upload workflows. They wrap `V3_6/Arduino/upload.sh`, run one job at a time, and redact WiFi passwords from job output. The Firmware tab uses the simple flow of firmware version, selected device or all devices, independently optional device-name and WiFi overrides, then compile/upload with an output window. If Arduino CLI is missing, the Firmware tab can start a one-time setup job that installs managed firmware tools outside the app bundle.

| Route | Body | Description |
|---|---|---|
| `POST /api/firmware/jobs` | `{action:"setup_tools", profile:"v3"}` | Download Arduino CLI into the managed tools directory, configure ESP32 board support, and install receiver firmware libraries. |
| `POST /api/firmware/jobs` | `{action:"list_ports", profile:"v3"}` | Run `upload.sh --board <profile> --ports-json` and return structured serial port data in the job result. |
| `POST /api/firmware/jobs` | `{action:"install", profile:"v3"}` | Run `upload.sh --board <profile> --install`. |
| `POST /api/firmware/jobs` | `{action:"compile", profile:"v3", device_name?, wifi_ssid?, wifi_password?, ip_mode?, static_ip?, gateway?, subnet?}` | Run compile-only verification with optional default device-name, WiFi credential, and static/DHCP IP overrides. |
| `POST /api/firmware/jobs` | `{action:"upload", profile:"v3", port_mode:"auto"\|"selected"\|"all", port?, device_name?, wifi_ssid?, wifi_password?, ip_mode?, static_ip?, gateway?, subnet?}` | Compile, then upload by auto-detected port, explicit selected port, or all detected ESP32-like ports. |

For firmware jobs, `ip_mode` is optional and defaults to `"keep"`. Use `"static"`
with `static_ip`, `gateway`, and `subnet` to store static IP settings on receiver
boot, or `"dhcp"` to clear saved static IP settings on boot. Firmware job
responses include `{id, action, profile, status, command, metadata, output,
result, error}`. `status` is `queued`, `running`, `succeeded`, or `failed`.
Starting a new job while another is queued/running returns `409`.

### DELETE Endpoints

| Route | Description |
|---|---|
| `DELETE /api/clips/:id` | Delete a clip by ID |
| `DELETE /api/looks/:id` | Delete a look by ID |
| `DELETE /api/device_groups/:id` | Delete a device group by ID |

---

## 9. Hardware Status Indicators

The ESP32-S3 Reverse TFT Feather has a built-in 240×135 ST7789 TFT display. Screen modes are cycled with button D0:

| Screen | Content |
|--------|---------|
| **Home** (default) | Large device name, WiFi status + RSSI, IP address, SSID, live FPS |
| **Status** | Per-output type/pixel count/universe, RECV/IDLE status, FPS, heap |
| **Error** | Error message and details |
| **Test Mode** | Test pattern name (entered via D1 button) |

The device name shown on the TFT is the custom name (set via ArtAddress/Rename) or the default firmware name "PrimusV3".

V1 and V2 boards have no TFT, so V3.6 firmware uses simple onboard connection indicators:

| Profile | Indicator | Connected | Disconnected |
|---------|-----------|-----------|--------------|
| `v1` | `LED_BUILTIN` | On | Off |
| `v2` | Onboard NeoPixel | Green | Off |
| `v31` | TFT | `WiFi OK` | `No WiFi` / error screen |

---

## 10. Integration Strategies by Tool

### QLab / OSC Show Control

Primus Central receives OSC cue triggers on the sender computer. For QLab running on the same Mac, create a Network cue that sends OSC to `127.0.0.1:53001`. For QLab on another computer, bind the Primus OSC listener to the sender computer's show-network IP in the Cue Controller panel, then target that IP and port from QLab.

Useful QLab Network cue messages:

```text
/cue/opening-look/start
/primus/cue/goto 3
/primus/cue/go
/primus/blackout 0.5
```

Primus cue names are exposed as QLab-friendly slugs in `GET /api/integrations/osc` and in the Cue Controller panel.

### TouchDesigner

TouchDesigner has native Art-Net support via the **Art-Net CHOP Out**.

1. **Discovery:** TouchDesigner's Art-Net nodes auto-discover via ArtPoll. PrimusV3 nodes should appear automatically.
2. **Sending data:** Create an Art-Net Out CHOP, set Universe (0/1/2), set Destination IP to the node's IP. Feed RGB as CHOP samples.
3. **FPS monitoring:** Use a UDP In DAT on port 6455 to capture the 7-byte telemetry packet.

### MadMapper / MadLight

1. **Discovery:** Preferences → Protocols → Art-Net. Nodes appear after scan.
2. **Patch:** Map fixtures to universes 0, 1, 2 with appropriate pixel counts.

### Isadora

1. **Setup:** Preferences → Communications → Art-Net.
2. **Output:** Use Art-Net Output actor, set Universe to 0/1/2.

### Processing (Java)

Use [ArtNet4j](https://github.com/cansik/artnet4j) or manual UDP:

```java
import ch.bildspur.artnet.*;
ArtNetClient artnet = new ArtNetClient();
artnet.start();
byte[] dmx = new byte[90];  // 30 pixels × 3
artnet.unicastDmx("192.168.1.100", 0, 0, dmx);
```

### Python (Direct)

```python
import socket, struct

ARTNET_HEADER = b"Art-Net\x00"
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

def send_artdmx(ip, universe, rgb_bytes, sequence=1):
    if len(rgb_bytes) % 2 != 0:
        rgb_bytes += b'\x00'
    pkt = bytearray()
    pkt += ARTNET_HEADER
    pkt += struct.pack("<H", 0x5000)
    pkt += struct.pack(">H", 14)
    pkt += bytes([sequence, 0])
    pkt += struct.pack("<H", universe)
    pkt += struct.pack(">H", len(rgb_bytes))
    pkt += rgb_bytes
    sock.sendto(pkt, (ip, 6454))

data = bytes([255, 0, 0] * 30)
send_artdmx("192.168.1.100", 0, data)
```

### Any Software with sACN/E1.31

PrimusV3 speaks **Art-Net only** (not sACN). Use OLA (Open Lighting Architecture) to bridge sACN → Art-Net if needed.

---

## 11. Quick-Start Checklist

1. **Verify network.** Sender and node must be on the same subnet (default: 192.168.1.x/24, WiFi SSID: NETGEAR44).
2. **Discover.** Send ArtPoll to broadcast:6454. Expect ArtPollReply within ~100 ms.
3. **Send data.** Build ArtDmx packets for active universes with correct pixel counts. Send to node IP on port 6454.
4. **Verify.** V3.1-style boards show WiFi/IP/FPS on the TFT. V1 shows `LED_BUILTIN` on when connected. V2 shows its onboard NeoPixel green when connected.
5. **Optional telemetry.** Listen on UDP 6455 for 7-byte FPS packets from the node.

---

## 12. Adding a New Output Type

### On the Arduino side (config.h)

Add a row to `OUTPUT_TYPE_TABLE[]` and a value to the `OutputType` enum:

```c
enum OutputType {
  OUTPUT_OFF         = 0,
  OUTPUT_SHORT_STRIP = 1,
  OUTPUT_LONG_STRIP  = 2,
  OUTPUT_GRID        = 3,
  OUTPUT_SMALL_GRID  = 4,
  OUTPUT_EXTRA_LONG_STRIP = 5,
  OUTPUT_RING        = 6,          // new, append only
};

const OutputTypeDef OUTPUT_TYPE_TABLE[] = {
  { "Off",          0, 0, LAYOUT_NONE,   0, 0 },
  { "Short Strip", 30, 3, LAYOUT_LINEAR, 0, 0 },
  { "Long Strip",  72, 3, LAYOUT_LINEAR, 0, 0 },
  { "Grid 8x8",   64, 3, LAYOUT_GRID,   8, 8 },
  { "Grid 8x4",   32, 3, LAYOUT_GRID,   8, 4 },
  { "Extra Long Strip", 122, 3, LAYOUT_LINEAR, 0, 0 },
  { "Ring",        24, 3, LAYOUT_LINEAR, 0, 0 },  // new, append only
};
```

### On the sender side (V3.6: state.py)

Add a matching entry to `OUTPUT_TYPES` and `LOOK_OUTPUT_TYPES`:

```python
OUTPUT_TYPES = {
    "none":        {"pixels": 0,  "layout": "none"},
    "short_strip": {"pixels": 30, "layout": "linear"},
    "long_strip":  {"pixels": 72, "layout": "linear"},
    "grid":        {"pixels": 64, "layout": "grid", "grid_size": [8, 8]},
    "small_grid":  {"pixels": 32, "layout": "grid", "grid_size": [8, 4]},
    "extra_long_strip": {"pixels": 122, "layout": "linear"},
    "ring":        {"pixels": 24, "layout": "linear"},
}

  LOOK_OUTPUT_TYPES = ["none", "short_strip", "long_strip", "grid", "small_grid", "extra_long_strip", "ring"]
# Indices must match firmware OutputType enum IDs
```

Pixel counts and byte sizes propagate automatically from these tables — no other code changes needed.

---

## 8. Audio Control — ArtAudioCmd (custom opcode 0x8300)

Radius nodes (V3.2 firmware) play WAV files from an SD card. The sender controls playback via a custom Art-Net opcode. These packets are only sent to devices flagged `is_audio`; standard LED nodes ignore unknown opcodes.

**WAV format requirement**: RIFF PCM WAV, 16-bit, 44100 Hz. Convert with: `afconvert -f WAVE -d LEI16@44100 input.aif output.wav`

### ArtAudioCmd Packet (sender → Radius node)

| Offset | Length | Field | Value |
|--------|--------|-------|-------|
| 0–7 | 8 | Header | `Art-Net\0` |
| 8–9 | 2 | Opcode | `0x8300` (little-endian) |
| 10–11 | 2 | ProtVer | `0x000E` (14, big-endian) |
| 12 | 1 | Command | See command table below |
| 13 | 1 | Volume / Cue | 0–100 for volume; cue number for cmd 6/7 |
| 14–N | ≤33 | Filename | Null-terminated ASCII, max 32 chars (cmd 1/2 only) |
| N+1–N+2 | 2 | Duration | `uint16_t` LE, seconds; 0 or omitted = full file (cmd 1/2 optional) |

**Minimum packet: 15 bytes.**

### Command Values

| Value | Name | Description |
|-------|------|-------------|
| 0 | Stop | Stop playback immediately |
| 1 | Play | Play filename once; optional duration limit |
| 2 | Loop | Loop filename; optional duration limit |
| 3 | Pause | Pause / resume playback |
| 4 | Volume | Set hardware volume (byte 13 = 0–100); no filename needed |
| 5 | Test Tone | Play a built-in test tone for device identification |
| 6 | Play Cue | Play the file mapped to cue number (byte 13) in `/cues.json` |
| 7 | Loop Cue | Loop the file mapped to cue number (byte 13) in `/cues.json` |

### Cue Map

Cue numbers (cmd 6/7) resolve via `/cues.json` on the SD card, loaded at boot. Format:

```json
{
  "1": "intro.wav",
  "2": { "file": "loop.wav", "duration": 30 }
}
```

Max 64 entries. Values are either a plain filename string or an object with `file` and optional `duration` (seconds).

---

## 9. FTP Server Control — ArtFtpCmd (custom opcode 0x8301)

Radius nodes run an FTP server (SimpleFTPServer) for SD card file management. The server starts automatically at boot. The sender can toggle it on or off via this opcode; the D1 button on the device also toggles it.

**Credentials**: user `primus`, password `primus`, port 21.

### ArtFtpCmd Packet (sender → Radius node)

| Offset | Length | Field | Value |
|--------|--------|-------|-------|
| 0–7 | 8 | Header | `Art-Net\0` |
| 8–9 | 2 | Opcode | `0x8301` (little-endian) |
| 10–11 | 2 | ProtVer | `0x000E` (14, big-endian) |
| 12 | 1 | Command | `0` = stop FTP, `1` = start FTP |

**Total: 13 bytes.**

**SD bus mutex**: while audio is playing (`sdBusy` flag), `handleFTP()` is skipped each loop — the FTP TCP connection stalls but does not drop. File transfers resume automatically when playback ends.
