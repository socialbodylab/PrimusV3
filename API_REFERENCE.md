# PrimusV3 Art-Net API Reference

This document describes the network API exposed by PrimusV3 LED receiver nodes and strategies for integrating them into common creative-coding and lighting-control environments.

---

## Network Overview

| Function | Protocol | Port | Direction |
|---|---|---|---|
| **LED data** (ArtDmx) | UDP / Art-Net | 6454 | Sender → Node |
| **Discovery** (ArtPoll / ArtPollReply) | UDP / Art-Net | 6454 | Bidirectional |
| **Device naming** (ArtAddress) | UDP / Art-Net | 6454 | Sender → Node |
| **Output config** (custom 0x8100) | UDP / Art-Net | 6454 | Sender → Node |
| **IP config** (custom 0x8200) | UDP / Art-Net | 6454 | Sender → Node |
| **FPS telemetry** (custom) | UDP | 6455 | Node → Sender |

All communication is standard Art-Net 4 over IPv4 UDP, plus three custom opcodes. No TCP, no HTTP, no proprietary framing — any software that speaks Art-Net can drive these nodes directly.

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
| 44–107 | 64 | Long Name | e.g. `"PrimusV3 LED Node \| A0:Short Strip A1:Long Strip A2:Grid 8x8"` |
| 108–171 | 64 | Node Report | Status string, e.g. `"#0001 [0482] PrimusV3 OK — 30 fps"` |
| 172–173 | 2 | NumPorts | Number of active outputs (big-endian) |
| 174–177 | 4 | PortTypes | `0xC0` per active port (DMX output) |
| 190–193 | 4 | SwOut | Universe assignment per port (low nibble) |
| 201–206 | 6 | MAC Address | Node's WiFi MAC |

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

### Default Universe Layout

| Output | Default Type | Pixels | Universe |
|--------|------|-------:|---------|
| A0 | Short Strip | 30 | 0 |
| A1 | Long Strip | 72 | 1 |
| A2 | Grid 8×8 | 64 | 2 |

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
- **Brightness:** Controlled entirely by the RGB values you send. There is no separate brightness channel — send the exact colors you want.
- **Padding:** Art-Net requires even-length data. If your byte count is odd, pad with one `0x00`.
- **Grid pixel order:** Grids always use serpentine ordering — even rows left-to-right, odd rows right-to-left.

### Frame Rate

- The node renders data as fast as it arrives. For smooth animation, **30 FPS** is a good default. The hardware supports up to ~60+ FPS depending on strip length.
- Packets for universes 0, 1, and 2 within a **5 ms window** are assembled into a single frame. If a universe is missing, the timeout fires and the frame renders with stale data for that output.
- The **sequence byte** (offset 12) should increment 1→255→1 with each frame. This lets the node detect and discard out-of-order packets.

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
| 12 | 1 | NumOutputs | Number of outputs to configure (1–3) |
| 13+ | N | Type IDs | One byte per output: 0=Off, 1=Short Strip, 2=Long Strip, 3=Grid |

**Total: 13 + NumOutputs bytes.** The node updates its output configuration, clears pixel buffers, recounts active outputs, and broadcasts an updated ArtPollReply.

### Type ID Mapping

| ID | Type | Pixels |
|----|------|--------|
| 0 | Off | 0 |
| 1 | Short Strip | 30 |
| 2 | Long Strip | 72 |
| 3 | Grid 8×8 | 64 |

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

The sender provides a built-in effects engine (V3.1: `effects.py`, V3.0: embedded in `led_controller.py`) with the following effects:

| Effect | Description | Extra Parameters |
|--------|-------------|------------------|
| none | Output off (black) | — |
| solid | Static color | — |
| pulse | Breathing/fading | speed |
| linear | Color gradient sweep | speed, angle (grid) |
| constrainbow | Constrained rainbow gradient | speed |
| rainbow | Full-spectrum rainbow | speed |
| knight_rider | Bouncing highlight bar | speed, highlight_width |
| chase | Progressive color fill | speed, chase_origin, angle (grid) |
| radial | Radial gradient from center (grid only) | speed |
| spiral | Spiral pattern (grid only) | speed |

### Look Architecture

The effects engine uses a **Look** architecture. In **V3.0**, animation state is computed once per frame and sent identically to all connected devices, with 3 output slots matching the 3 physical outputs.

In **V3.1**, this is extended with a clip/look workflow:
- **Clips** are saved effect presets (effect type, colors, speed, playback mode) scoped to an output type.
- **Looks** are timeline-based compositions of clips across multiple tracks, with per-segment timing and crossfades.
- **Playback sources** determine what drives the outputs: `designer` (live effect editing), `mixer` (look preview), `controller` (cue list playback), or `idle` (black).

Each Look has output slots matching physical outputs. Each slot has its own type, effect, colors, speed, and parameters.

---

## 8. HTTP Control API (V3.1 Sender)

The V3.1 sender (`run.py`) serves a web UI and exposes a JSON API. All POST/DELETE bodies and responses are JSON. The server auto-selects a port (printed at startup).

### GET Endpoints

| Route | Description |
|---|---|
| `GET /` | HTML control interface (Alpine.js SPA) |
| `GET /api/state` | Full JSON state dump (look, devices, FPS, playback source) |
| `GET /api/clips` | List all clips. Query params: `?type=short_strip`, `?search=fire`, `?sort=modified\|created\|name` |
| `GET /api/clips/:id` | Load a single clip by ID |
| `GET /api/looks` | List all saved looks |
| `GET /api/looks/:id` | Load a single look by ID |
| `GET /api/cues` | Get cue list state (cues, current index, playing flag) |

### POST Endpoints — Device Management

| Route | Body | Description |
|---|---|---|
| `POST /api/update` | Various fields | Update state: output type, effect, color, speed, FPS, device IP, grid rotation, angle, highlight_width, chase_origin, playback mode |
| `POST /api/connect` | `{device: N}` | Connect device by index |
| `POST /api/disconnect` | `{device: N}` | Disconnect device by index |
| `POST /api/connect_all` | `{}` | Connect all devices |
| `POST /api/disconnect_all` | `{}` | Disconnect all devices |
| `POST /api/discover` | `{}` | Run ArtPoll discovery, returns `[{ip, short_name, long_name, num_ports, universes}]` |
| `POST /api/add_discovered` | `{ip, short_name, ...}` | Add discovered node as device and auto-connect |
| `POST /api/add_manual` | `{ip: "..."}` | Add device by IP address (tries unicast discovery first, falls back to bare device) |
| `POST /api/remove_device` | `{device: N}` | Remove device by index |
| `POST /api/rename_node` | `{device: N, name: "..."}` | Rename device — sends ArtAddress to firmware, updates TFT |
| `POST /api/hello_device` | `{device: N}` | Flash device red for 1 second to identify it physically |
| `POST /api/set_device_ip` | `{device: N, ip: "...", gateway: "...", subnet: "..."}` | Set static IP on device — sends ArtIPConfig, device reboots |
| `POST /api/revert_device_dhcp` | `{device: N}` | Revert device to DHCP — sends ArtIPConfig mode 0, device reboots |
| `POST /api/device_groups` | `{id, name, device_ips}` | Create or update a named device group |
| `POST /api/set_playback_source` | `{source: "designer"\|"idle"}` | Set the active playback source |

### POST Endpoints — Clips

| Route | Body | Description |
|---|---|---|
| `POST /api/clip/preview` | `{clip_id, t}` | Compute one preview frame for a clip at time `t`. Returns `{pixels, grid, count}` |
| `POST /api/clips/save` | `{name, outputs}` or clip dict | Save clip(s) from designer outputs, or save a single clip dict |
| `POST /api/clips/save_single` | Clip dict | Save or update a single clip. Auto-generates ID and timestamp if missing |

### POST Endpoints — Looks & Mixer

| Route | Body | Description |
|---|---|---|
| `POST /api/looks/save` | Look dict | Save or update a look (timeline with tracks, segments, metadata) |
| `POST /api/mixer/frame` | `{look: {...}, t: 0.0}` | Compute one preview frame for a full look at time `t`. Returns `{outputs: [{pixels, grid, type}, ...]}`. Stateless — no hardware output |
| `POST /api/mixer/preview` | Look dict (+ optional `device_filter`, `play_time`, `playing`) | Start previewing a look on connected devices |
| `POST /api/mixer/update` | `{play_time, playing}` | Lightweight update of mixer preview time/playing state without resending full look |
| `POST /api/mixer/stop_preview` | `{}` | Stop mixer preview, return to idle |

### POST Endpoints — Cue Controller

| Route | Body | Description |
|---|---|---|
| `POST /api/cues` | `{cues: [...]}` | Set the full cue list |
| `POST /api/cues/go` | `{}` | Advance to next cue (fire) |
| `POST /api/cues/stop` | `{}` | Stop cue playback |
| `POST /api/cues/goto` | `{number: N}` | Jump to a specific cue number |
| `POST /api/controller/activate` | `{look_id, fade_time}` | Activate a look directly with optional fade time |
| `POST /api/controller/blackout` | `{fade_time}` | Fade to black with optional fade time |

### DELETE Endpoints

| Route | Description |
|---|---|
| `DELETE /api/clips/:id` | Delete a clip by ID |
| `DELETE /api/looks/:id` | Delete a look by ID |
| `DELETE /api/device_groups/:id` | Delete a device group by ID |

---

## 9. TFT Display

The ESP32-S3 Reverse TFT Feather has a built-in 240×135 ST7789 TFT display. Screen modes are cycled with button D0:

| Screen | Content |
|--------|---------|
| **Home** (default) | Large device name, WiFi status + RSSI, IP address, SSID, live FPS |
| **Status** | Per-output type/pixel count/universe, RECV/IDLE status, FPS, heap |
| **Error** | Error message and details |
| **Test Mode** | Test pattern name (entered via D1 button) |

The device name shown on the TFT is the custom name (set via ArtAddress/Rename) or the default firmware name "PrimusV3".

---

## 10. Integration Strategies by Tool

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
4. **Verify.** The TFT display shows device name, WiFi status, IP, RSSI, and live FPS.
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
  OUTPUT_RING        = 4,          // ← new
};

const OutputTypeDef OUTPUT_TYPE_TABLE[] = {
  { "Off",          0, 0, LAYOUT_NONE,   0, 0 },
  { "Short Strip", 30, 3, LAYOUT_LINEAR, 0, 0 },
  { "Long Strip",  72, 3, LAYOUT_LINEAR, 0, 0 },
  { "Grid 8x8",   64, 3, LAYOUT_GRID,   8, 8 },
  { "Ring",        24, 3, LAYOUT_LINEAR, 0, 0 },  // ← new
};
```

### On the sender side (V3.1: state.py / V3.0: led_controller.py)

Add a matching entry to `OUTPUT_TYPES` and `LOOK_OUTPUT_TYPES`:

```python
OUTPUT_TYPES = {
    "none":        {"pixels": 0,  "layout": "none"},
    "short_strip": {"pixels": 30, "layout": "linear"},
    "long_strip":  {"pixels": 72, "layout": "linear"},
    "grid":        {"pixels": 64, "layout": "grid", "grid_size": [8, 8]},
    "ring":        {"pixels": 24, "layout": "linear"},  # ← new
}

LOOK_OUTPUT_TYPES = ["none", "short_strip", "long_strip", "grid", "ring"]
# Indices must match firmware OutputType enum IDs
```

Pixel counts and byte sizes propagate automatically from these tables — no other code changes needed.
