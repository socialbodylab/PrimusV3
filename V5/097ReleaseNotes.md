# PrimusCentral and DeviceManager v0.97

**First release built from the V5 unified sender tree.** Previous PrimusCentral
(v0.92) and DeviceManager (v0.96) releases were built from V4.

Bundled receiver firmware: **Primus 3.14.1**, **Radius 4.1.1**.

## Headline: Show / Setup / Watch UDP lane split

Receiver traffic is now separated onto three UDP lanes instead of sharing one
socket. See [docs/systems/PORT_ORGANIZATION.md](../docs/systems/PORT_ORGANIZATION.md).

| Lane | Port | Carries |
|------|------|---------|
| **Show** | 6454 (Primus) / 6456 (Radius audio) | ArtDmx, ArtPoll — Eos-compatible, unchanged |
| **Setup** | **6457** (new) | Management, rename, IP, output/receive config, show info, FTP gate |
| **Watch** | 6455 | PST / PFP / PTR telemetry (outbound from receivers) |

The point is isolation: commissioning bursts no longer land in the same receive
queue as show data, and the three lanes can be firewalled separately. This does
**not** create extra WiFi bandwidth — one radio still shares airtime.

- Primus firmware binds Show `:6454` and Setup `:6457`; Radius adds Setup `:6457`
  alongside audio `:6456`.
- All lane ports are overridable per device (NVS-backed) and per sender profile.
- `PORT_DUAL_LISTEN` remains enabled for this release, so Setup opcodes are still
  accepted on the Show port during migration. Existing receivers keep working.
- Recovery path is unchanged: discover on `:6454`, open Setup on the advertised
  or default `:6457`, then reset ports via `SET_LANE_PORTS` or the boot window.

## Discovery: lane advertisement and a Node Report truncation fix

The ArtPollReply Node Report is a hard 64-byte Art-Net field. Advertising the
full `|SHOW:6454|MGMT:6457|TELE:6455` triple costs 30 bytes and, emitted
unconditionally, overflowed that buffer on **every** device regardless of its
configuration — silently dropping `|IP:`, `|U:`, `|G:` and all per-output
tuples. Senders read affected nodes as `ip_mode: unknown` with no universe base.

Fixed in firmware 3.14.1:

- New **`L` feature flag** in `F:` marks a node as lane-aware. Lane ports are now
  advertised **only when moved off their default**, so a node on defaults emits
  no lane token and the sender infers the documented defaults from `L`. A node
  without `L` is pre-lane firmware and keeps Setup on the Show port.
- Node Report tokens are now priority-ordered, dropped from the bottom when space
  runs out: `F:` → `B:` → `IP:` → `U:` → moved-lane tokens → per-output tuples →
  `G:`. `G:` ranks last because no sender code parses it.
- Every token is appended only if it fits **whole**. A truncated `|MGMT:645`
  parses as a plausible port number and would send all Setup traffic into the
  void — worse than not advertising at all.

## PrimusCentral

- **Settings → UDP Lanes** — editable Show/Setup/Watch defaults for new sessions,
  with validation that Setup differs from both Show ports and from Watch.
- **Eos warning on device cards** — a node whose Show lane has been moved off 6454
  is flagged, since a stock Art-Net console sends to 6454 and will silently miss it.

## DeviceManager

- **Per-device lane ports** — expanded cards show the node's live
  `Show/Setup/Watch` values and can rewrite them (Primus via management `0x17`,
  Radius via ArtLanePorts `0x8220`).
- Lane configuration is gated like IP config, honours production lock, and works
  under `--monitor-only` through the existing transient-connection path.

## Sender

- `GET /api/state` now reports resolved `port_show` / `port_setup` / `port_watch`
  per device. Previously the lane UI ran entirely on hardcoded fallbacks, so the
  editor prefilled Setup incorrectly and could not be saved.
- Device capabilities carry `lane_aware`; Setup sends resolve to 6457 for
  lane-aware nodes and fall back to the Show port for legacy firmware.
- New `GET|POST /api/network/lane_ports` and `GET|POST /api/device_lane_ports`.

## Compatibility

Existing receivers that only listen on `:6454` keep working — senders fall back
Setup → Show when a node does not advertise lane awareness, and dual-listen is
still on in this firmware. Devices flashed with 3.14.1 report their IP mode and
universe base correctly again; devices left on the earlier 3.14.0 build will
still show `unknown` IP mode until reflashed.

## Packaging

- **Bundle version fixed** — PyInstaller left `CFBundleShortVersionString` and
  `CFBundleVersion` at `0.0.0`, so every previously shipped build reported
  `0.0.0` to Finder's Get Info and to any OS-level version check while the DMG
  name and in-app version said otherwise. Both keys are now stamped with the
  release version before signing. This also applies to RadiusCentral builds.

## Validation

- 374 stdlib unittests pass; `py_compile` clean across `V5/sender`
- Primus firmware compiles for all three board profiles (`-v1`, `-v2`, `-v3`)
- Verified on hardware against a V1 Huzzah32 and a V2 Feather: Show lane at
  30 fps ArtDmx, Setup lane rename/hello/telemetry-target on `:6457`, Watch lane
  telemetry on `:6455`; DeviceManager additionally verified under `--monitor-only`
  (no auto-connect, `/api/connect_all` → 409, one-off setup actions still work)
- Both apps Developer ID signed with network entitlements, notarized, and stapled
- Both DMGs signed, notarized, stapled, and verified with `hdiutil verify`

## Assets

- `PrimusCentral-0.97-macOS-arm64.dmg`
- `PrimusCentral-0.97-macOS-arm64.dmg.sha256`
- `DeviceManager-0.97-macOS-arm64.dmg`
- `DeviceManager-0.97-macOS-arm64.dmg.sha256`

## SHA-256

```text
ba294e744f16d6e1602a6af201b37140b18ba331b8e5baeaa98c914447d308a7  PrimusCentral-0.97-macOS-arm64.dmg
eaf25da4ec33f53a7d7c8d1e7cf32cf30bd0f9f5a5df4191d6d9a75919e44fed  DeviceManager-0.97-macOS-arm64.dmg
```
