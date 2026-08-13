# Ports and Lanes — as implemented

Receiver traffic is split into three UDP **lanes** so that a burst of setup or
telemetry traffic can never sit in front of show data in a receive queue, and
so firewall rules and packet captures have a meaningful shape. This document
is the as-implemented reference for V5 (Primus firmware 3.14.1, Radius 4.20,
and the unified sender). The original design rationale and trade-off
discussion is in [docs/systems/PORT_ORGANIZATION.md](../docs/systems/PORT_ORGANIZATION.md);
where that document says "should", this one says what the code does.

Lanes are about **queue and socket isolation, not bandwidth** — one WiFi radio
still shares airtime. Don't expect port splits to fix FPS.

## The lane map

| Lane | Port (default) | Direction | Primus | Radius |
|---|---|---|---|---|
| **Show** | **6454** | sender → node | ArtPoll `0x2000` + ArtDmx `0x5000` | ArtPoll **only** (discovery; never ArtDmx) |
| **Show (audio)** | **6456** | sender → node | — | ArtAudioCmd `0x8300` |
| **Setup** | **6457** | sender → node | mgmt `0x8140`, ArtAddress `0x6000`, `0x8100`/`0x8110`/`0x8130`, ArtIPConfig `0x8200`, ArtShowInfo `0x8210` | ArtAddress, ArtIPConfig, ArtShowInfo, ArtFtpCmd `0x8301`, ArtLanePorts `0x8220` |
| **Watch** | **6455** | node → sender | `PST` (28 B, ~1 Hz) | `PTR`, `PFP`, `PRS` (+ `0x8302`, unparsed) |
| **Content** | TCP **21** | bidirectional | — | FTP data plane, gated by ArtFtpCmd on Setup |

Notes on the shape:

- **Primus Show stays on 6454** so stock Art-Net consoles (EOS, TouchDesigner,
  MadMapper) work unmodified. The UI warns when a Primus Show port is moved:
  "custom Art-Net — stock Eos will not hit this node."
- **Radius splits discovery from show.** Its 6454 discovery socket answers
  ArtPoll only and is deliberately **not** configurable — it is the bootstrap
  port through which a node with a broken Show/Setup config can always be
  recovered. There is intentionally no ArtDmx handler anywhere in the Radius
  sketch.
- **Watch is send-only on the node.** No receiver listens on 6455; the sender
  binds it once at startup (`0.0.0.0`, single listener — see
  [ARCHITECTURE.md](ARCHITECTURE.md#telemetry)).
- The Radius firmware also binds an OSC listener on UDP 53001 (`/stop`,
  `/hello`, `/cue/<n>`). That is outside the lane model (the design doc calls
  OSC app-local; the firmware disagrees — a live, documented inconsistency).
- Overriding is at **lane granularity only** — never per-opcode ports.

## Every lane port is a default, stored on the device

Lane ports live in receiver NVS (`portShow`, `portSetup`, `portWatch`) and
survive reboot. The firmware validates a stored set (each ≥ 1024, all three
distinct) and silently reverts an invalid set to compiled defaults at boot.

How a move happens differs by family:

- **Primus:** management op `0x17 SET_LANE_PORTS` inside the `0x8140` protocol
  (6-byte payload, three big-endian u16s). ACK/NACK'd like every management
  op, and **blocked in production mode** like every other commissioning write.
  Sockets rebind in place; no reboot.
- **Radius:** dedicated opcode `0x8220 ArtLanePorts` (18 bytes: header, three
  BE u16s) on the Setup lane. **No ACK** — see the caveats below. Radius has
  no production lock, so nothing gates this.

## Advertisement: the `L` flag and the 64-byte budget

The ArtPollReply Node Report is a hard 64-byte Art-Net field, and the full
V5 token set routinely exceeds it — **truncation is the normal case, not an
edge case**. The lane advertisement rules exist because of a real regression:
the first lane firmware advertised `|SHOW:6454|MGMT:6457|TELE:6455`
unconditionally, and that 30-byte triple alone overflowed the report on every
device, silently dropping `IP:`, `U:`, `G:` and all per-output tuples
(confirmed on hardware; fixed in Primus 3.14.1). The rules that came out of
it:

1. **`L` in the `F:` feature flags means "this firmware binds a Setup lane."**
   It is the *only* always-present lane signal.
2. **Lane tokens (`SHOW:`/`MGMT:`/`TELE:` — `AUD:` instead of `SHOW:` on
   Radius) are emitted only for a lane moved off its default.** A lane-aware
   node on defaults emits none.
3. Therefore: `L` **and no lane token** = "on the documented defaults".
   **No `L`** = pre-lane firmware whose Setup traffic still lives on the Show
   port. This is how the sender distinguishes "lane-aware, silent" from
   "legacy" — silence alone is ambiguous.
4. **Every token appends whole-or-not-at-all.** A truncated `|MGMT:645`
   parses as a plausible port and would black-hole all Setup traffic, so a
   token that doesn't fit entirely is dropped, never clipped.

Priority under pressure (highest survival first), Primus (3.14.2+):

```
F:  →  B:  →  G:  →  IP:  →  U:  →  moved-lane tokens  →  per-output tuples
```

`F:` first because losing it demotes the device to "unconfirmed legacy
hardware" with every capability disabled. `G:` (management protocol version +
lock state) rides directly behind it because the sender gates
`management_supported` on it — as capability-critical as `F:`, and at a fixed
5 bytes it always fits there. Lane tokens outrank output tuples because a
node whose Setup lane moved but can't say so is unmanageable.

> ⚠️ Firmware **3.14.0 and 3.14.1** emitted `G:` *last*, on the mistaken
> belief that nothing parsed it — a crowded report silently dropped it and
> the sender disabled every `0x8140` operation for that device. 3.14.2 fixed
> the order; devices still on 3.14.0/3.14.1 should be reflashed.

Radius token order: `PVRAD1 | B: | F: | IP: | <moved lanes> | V: | MC:/MP:` —
the Marius puck name rides last because it is the one unbounded field.

## How the sender picks a port for each packet

Per-device resolution (`artnet.py resolve_lane_ports`, applied at every send
site via `device_show_port()` / `device_setup_port()`):

| Node advertises | Sender sends Show to | Sender sends Setup to |
|---|---|---|
| `SHOW:`/`AUD:` token | that port | — |
| `MGMT:` token | — | that port |
| `L`, no `MGMT:` | default Show | **6457** (lane-aware default) |
| no `L`, no tokens (pre-lane Primus) | 6454 | **6454** (Setup rides Show) |
| pre-lane / token-less Radius | **6454** (see caveat) | same as Show |

Lane ports read back from a Primus `GET_CONFIG` (payload v2 carries them at
offsets 27–32) are **authoritative** and overwrite inference. Resolved ports
are visible per device in `/api/state` (`port_show`, `port_setup`,
`port_watch`) and via `GET /api/device_lane_ports`.

Sender-side configuration surfaces:

- `GET|POST /api/network/lane_ports` — the editable global defaults
  (`port_show_primus`, `port_show_radius`, `port_setup`, `port_watch`),
  persisted in sender state (not NVS). Today these effectively control **only
  the Watch listen bind, applied at process start**; they do not move
  already-configured devices (the Settings UI says so).
- `GET|POST /api/device_lane_ports` — per-device: resolves and moves a
  specific node's lanes via `0x17` (Primus) or `0x8220` (Radius), then updates
  the sender's record and re-points the live ArtDmx sender.
- UI: Settings → UDP Lanes in all three apps; per-device editor in
  DeviceManager's expanded card.

## Migration state: dual-listen is ON — and currently load-bearing

Both firmwares compile with `PORT_DUAL_LISTEN = 1`:

- Primus accepts Setup opcodes on the Show socket too.
- Radius accepts Setup opcodes on **any** lane, and ArtAudioCmd on the
  discovery socket as well as 6456.

This was meant as a one-release migration bridge. Today it is **load-bearing**
in two ways, and flipping the flag to 0 is a breaking change, not a cleanup:

1. ~~The sender resolved a token-less Radius node's audio port to 6454~~ —
   **fixed on main** (2026-08-13, matching the fix first made on the
   `radius-central` branch after real hardware went silent): a Radius node
   with no `AUD:` token now resolves to **6456**, the audio lane every
   firmware since 4.1 actually listens on.
2. A token-less Radius node's **Setup** traffic still resolves to its Show
   port (6456), where it lands only because dual-listen accepts Setup
   opcodes on any lane — the node's native Setup socket is 6457. Radius has
   no `L`-flag equivalent to distinguish "lane-aware, on defaults" from
   truly ancient firmware, so this stays until one exists (or until every
   fleet unit advertises).

## Recovery

A node with a broken lane config is always reachable:

1. Discover on **6454** (never moves on either family).
2. Open Setup on the advertised port, or the default 6457, or — pre-lane —
   the Show port.
3. Send `SET_LANE_PORTS` (`0x17`) / ArtLanePorts (`0x8220`) to restore
   defaults. On a production-locked Primus node, unlock first (boot window
   within 60 s of power-on for headless boards, D1 long-press on V3.1).
4. The firmware itself resets an invalid stored set to defaults at boot.

The sender must never silently substitute defaults for ports a device
*did* advertise — that is how lab and stage end up split-brained.

## Known sharp edges (verified in code)

Beyond the two dual-listen items above:

- **Primus replies are pinned to literal 6454** (ArtPollReply, `0x8141`
  management replies, show-info responses) regardless of a moved Show lane;
  the sender's query socket likewise binds 6454. Moving the Primus Show lane
  changes what the node *hears*, not where it *answers*.
- **Radius `0x8220` has no ACK**, and the sender applies the move
  optimistically — a dropped packet or firmware-side rejection leaves the two
  disagreeing about the Setup port. (The Primus path ACKs.)
- **Validation differs per layer**: global profile requires ≥ 1024 and
  setup ≠ show/watch; the per-device API only checks ≥ 1 and setup
  distinctness; the firmware requires ≥ 1024 and all-distinct. Inputs can
  pass the sender and be rejected (Primus: NACK; Radius: silently dropped).
- **Watch-port changes are not paired.** Changing the sender's Watch default
  takes effect at next process start, and nothing pushes `portWatch` to
  receivers; changing a device's `portWatch` doesn't check the sender is
  listening there. Either direction can silently lose telemetry.
- Radius emits an `0x8302` audio-status packet to the Watch lane that no
  sender code parses; it also still truncates filenames at 32 chars (the rest
  of the system moved to 64 in firmware 4.18).
- The Radius `FTP:` capability token is parsed by the sender but no longer
  emitted by firmware (the port isn't configurable); the parse path is dead.
