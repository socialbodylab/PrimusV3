# PrimusV3 External Art-Net Integration Guide

This document explains how PrimusV3.6 receiver firmware expects Art-Net LED data. It is written for third-party lighting consoles and media servers — especially **ETC EOS** — that send Art-Net directly to Primus nodes without using Primus Central.

If devices respond to Art-Net but colors look wrong, scrambled, or shifted, the cause is almost always a mismatch in **universe**, **pixel count**, **channel start**, **color order**, or **grid pixel ordering**. The firmware does not reinterpret or remap incoming data beyond copying bytes to LEDs in order.

---

## Quick Reference — Workshop Hardware

In workshop kits, outputs are often labeled:

| Workshop label | Firmware / sender type | Pixels | Channels (RGB) | Layout |
|----------------|------------------------|-------:|---------------:|--------|
| **Badge** | `small_grid` (Grid 8×4) | 32 | 96 | Serpentine grid |
| **Collar** | `long_strip` (Long Strip) | 72 | 216 | Linear strip |

Workshop setups preset the collar output to **72 pixels** (`long_strip`) via Primus Central's output configuration. Older nodes may still report `short_strip` (30 px) until reconfigured — always verify with ArtPoll.

Other output types exist (`short_strip`, `grid`, `extra_long_strip`) but badge and 72-LED collar are the standard workshop pair.

---

## How the Firmware Handles Art-Net

### Transport

| Item | Value |
|------|-------|
| Protocol | Art-Net only (not sACN / E1.31) |
| UDP port | **6454** |
| Opcode | ArtDmx `0x5000` |
| Delivery | **Unicast** to the node's IP address |
| Outputs per node | **2** (A0 and A1) |
| Universes | **Split (default):** one universe per active output. **Combined (FW 3.8+):** one universe, contiguous port layout. |

### What the firmware does with pixel data

1. Receives an ArtDmx packet.
2. Matches the packet's **universe** to output A0 or A1.
3. Copies the first *N* bytes into that output's buffer, where *N* = `pixel_count × 3`.
4. Treats the buffer as sequential pixels: byte 0–2 = LED 0, byte 3–5 = LED 1, and so on.
5. Passes each triplet to the NeoPixel driver as **R, G, B** (the driver sends GRB wire order to the LEDs internally).

There is **no** firmware-side brightness channel, **no** HTP/LTP merge logic, and **no** grid remapping. Whatever byte order you send is what gets written to the physical LED chain.

### Brightness

Show dimming is done by scaling RGB values in the sender. The receiver hardware brightness is fixed at 255. To dim from EOS, lower the RGB channel values you send (or apply a dimmer that scales RGB, not a separate intensity channel before RGB).

---

## Default Port and Universe Layout

Each board profile assigns default output types and universes at boot. **Verify on site** — output types can be changed remotely via Primus Central and are stored in the node's NVS.

| Profile | Output A0 | Universe | Output A1 | Universe |
|---------|-----------|----------|-----------|----------|
| `v1` (Huzzah32) | Badge (8×4 grid) | **0** | Long strip / collar (72 px) | **1** |
| `v2` (ESP32 Feather V2) | Badge (8×4 grid) | **0** | Collar (72 px) * | **1** |
| `v31` (S3 TFT + NeoPXL8) | Short strip (30 px) | **0** | Long strip (72 px) | **1** |

\* V2 firmware defaults to `short_strip` on A1 at first flash, but workshop Primus Central presets A1 to `long_strip` (72 px). Read the live Node Report before patching EOS.

Workshop kits typically use **badge on universe 0**, **72-LED collar on universe 1** in split mode.

### Combined universe mode (EOS-friendly, firmware 3.8+)

When Node Report includes `U:C:<base>`, both outputs listen on **one universe**. Bytes are contiguous: port A0 first, port A1 immediately after. Workshop badge + 72-LED collar example on universe 104:

| Region | Channels | Content |
|--------|---------:|---------|
| 1–96 | 96 | Badge (32 px RGB) |
| 97–312 | 216 | Collar (72 px RGB) |

Flash combined defaults: `./V4/Arduino/upload.sh -v1 --auto --receivemode combined --universe 104`

Runtime change: ArtReceiveConfig opcode `0x8110` (see [`API_REFERENCE.md`](../API_REFERENCE.md) §5.1) or PrimusCentral when `F:...M` is advertised.

### How to read the live configuration

Send **ArtPoll** to the node's IP (or broadcast). The **ArtPollReply Node Report** contains a capability tag:

```text
PV3CAP1|port:type_id:universe|B:profile|IP:D|F:RIOH
```

Example for a workshop V1/V2 node with badge + 72-LED collar:

```text
#0001 [0000] OK|PV3CAP1|0:4:0|1:2:1|B:v1|IP:D|F:RIOH
```

Parse each `port:type_id:universe` segment:

| Segment | Meaning |
|---------|---------|
| `0:4:0` | Port A0, type ID 4 (`small_grid` / badge), universe **0** |
| `1:2:1` | Port A1, type ID 2 (`long_strip` / collar), universe **1** |

Type IDs:

| ID | Type | Pixels | DMX channels (RGB) |
|----|------|-------:|-------------------:|
| 0 | Off | 0 | 0 |
| 1 | Short strip | 30 | 90 |
| 2 | Long strip (collar) | 72 | 216 |
| 3 | Grid 8×8 | 64 | 192 |
| 4 | Small grid (badge) | 32 | 96 |
| 5 | Extra long strip | 122 | 366 |

The **Long Name** field also lists active outputs, e.g. `A0:Grid 8x4 A1:Long Strip`.

---

## ArtDmx Packet Format

| Offset | Field | Notes |
|--------|-------|-------|
| 0–7 | `"Art-Net\0"` | Magic header |
| 8–9 | Opcode | `0x5000` (little-endian) |
| 10–11 | ProtVer | `14` (`0x000E` big-endian) |
| 12 | Sequence | Increment 1→255 per frame (0 = disable sequencing) |
| 13 | Physical | `0` |
| 14–15 | Universe | **Little-endian** universe number |
| 16–17 | Length | Data byte count (**big-endian**) |
| 18+ | DMX data | RGB bytes |

### Channel numbering

The first data byte (offset 18) is **DMX channel 1** in Art-Net terms.

For a 72-pixel collar:

| LED index | DMX channels | Bytes in packet |
|----------:|-------------|-----------------|
| 0 | 1–3 | R, G, B |
| 1 | 4–6 | R, G, B |
| … | … | … |
| 71 | 214–216 | R, G, B |

For a 32-pixel badge:

| LED index | DMX channels | Bytes in packet |
|----------:|-------------|-----------------|
| 0 | 1–3 | R, G, B |
| … | … | … |
| 31 | 94–96 | R, G, B |

All workshop outputs fit in one universe (well under the 512-channel limit).

### Color order in the packet

**Send RGB** — red first, then green, then blue — for every pixel.

The firmware calls the NeoPixel library with `(R, G, B)` and uses `NEO_GRB` on the wire. You do **not** need to pre-swap to GRB in your console; doing so will produce wrong colors (e.g. red becomes green).

---

## Collar (Long Strip) — Linear Pixel Order

The workshop collar is a **72-LED linear strip** (`long_strip`). Pixel index follows the physical wiring from the **data-in** end of the strip to the far end.

```
Data in ──►  [0] [1] [2] ... [70] [71]
```

Art-Net mapping is straightforward: channel 1 = LED 0 red, channel 2 = LED 0 green, channel 3 = LED 0 blue, channel 4 = LED 1 red, etc.

### EOS collar checklist

- Fixture mode: **RGB** (3 channels per pixel), not RGBW, not CMY.
- Pixel count: **72**.
- Universe: match Node Report (usually **1** on workshop nodes for A1).
- Start channel: **1** (or your net's equivalent of first slot in the Art-Net universe).
- No extra offset or "fixture personality" channel before the first pixel.
- Destination IP: the Primus node's IP, not only a subnet broadcast (unicast is reliable).

---

## Badge (Small Grid 8×4) — Serpentine Pixel Order

The badge is **32 pixels** arranged as an **8 column × 4 row** grid, but the LED strip is wired in **serpentine** (boustrophedon) order:

- **Even rows** (0, 2): left → right
- **Odd rows** (1, 3): right → left

Physical LED index map (numbers are **pixel indices** in the Art-Net stream):

```text
Row 0:    0   1   2   3   4   5   6   7
Row 1:   15  14  13  12  11  10   9   8
Row 2:   16  17  18  19  20  21  22  23
Row 3:   31  30  29  28  27  26  25  24
```

Row 0 is the row where the strip **starts** (data-in). Confirm orientation on the physical badge if left/right seems mirrored in show.

### What Primus Central does (and EOS must match)

Primus Central designs effects in **logical** row-major order (row 0 left→right, row 1 left→right, etc.), then **reorders to serpentine** immediately before sending ArtDmx. The firmware expects **physical serpentine order** — it does not perform that reorder itself.

If EOS is patched as a simple 32-pixel line, or as an 8×4 matrix with every row left→right, **even rows may look correct while odd rows appear reversed**, or the whole pattern may look scrambled.

### EOS badge checklist

- Total pixels: **32** (96 RGB channels).
- Layout: **serpentine 8×4**, not progressive/linear row-major.
- If EOS only offers "matrix" without serpentine, use a 32-pixel **linear** fixture type and manually order channels to match the map above, or use a custom pixel map / personality.
- Universe: match Node Report (usually **0** on workshop nodes for A0).
- Color order: **RGB**.

---

## Why Colors Look Unpredictable — Common Causes

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| Red shows as green (or cyclic wrong hues) | Color order set to GRB (or other) in EOS fixture | Set fixture / mode to **RGB** |
| All pixels show a shifted rainbow or wrong solid | Wrong **start channel** or extra channel before pixel 1 | Start at channel 1; remove leading dimmer/intensity channel |
| Pattern appears on wrong device | Wrong **universe** or wrong **destination IP** | Read `PV3CAP1` Node Report; unicast to node IP |
| Collar looks correct, badge rows zig-zag | Badge sent as linear or progressive grid, not **serpentine** | Use serpentine map in Badge section |
| Only first few LEDs change | **Pixel count** too low in patch (e.g. 30 instead of 72) | Set 72 (collar) or 32 (badge) |
| Collar pattern repeats or wraps oddly | Collar patched as 30 px (`short_strip`) instead of 72 | Confirm type ID **2** in Node Report |
| Colors flicker or stutter | Multiple senders fighting, or sequence issues | One controller per node; increment ArtDmx sequence |
| Everything very dim | RGB scaled low; no separate brightness channel exists | Raise RGB levels in EOS |
| Collar responds on badge universe | Output types changed from defaults | Re-read ArtPollReply; patch to actual universes/types |

---

## EOS-Specific Setup Notes

EOS terminology varies by version and network configuration. Map these concepts to Primus:

| Primus concept | EOS concept |
|----------------|-------------|
| Node IP address | Art-Net device / net destination IP |
| Universe 0, 1 | Net universe (confirm whether your net uses 0- or 1-based display) |
| 32 or 72 RGB pixels | LED fixture, pixel map, or RGB array |
| 96 or 216 channels | Total DMX footprint per universe output |
| Serpentine 8×4 | Matrix wiring / snake order / pixel map |

### Recommended verification procedure

Run these tests before building cues:

1. **Discovery** — ArtPoll the node; confirm `PV3CAP1` segments and note each port's universe and type ID.

2. **Collar solid red** — Universe for A1 (usually 1). Send LED 0 = (255, 0, 0), all others off. The first LED at the data-in end of the collar should be red.

3. **Collar walk** — Light one pixel at a time in index order 0→71. Confirm sequential motion along the strip.

4. **Badge corner test** — Universe for A0 (usually 0). Light only pixel **0** green. Only one corner LED (start of strip, row 0 left in map above) should light.

5. **Badge serpentine test** — Light pixel **7** blue and pixel **8** red simultaneously. They should be adjacent along the strip path (end of row 0 and start of row 1 on the physical zig-zag), not at opposite corners of a progressive matrix.

6. **Badge row reversal test** — Light pixels 8–15 one at a time. They should run **right to left** along row 1 (indices 8 at right, 15 at left in the map above).

### Network

- Primus nodes join WiFi (default SSID in firmware is often `OPERADEV` unless reflashed).
- EOS and the node must be routable to each other (same LAN or routed Art-Net).
- Use **unicast** to the node's IP for output; broadcast is not required.

---

## Frame Timing

- The node renders as packets arrive; target **~30 FPS** for smooth motion.
- When both outputs are active, the firmware waits up to **5 ms** for universes sharing the same sequence before updating LEDs.
- Increment the ArtDmx **sequence** byte each frame so the node can ignore stale packets.

---

## Protocol the Firmware Does Not Use

Sending these will not fix color issues:

- No sACN (E1.31) — Art-Net only
- No separate brightness / dimmer DMX channel per output
- No HTP merge of multiple Art-Net sources at the pixel level
- No automatic RGB↔GRB swap of your data
- No grid remapping (serpentine must be correct in the stream)

Primus-specific opcodes (`0x8100` output config, `0x8200` IP config, `0x6000` rename) are for management only; they do not affect how ArtDmx color bytes are interpreted.

---

## Related Documentation

- Full protocol reference: `API_REFERENCE.md` (ArtDmx, output types)
- Firmware output table: `FIRMWARE_DEVELOPMENT.md`
- Hardware profiles: `hardwareCompatibility.md`

---

## Summary

| Output | Type ID | Pixels | Channels | Universe (workshop) | Pixel order | Color order |
|--------|--------:|-------:|---------:|---------------------|-------------|-------------|
| Badge | 4 | 32 | 96 | 0 (A0) | 8×4 **serpentine** | RGB |
| Collar | 2 | 72 | 216 | 1 (A1) | **Linear** 0→71 | RGB |

**The firmware is a thin transport layer:** universe → byte copy → LED index. Predictable color from EOS requires matching universe, pixel count, channel start, RGB order, and (for badge) serpentine pixel indices exactly as described above.
