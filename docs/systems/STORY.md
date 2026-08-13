# Primus + Radius — story narrative (per frame)

Companion prose for the Figma linked diagram set.  
**File:** [Primus-Radius Systems Diagrams](https://www.figma.com/design/VetnYLjB87BDXle5q8r9s3)  
**API tables:** [API_CONTROLS.md](API_CONTROLS.md) · **Brief:** [FIGMA_DIAGRAM_BRIEF.md](FIGMA_DIAGRAM_BRIEF.md)

> Figma Starter allows **3 pages**. Frames are organized as:  
> `00 Cover Index Components` · `10 System and Operators` · `30 Devices and API`

---

## 00-index — Same LAN, two media

Primus and Radius share a trusted show network and a cast identity language, but they carry different media. DeviceManager is the shared eyes. PrimusCentral (or Eos) drives light. RadiusCentral drives sound. Commissioning and monitoring never silently take over the show path.

**Export tip:** Start PDF export from this frame as page 1.

---

## 10-lan-overview — Three planes

Read the LAN as three overlays:

1. **Show plane** — ArtDmx on `:6454` to Primus; ArtAudio/FTP on `:6456` to Radius.  
2. **Control plane** — management `0x8140`, rename, IP, FTP content load. Dashed conceptually; does not own pixels.  
3. **Telemetry plane** — `:6455` PST/PTR. Primus PST only goes where `teleTarget` was explicitly set — never learned from Eos ArtDmx.

---

## 11-ports — Where conversations live

| Port | Who | What |
|------|-----|------|
| UDP 6454 | Primus + Eos | ArtDmx, management, discovery |
| UDP 6456 | Radius (`radius-central`) | ArtAudioCmd, ArtFtpCmd |
| UDP 6455 | Both | PST / PTR / PFP |
| HTTP | Centrals + DM | JSON facades |
| OSC / FTP | PrimusCentral / Radius SD | Cues · file transfer |

---

## 20-devicemanager — Stage manager board

Always-visible strip: identity triad, health, Hello. Expanded drawer (prototype only): A0/A1 geometry, receive mode, IP, telemetry target, production enter, bulk actions, mixed firmware. Production seal locks commissioning fields while ArtDmx and PST continue. See API §1–2.

---

## 21-prototype-production — Seal, don’t choke

Prototype is editable. Production persists `opMode` and returns `NACK/LOCKED` on commissioning writes. The show pipe stays open. Recovery is physical/boot-window only.

---

## 22-eos — Console owns pixels

Primary path: Eos ArtDmx `:6454` straight to Primus universes. Optional: Eos OSC into PrimusCentral cue vocabulary. DeviceManager stays `monitor_only` when it owns the backend — binoculars, not a second console.

---

## 23-radius-prototype — Tech the SD

Discover → Audio panel (FTP) → project library → Cue Map → Net Log → firmware. Identity uses the same Character / Performer / Device model via ArtShowInfo.

---

## 24-radius-production — Journey strip

Library → Audio Cues (per-device actions) → Sync All (push WAVs) → Fire / OSC / cue number. This is operational “production,” not Primus firmware lock.

---

## 25-naming — Shared triad

Three independent fields. Wire: `0x8210`. Hello: flash vs tone.

---

## 30-primus-device — Exploded light node

Critical path: ArtDmx → wire-order buffers → virtual→physical → NeoPixel `show()`. NVS holds descriptors, opMode, identity, IP, teleTarget. PST is opt-in.

---

## 31-primus-mgmt — Control plane

Commissioner → `0x8140` → gate → NVS CRC → `0x8141`. Ops `0x01`–`0x16` listed on frame; full semantics in API_CONTROLS §2.3.

---

## 32-radius-device — Exploded audio node

Critical path: `audioUpdate` → VS1053 + SD. `sdBusy` means audio and FTP never share the SPI bus. No ArtDmx. Telemetry PTR/PFP on `:6455`.

---

## 33-radius-audio-path — Two ways to play

A) Sender cue sheet expands to filenames.  
B) `play_cue(N)` hits `/cues.json` on device. FTP path loads content before show.

---

## 34-device-compare — Side by side

Same WiFi citizen, different guts. Use when explaining why mixed DeviceManager monitoring is safe: Radius never receives standing ArtDmx.

---

## 40-api-cheat — Six doors

Name · Identify · Geometry · Lock · Play light · Play sound. Point operators to [API_CONTROLS.md](API_CONTROLS.md) for the full matrix.

---

## Illustrator handoff

1. In Figma: select frames → Export → **PDF** (one page per frame).  
2. Confirm groups named `00_bg` … `70_chrome` remain selectable.  
3. Save `.ai` working copy; keep PDF as interchange.  
4. Do not rely on Mermaid PNGs as final art — they remain underlays only.
