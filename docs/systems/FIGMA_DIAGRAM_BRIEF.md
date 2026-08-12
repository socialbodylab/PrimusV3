# Figma → PDF → Illustrator brief

Visual production path for the Primus + Radius diagram set.  
Markdown / Mermaid / draw.io remain **content truth**; Figma is the **storytelling** surface; PDF is the **editable handoff** into Adobe Illustrator.

| Role | Artifact |
|------|----------|
| Structure & API truth | [README.md](README.md), [SYSTEMS_OUTLINE.md](SYSTEMS_OUTLINE.md), [API_CONTROLS.md](API_CONTROLS.md) |
| Draft geometry (optional underlay) | [png/](png/), [Primus-Radius-Systems.drawio](Primus-Radius-Systems.drawio) |
| Rich visuals | **[Primus-Radius Systems Diagrams](https://www.figma.com/design/VetnYLjB87BDXle5q8r9s3)** (`VetnYLjB87BDXle5q8r9s3`) |
| Frame prose | [STORY.md](STORY.md) |
| Edit / brand polish | Illustrator via **PDF export** (grouped objects) |

**Plan note:** Figma Starter allows only **3 pages**. The brief’s six-page map is collapsed to:

| Page | Frames |
|------|--------|
| `00 Cover Index Components` | `00-index` |
| `10 System and Operators` | `10-lan-overview` … `25-naming` |
| `30 Devices and API` | `30-primus-device` … `40-api-cheat` |

---

## 1. Why this pipeline

- Figma supports a richer visual language than Mermaid (illustration, dual planes, journey strips, exploded devices).
- **PDF export with named groups/layers** opens in Illustrator with selectable objects (prefer PDF over SVG for multi-object diagrams).
- Markdown stays in git for API accuracy; art does not need to be regenerated from Mermaid.

---

## 2. Figma file setup

### Pages

| Figma page | Contents |
|------------|----------|
| `00 Cover & Index` | Title, reading order, legend, link list to frames |
| `10 System` | Overview LAN scene + ports |
| `20 Operators` | DeviceManager, prototype/production, Eos, Radius workflows, naming |
| `30 Devices` | Primus / Radius exploded internals + compare |
| `90 Components` | Tokens, symbols, connector styles, callout kit |
| `99 Underlays` | Locked Mermaid/draw.io PNGs (reference only, hide for export) |

### Frame size

- **Primary:** 1920 × 1080 (16:9 slides / screen)  
- **Print optional:** 11 × 17" @ 72pt Figma = scale in AI later  
- One **story beat = one frame**; name frames exactly as below so PDF page labels stay clear.

### Frame inventory (linked set)

| Frame name | Story beat (one sentence) | Content refs |
|------------|---------------------------|--------------|
| `00-index` | “Same LAN, two media — light and sound.” | README hub |
| `10-lan-overview` | Who talks to whom; show vs control vs telemetry. | L0, outline §1 |
| `11-ports` | 6454 / 6455 / 6456 / HTTP / OSC / FTP as a port legend scene. | L4, API wire cols |
| `20-devicemanager` | Stage manager board: monitor always, commission when prototype. | L2a, API §1–2 |
| `21-prototype-production` | Freeze commissioning without stopping ArtDmx. | L2b, API gates |
| `22-eos` | Eos owns pixels; DM watches; OSC cues optional. | L2c, API §2.4 |
| `23-radius-prototype` | Tech the SD: browse, upload, cue map, net log. | L3a, API §3 |
| `24-radius-production` | Library → Sync All → Fire / cue# / OSC. | L3b, API §3.3 |
| `25-naming` | Character · Performer · Device — shared cast language. | L3c, API §1 |
| `30-primus-device` | Exploded Primus node: WiFi → buffers → A0/A1 → PST. | D1–D2 |
| `31-primus-mgmt` | Control plane: 0x8140 → NVS → lock. | D3, API §2.3 |
| `32-radius-device` | Exploded Radius node: audio-first loop, SD, VS1053. | D4 |
| `33-radius-audio-path` | Filename vs cue# → SD → speaker; FTP load path. | D5, API §3.1 |
| `34-device-compare` | One Primus node vs one Radius node, shared spine. | D6 |
| `40-api-cheat` | Visual “which API for what?” (not the full table). | API §4 |

Use **prototype links** in Figma (`00-index` hotspots → each frame) so the set feels like one navigable story.

---

## 3. Visual language (beyond Mermaid)

### Palette (CSS-ish tokens → Figma styles)

| Token | Hex | Use |
|-------|-----|-----|
| `bg` | `#F7F5F2` | Page ground |
| `lan` | `#E8F0E6` | Trusted LAN field |
| `primus` | `#1F4E5F` | Primus stroke / accent |
| `primusFill` | `#D6E8EE` | Primus surfaces |
| `radius` | `#8B4513` | Radius stroke / accent |
| `radiusFill` | `#F3E6D8` | Radius surfaces |
| `eos` | `#2C3E50` | Console / external |
| `eosFill` | `#E5E9ED` | Eos surfaces |
| `shared` | `#3D5A40` | Shared spine |
| `warn` | `#8B3A2A` | Lock / contention / caution |
| `ink` | `#1A1A1A` | Body text |
| `muted` | `#5A5A5A` | Captions |

Avoid purple gradients, generic SaaS cards, and emoji as icons.

### Typography

- **Display:** one distinctive family (not Inter/Roboto/Arial) for frame titles only.  
- **UI/labels:** a clean grotesque for callouts and port numbers.  
- Hierarchy: title → one supporting line → labels; no paragraph walls on frames (put detail in API_CONTROLS).

### Story devices (use these instead of flowchart soup)

1. **Dual-plane overlay** — Show plane (ArtDmx / audio) as solid arrows; control plane (mgmt / FTP) as dashed/halftone layer; telemetry as thin pulse lines to :6455.  
2. **Journey strip** — Numbered stages left→right with one icon each (commission → lock → show / library → sync → fire).  
3. **Exploded device plate** — Isometric or orthographic board with leader lines to A0/A1 or SD/VS1053; numbers key to API cheat.  
4. **Cast identity chip** — Recurring three-field badge (Character / Performer / Device) on every device card.  
5. **Lock seal** — Production mode as a physical seal over commissioning controls; ArtDmx pipe remains open underneath.  
6. **Contention badge** — On Radius, `sdBusy` as a shared SPI bus with mutual exclusion between audio and FTP.

### Components library (`90 Components`)

Create as **Figma components** (not flat rectangles):

- `Node/Primus`, `Node/Radius`, `App/DeviceManager`, `App/PrimusCentral`, `App/RadiusCentral`, `Console/Eos`  
- `Arrow/Show`, `Arrow/Control`, `Arrow/Telemetry`  
- `Badge/Identity`, `Badge/Locked`, `Badge/MonitorOnly`, `Badge/Port`  
- `Callout/Number` (1–9) for exploded plates  
- `Plane/Show`, `Plane/Control` (full-frame translucent overlays)

---

## 4. Grouping rules (so PDF stays editable in Illustrator)

Illustrator preserves Figma structure best when groups are intentional.

### Inside every frame — top-level groups (exact names)

```
00_bg
10_lan_field
20_show_plane          ← ArtDmx / audio paths
30_control_plane       ← management / FTP / rename / IP
40_telemetry_plane     ← PST / PTR / PFP
50_actors              ← apps, consoles, devices (instances)
60_callouts            ← numbers, leader lines, captions
70_chrome              ← title, subtitle, legend, frame ID
99_underlay            ← hidden before export
```

### Nesting

- Each actor instance is a **component instance**, then wrapped in a named group if needed (`actor_primus_rx_01`).  
- Connector paths live in the plane groups (`20_show_plane`), not mixed into actors.  
- Text for a callout stays **inside** that callout group with its leader line.

### Do / don’t

| Do | Don’t |
|----|--------|
| Name every top-level group | Leave “Group 47” |
| Flatten boolean ops before export if AI struggles | Rely on open Figma auto-layout for AI edit |
| Keep text as text (not outlined) until final print | Outline fonts in Figma before PDF |
| One artboard = one PDF page | Giant single frame with everything |

---

## 5. Export to Illustrator-friendly PDF

### From Figma

1. Hide `99_underlay` and any prototype overlay UI.  
2. Select frames to ship (or whole pages `10`–`30`).  
3. **Export → PDF**  
   - Use **“Export frames as PDF pages”** (or PDF kit / Figma’s PDF with page-per-frame).  
   - Prefer **vector** (no “rasterize text”).  
4. Optional: also export **SVG per frame** as backup for simple plates only.

### In Illustrator

1. Open PDF — use **“Show import options”** if offered; import all pages or one page.  
2. Confirm layers/groups match `00_bg` … `70_chrome`.  
3. Re-save as `.ai` working file; keep PDF as interchange.  
4. If a group flattened: re-group by plane using the naming scheme above.

### Quality check before calling a page done

- [ ] Can select Primus nodes without grabbing Radius arrows  
- [ ] Show / control / telemetry are separate selectable groups  
- [ ] Title + callouts editable as text  
- [ ] Frame ID (`10-lan-overview`) visible in chrome for cross-ref to API doc  

---

## 6. Storyboard notes (per key frame)

### `10-lan-overview`

Hero: costume-scale LAN field. Eos left, Centrals center, Primus/Radius clusters right. Three plane colors in the legend. One line of copy: *Commissioning and monitoring never own the show path.*

### `20-devicemanager`

Card grid metaphor (not a UI screenshot). Always-visible strip vs expanded commission drawer. Footer chip: `monitor_only` → points to API gates.

### `22-eos`

Two pipes from Eos: thick **ArtDmx :6454** to Primus bodies; thin dashed **OSC** to PrimusCentral. DeviceManager as binoculars icon on the side — watching PST, not sending pixels.

### `30-primus-device` / `32-radius-device`

Exploded plates side-by-side language: same “board” silhouette, different guts. Primus: LED ports glowing. Radius: SD + speaker. Shared WiFi antenna + identity badge.

### `40-api-cheat`

Six big tiles (Name / Identify / Geometry / Lock / Play light / Play sound) — each tile lists **one** primary HTTP path. Full tables stay in [API_CONTROLS.md](API_CONTROLS.md).

---

## 7. Working agreement

| Change type | Where |
|-------------|--------|
| New opcode / HTTP route | Update `API_CONTROLS.md` first, then adjust Figma callouts |
| Story / layout / illustration | Figma only |
| Structural completeness check | Optional: compare frame list to README inventory |
| Git | Commit this brief + markdown; **do not** commit huge binary PDFs unless releasing a tagged doc pack |

Suggested release pack (when art is ready): `docs/systems/exports/Primus-Radius-Systems.pdf` + `.ai` on shared drive / release assets — not required in-repo.

---

## 8. First build checklist

1. Create Figma file; paste tokens as color styles; build `90 Components`.  
2. Place Mermaid PNGs on `99 Underlays` at 20% opacity.  
3. Draw `10-lan-overview` and `00-index` with prototype links.  
4. Draw `30-primus-device` + `32-radius-device` (highest storytelling value).  
5. Export a 2-page PDF; open in Illustrator; verify groups.  
6. Proceed through operator frames, then API cheat.
