# ETC Eos Integration Plan

Status: planning document, no implementation yet.

## Goal

Let an ETC Eos console (or Eos family: Ion, Gio, Element, Nomad, ETCnomad) trigger and/or control PrimusV3 looks during a show, the same way it already triggers conventional lighting cues.

## What Primus already has

- **OSC listener, receive-only.** `V3_6/sender/osc_control.py` listens on UDP (default `127.0.0.1:53001`, configurable, rebindable to a show-network IP). It accepts `/primus/cue/go`, `/cue/goto <n>`, `/primus/cue/name <string>`, slug-based QLab-style addresses, `/primus/cue/stop`, and `/primus/blackout [fade]`. These call the same `CueList`/`ControllerState` methods the HTTP Cue Controller API uses, so OSC triggers behave identically to clicking "Go" in the UI. This is documented for QLab in `V3_6/exteriorIntegration.md`.
- **No OSC output.** Primus cannot report its current cue/look back to a console or show-control tool.
- **Art-Net only, output only.** `artnet.py` sends ArtDmx to receiver nodes and supports two custom opcodes (`0x8100` output config, `0x8200` IP config) for receiver setup. There is no sACN/E1.31 support and no listener for *incoming* Art-Net or DMX values as control input.
- **Cue model:** integer cue numbers, fade time, auto-follow/delay, and assignments to a Look or to blackout. No hierarchical numbering (1.1, 1.2) like Eos.
- **Brightness model:** sender-side RGB scaling only (Clip brightness → segment override → Look master brightness). Receivers have no brightness channel — do not build anything that assumes one.

## Constraints to respect

- Don't revive a receiver-side brightness byte or touch the `0x8000+` custom opcode range used for receiver config — any new inbound protocol work is a separate channel from the sender→receiver Art-Net path.
- Keep new features table-driven and additive; don't change existing OSC address behavior used by QLab today.
- No new external Python runtime dependencies in the sender (stdlib only), per project convention.

## Integration options

### Option 1 — OSC cue bridge, no sender code changes (lowest effort)

Use the OSC listener Primus already has. Eos has native OSC output (**Setup → System Settings → Show Control → OSC**, enable OSC Tx, add Primus's IP and port as a destination). Build Eos macros or cue-attached OSC commands that send the existing addresses, e.g.:

```text
/primus/cue/goto 12
/primus/blackout 0.5
```

This can be wired into Eos cues via an **OSC cue part** (fires alongside a normal Eos cue) or a **macro** triggered from a cue's "macro" link.

- **Effort:** none on the Primus side; show-file setup only.
- **Enables:** Eos cue advance fires a matching Primus cue/blackout, one-way.
- **Limits:** Eos operator must hand-author the OSC string per cue (no auto-sync of cue numbers), and there's no confidence feedback in Eos that Primus actually executed it. Today's OSC history panel in the Cue Controller is the only confirmation.

### Option 2 — Eos-aware OSC enhancements (small sender change)

Add a small, additive vocabulary to `osc_control.py` aimed specifically at console-style control rather than QLab-style cue triggers:

- `/primus/master_brightness <0.0-1.0>` — drive overall Look master brightness from an Eos submaster, fader, or "OSC fader" output, so a programmer can busk intensity live without leaving Eos.
- `/primus/group/<name>/blackout` or `/primus/group/<name>/cue <n>` — target a device group (groups already exist in `/api/device_groups`) instead of always affecting everything.
- Outbound status: when a cue or blackout fires, send `/primus/status/cue <n>` (or similar) back to a configured Eos/monitoring destination, so the console (or a companion confidence display) can show Primus is in sync. This requires adding a UDP *sender* to `osc_control.py`, which doesn't exist today.

- **Effort:** medium — additive OSC commands, plus first-time outbound OSC capability and an "Eos integration" panel showing the address list (similar to the existing QLab `cue_triggers` block in `/api/integrations/osc`).
- **Enables:** live intensity busking and group targeting from Eos controls, with status feedback.
- **Limits:** still cue/command-level, not full per-fixture-channel patch.

### Option 3 — Native incoming Art-Net listener (channel-level control, no external bridge)

Eos can output Art-Net directly from its own network settings — no bridge software required. Add a second, clearly separate listener in the sender (e.g. `artnet_input.py`) that subscribes to one configurable universe of *incoming* ArtDmx and maps specific channels to Primus actions:

- Channel 1: cue select (0-255 maps to cue number)
- Channel 2: "go" trigger (rising edge fires the selected cue)
- Channel 3: master brightness (0-255 maps to 0.0-1.0)
- Channel 4: blackout (snap or threshold-fade)

Patch this universe in Eos as a generic fixture/relay so a programmer can fader-control Primus exactly like a conventional dimmer rack, fully inside the Eos patch and cue structure (no OSC authoring needed per cue).

- **Effort:** medium-high — new listener thread, channel-mapping config and UI, careful separation from the existing receiver-facing ArtDmx output path so the two are never confused.
- **Enables:** the most "console-native" workflow — Primus behaves like a DMX device with a small channel footprint, fully recallable from the Eos cue list itself (values stored per-cue in Eos, not by editing Primus cues).
- **Limits:** coarse control (a handful of channels, not per-pixel); still need Primus-side Looks/Clips for the actual effect content.

### Option 4 — sACN bridge via OLA (if the show network standard is sACN, not Art-Net)

If a venue's show network is committed to sACN end-to-end, drop in [OLA](https://www.openlighting.org/ola/) (or a small custom bridge) between Eos's sACN output and Primus. The bridge can either re-emit Art-Net into the existing Option 3 listener, or translate channel values into HTTP calls against the existing `/api/controller/activate` and `/api/controller/blackout` endpoints.

- **Effort:** low for Primus itself (reuses Option 1 or 3), but adds an operational dependency (a third-party bridge process/machine) and another point of failure in the show network.
- **Enables:** sACN-native consoles/networks without adding sACN support to Primus.
- **Limits:** extra moving part to install, configure, and keep running during a show; not worth it unless sACN is already mandated by the venue.

### Option 5 — Middleware via Bitfocus Companion

If the show already uses [Bitfocus Companion](https://bitfocus.io/companion) as a button surface talking to Eos, Companion can also speak OSC to Primus directly (no Eos-side OSC authoring at all) and could poll Primus's existing `GET /api/state` / `/api/cues` for status to show on button feedback.

- **Effort:** none on the Primus side beyond Option 1; setup lives entirely in Companion.
- **Enables:** a stage manager-friendly button panel that triggers both Eos and Primus from one surface, with visual feedback, without touching the Eos show file's OSC settings.
- **Limits:** only relevant if Companion (or similar middleware) is already part of the show's control stack.

## Comparison

| Option | Sender code changes | Eos-side setup | Granularity | Status feedback |
| --- | --- | --- | --- | --- |
| 1. OSC cue bridge | none | OSC Tx + per-cue/macro strings | cue / blackout | none (OSC history panel only) |
| 2. Eos-aware OSC + outbound status | small | OSC Tx, faders/macros | cue / blackout / brightness / group | yes, once built |
| 3. Native Art-Net DMX-in | medium-high | patch as generic Art-Net fixture | channel-level (coarse) | via channel readback or HTTP polling |
| 4. sACN bridge (OLA) | none (reuses 1 or 3) | sACN patch + bridge config | depends on target | depends on target |
| 5. Companion middleware | none | none (Companion-side) | depends on Companion config | yes, via Companion polling |

## Recommended path

1. **Ship Option 1 now.** It requires zero sender changes and can be validated in a single rehearsal: add OSC Tx destinations in Eos, attach OSC cue parts to a few cues, confirm they land in the Cue Controller's OSC history panel.
2. **If busking brightness live from Eos becomes a real need, build Option 2 next** — it's a contained, additive change to `osc_control.py` and fits the existing receive/execute pattern, plus first outbound-OSC capability for confidence monitoring.
3. **Only invest in Option 3 (native Art-Net DMX-in) if a production wants Primus fully patched and cued inside the Eos show file** rather than authored as separate Primus cues — this is the "feels like a real dimmer rack" outcome but costs the most engineering and UI work.
4. **Treat Options 4 and 5 as integration-by-other-tools**, not Primus feature work — they're "no code" paths that exist purely because a venue or show stack already has that middleware in place.

## Open questions for the user

- Is the goal "Eos fires Primus cues" (show control, Option 1/2) or "Primus patched as channels inside the Eos cue list" (Option 3)?
- Does the venue/show network standard lean Art-Net (already spoken by Primus) or sACN (would need Option 4)?
- Is live intensity busking from Eos faders during tech a priority, or is cue-to-cue triggering sufficient?
