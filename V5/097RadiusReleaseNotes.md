# RadiusCentral v0.97

macOS release built from the V5 unified sender (`--product radius`).

This is the first RadiusCentral build off the `radius-v5-forwardport` line since
v0.93, and it carries the Show/Setup/Watch lane-port work merged from `main`.

## Changes

### Audio / SD card

- **Fixed: the SD file browser showed an empty card.** The receiver's FTP server
  omits the group column in its `LIST` output, and the parser required the
  standard 9-field `ls -l` layout, so every entry was discarded and reported as
  a clean empty listing rather than an error.
- **Fixed: two panels loading at once could kill each other's listing.** A
  receiver serves one FTP connection at a time and ending a session stops the
  server globally, so overlapping requests tore each other down and one failed
  with a timeout. Sessions are now serialized per device.
- Filenames containing spaces are parsed correctly, with the right size.
- The FTP connect is retried when a receiver is not listening yet, instead of
  surfacing a spurious timeout on a perfectly good card.
- The file browser lists folders and `.wav` files only.

### Cues

- Cue maps can be pushed to devices from a new Cue Maps modal, with a preview of
  what each device will receive.
- Device-side cue delay.
- Cue maps reload live on the receiver — no reflash to change them.

### Devices and network

- Show / Setup / Watch lane ports (`6454` / `6457` / `6455`), with Radius audio
  on `6456`. Nodes advertise only lanes moved off their defaults, so the
  Art-Net Node Report no longer overflows and silently drops fields.
- Editable lane port profile with HTTP API and UI warnings.
- Battery telemetry on rv1 hardware.
- Event-driven track telemetry and VS1053 hardening.
- Show info (character / performer names) is logged to the Net Log.
- DeviceManager discovers and manages Radius nodes alongside Primus receivers.
- Launching against an already-running Central now explains what it found and
  what it can do about it, instead of silently attaching.

### Firmware

- NimBLE dropped from the V1 Radius build, reclaiming about 264 KB of flash.

## Validation

- `RadiusCentral.app` Developer ID signed with network entitlements, notarized, and stapled
- `RadiusCentral-0.97-macOS-arm64.dmg` signed, notarized, stapled, and verified with `hdiutil verify`
- LaunchServices smoke: `open -n V5/dist/macos/RadiusCentral.app --args --port 8098 --no-browser` then `curl -s http://127.0.0.1:8098/api/runtime`
- Sender test suite: 457 passing
- Hardware check against a V1 Huzzah32 on firmware 4.0: sequential and
  concurrent SD listings return the full card

## Assets

- `RadiusCentral-0.97-macOS-arm64.dmg`
- `RadiusCentral-0.97-macOS-arm64.dmg.sha256`

## SHA-256

```text
01c1ee38e6b5582381786959b6bdf37e509afa5282782445ba57620676d0489b  RadiusCentral-0.97-macOS-arm64.dmg
```
