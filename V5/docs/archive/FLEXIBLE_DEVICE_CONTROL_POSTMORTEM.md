# Flexible Device Control: Post-mortem and Implementation Handoff

**Project:** PrimusV3 V4

**Document date:** 2026-07-15

**Implementation context:** V4 flexible receiver setup layer, documented by the
[v0.94 source release notes](094ReleaseNotes.md)

**Final implementation head before this handoff:** `ea4c78f4fc2b5e06cb3b085e263ff04e7cd8ba54`

This document is the implementation handoff for the V4 Primus flexible-control
work. It is written for future maintainers, commissioning operators, and
third-party controller authors. The normative details remain the source and
protocol tests; links below point to those sources.

## Table of contents

1. [Executive summary](#executive-summary)
2. [Original problems and root causes](#original-problems-and-root-causes)
3. [Goals, non-goals, and deferred work](#goals-non-goals-and-deferred-work)
4. [Architecture before and after](#architecture-before-and-after)
5. [Detailed implementation](#detailed-implementation)
6. [Wire protocol reference](#wire-protocol-reference)
7. [Sender state and HTTP API](#sender-state-and-http-api)
8. [Persistence and migration](#persistence-and-migration)
9. [Important file inventory](#important-file-inventory)
10. [Operator and integration workflows](#operator-and-integration-workflows)
11. [Compatibility behavior](#compatibility-behavior)
12. [Concurrency and reliability hardening](#concurrency-and-reliability-hardening)
13. [Validation evidence](#validation-evidence)
14. [Risks, troubleshooting, and operational guidance](#risks-troubleshooting-and-operational-guidance)
15. [Future work](#future-work)
16. [Implementation layers and commits](#implementation-layers-and-commits)

## Executive summary

Primus receivers are no longer limited to a short list of output-type IDs whose
meaning must be inferred from discovery metadata. V4 now has a controller-neutral
commissioning model:

- ArtDmx continues to carry RGB bytes in physical wire order.
- A versioned, acknowledged Art-Net management protocol reads and writes complete
  receiver configuration.
- Each physical output, A0 and A1, always exists as a stable slot, including when
  it is Off.
- Outputs can be linear strips or grids with 1-170 physical pixels, explicit
  traversal/wiring metadata, and an independent virtual send resolution.
- Telemetry goes only to an explicitly configured unicast target and uses a
  unified `PST` status packet.
- Prototype mode is editable; production mode locks commissioning fields while
  leaving output, discovery, monitoring, and Hello available.
- PrimusCentral and DeviceManager expose the same shared setup actions. Radius
  remains isolated, and DeviceManager's monitor-only/mobile safety behavior is
  preserved.
- Sender-side presets make descriptors reusable without writing firmware state
  until a preset is explicitly applied.

The work also hardened persistence and concurrency. Firmware commits complete
configuration as checksummed single-record writes, mutation replies are replayable
for safe retries, sender management I/O is serialized per device and kept outside
the animation lock, and the UI guards asynchronous drafts and state refreshes by
device identity and generation.

## Original problems and root causes

### Output identity was too rigid

The older model selected one of a small number of output type IDs. This worked for
known costume pieces, but could not accurately represent arbitrary strip lengths
or grid wiring. A slot with zero pixels was often treated as absent, so an Off
output could disappear from setup and become difficult to recover without
reflashing.

**Root cause:** physical connector identity, active pixel count, render layout,
and transport resolution were conflated into one legacy type.

### Configuration was write-oriented and weakly acknowledged

Legacy custom opcodes could request rename, output type, receive mode, virtual
resolution, IP, and show-info changes, but there was no single authoritative
readback of the complete configuration and no uniform ACK/NACK contract.

**Root cause:** controls were added incrementally around Art-Net discovery rather
than around a versioned configuration transaction.

### Telemetry destination was implicit or ambiguous

Learning a telemetry destination from ArtDmx or the latest packet source would be
unsafe on networks shared with EOS, multiple tools, or more than one sender.

**Root cause:** traffic source and monitoring ownership were not separated.

### Production configuration could be changed too easily

Commissioning controls remained available during a show, and different hardware
profiles did not have a unified recovery story.

**Root cause:** no persisted operating mode existed to distinguish editable
prototype devices from locked production devices.

### Persistence could form hybrid records

Multi-key writes could be interrupted between fields. Compile-time overrides and
legacy mirrors could also be mistaken for authoritative state after a partial
write.

**Root cause:** related fields and override-consumption markers were stored
separately without a checksum or atomic authority boundary.

### Concurrent management paths could race

Art-Net management queries share UDP port 6454, sender state has an animation
lock, and browser polling can overlap user mutations. Early versions of the UI
could overwrite a draft while a request or state fetch was in flight.

**Root cause:** serialization and generation ownership were not explicit at the
firmware replay, UDP query, sender device, preset-file, and browser-draft layers.

## Goals, non-goals, and deferred work

### Goals

- Preserve standard ArtDmx output and existing receivers.
- Describe arbitrary supported output geometry without changing RGB transport.
- Make configuration reads authoritative and writes acknowledged.
- Keep both physical connectors visible and recoverable from Off.
- Make telemetry opt-in and destination-explicit.
- Provide a safe production lock and profile-appropriate recovery.
- Expose the same capability-aware setup contract through firmware, sender state,
  HTTP, DeviceManager, and PrimusCentral.
- Preserve DeviceManager monitor-only/mobile behavior and Radius separation.
- Make firmware and preset persistence resilient to interruption and concurrency.
- Provide executable protocol, API, UI, and network-concurrency regressions.

### Non-goals

- ArtDmx ownership, HTP/LTP merging, or multi-sender arbitration.
- Authentication or authorization on the trusted show LAN.
- RGBW, more than two physical outputs, or more than 170 pixels per physical port.
- Changing ArtDmx into logical grid coordinate order.
- Giving Mobile View new commissioning permissions.
- Applying output presets automatically to firmware merely because they exist in
  the sender's preset file.

### Deferred multi-sender arbitration

Management protocol v1 has no lease, owner ID, generation authority, or lock
token. Use one commissioning authority at a time, then enter production mode.
Do not infer ownership from the last ArtDmx sender or telemetry target. A future
protocol can add explicit arbitration without retrofitting a fragile heuristic
into v1.

## Architecture before and after

| Concern | Before | After |
|---|---|---|
| Physical outputs | Active outputs inferred from type/count | Stable A0 and A1 slots; Off is a valid descriptor |
| Geometry | Built-in type ID | Complete 12-byte `OutputDescriptor` |
| Pixel transport | ArtDmx RGB | Unchanged: ArtDmx RGB in physical wire order |
| Configuration writes | Independent legacy opcodes | Versioned request/reply with ACK/NACK and request ID |
| Configuration reads | Discovery fragments and local assumptions | Authoritative `GET_CONFIG` |
| Telemetry | Older PFP/PBT paths or ambiguous target ownership | Explicit unicast target and `PST` v1 |
| Safety | No persisted commissioning lock | Prototype/production mode and recovery paths |
| Persistence | Multiple legacy keys | Checksummed authoritative records plus compatibility mirrors |
| Sender concurrency | Shared query/state paths could contend | UDP query lock, per-device lock, two-phase state merge |
| UI concurrency | Polling could replace edits | Dirty revisions, pending identity, guarded state generations |

### Controller-neutral data flow

1. A lighting controller sends ArtDmx directly to the receiver's configured
   universe or universes.
2. A commissioning client uses management request `0x8140` and receives reply
   `0x8141`, or calls the V4 sender's HTTP facade.
3. The receiver validates and persists the requested configuration, ACKs or NACKs
   it, and returns authoritative state through `GET_CONFIG`.
4. If and only if `teleTarget` is configured, the receiver sends one `PST` v1
   heartbeat per second to UDP 6455 at that address.

ArtDmx does not select the telemetry destination and does not carry logical grid
coordinates. Descriptor metadata tells a controller how logical coordinates map
to physical wire positions; the transmitted bytes remain wire order.

## Detailed implementation

### Stable A0/A1 physical slots and Off recovery

Both slots are inventoried in discovery and returned by `GET_CONFIG`, even when a
slot is Off. Split mode keeps A0 at base universe and A1 at base+1. Combined mode
uses one universe and concatenates A0 bytes before A1 bytes. UI helpers pad to
two physical rows, so an Off slot still has a selector and can be changed to a
built-in, custom descriptor, or preset.

Never interpret `physical_pixels == 0` as "connector does not exist." It means
the stable connector is Off.

### OutputDescriptor

Each slot uses the following fields:

| Field | Values and constraints | Meaning |
|---|---|---|
| `enabled` | Boolean | False selects canonical Off |
| `layout` | `off`, `linear`, `grid` | Physical/logical layout |
| `physical_pixels` | 1-170 when enabled | LEDs physically wired to the port |
| `rows` | Positive integer for grid | Grid row count |
| `columns` | Positive integer for grid | Grid column count |
| `traversal_axis` | `row_major`, `column_major` | Primary logical traversal |
| `scan_pattern` | `progressive`, `serpentine` | Same direction each line or alternating |
| `start_corner` | `top_left`, `top_right`, `bottom_left`, `bottom_right` | Logical origin and first wire position |
| `virtual_pixels` | 1 to physical count | Number of RGB pixels sent before receiver upscaling |

For a grid, `rows * columns` must equal `physical_pixels` and be 1-170. Inputs
must be finite integers; fractional values are rejected rather than rounded.
Combined mode validates that the total virtual pixel count fits one ArtDmx
universe (170 RGB pixels).

Example: a 4x8 badge wired row-major, serpentine, from the top-left has 32
physical pixels. With `virtual_pixels: 1`, the sender sends one RGB pixel and the
receiver expands it across the physical output. With `virtual_pixels: 32`, the
controller sends all physical wire positions.

### Wire-order semantics

Grid fields describe logical-to-wire mapping; they do not reorder ArtDmx inside
the receiver. A third-party renderer should:

1. Enumerate logical coordinates according to traversal axis.
2. Reverse each alternating row or column for serpentine wiring.
3. Transform the start corner by reversing the horizontal and/or vertical
   direction.
4. Place each logical pixel into its physical wire index.
5. Send RGB triples in that physical index order.

The existing Primus sender performs this mapping. A console that already renders
physical wire order can ignore logical geometry while still respecting physical
and virtual counts.

### Output presets

[`sender/output_presets.py`](sender/output_presets.py) provides schema-v1
sender-side presets. Built-ins are Off, Short Strip (30), Long Strip (72), Grid
(8x8), Small Grid (4x8, virtual 1), and Extra Long Strip (122). User presets can
be created, renamed, updated, deleted, and applied to A0 or A1. Built-ins are
immutable and non-deletable.

Presets store descriptor templates, not receiver ownership. Creating or editing a
preset does not change a receiver. Applying it validates the complete resulting
two-slot receive configuration and then sends the same management descriptor
mutation used by the custom editor. Group application returns per-device results.
Bulk static IP remains intentionally unsupported.

### Versioned acknowledged management

Management uses Art-Net custom opcodes `0x8140` (request) and `0x8141` (reply),
protocol version 1, a 20-byte envelope, a 16-bit request ID, payload length,
operation, status, and error code. Mutations receive ACK or a structured NACK.
After ACK, the sender normally performs `GET_CONFIG`.

Firmware caches four complete deterministic replies for 30 seconds. A retry with
the same source address, request ID, version, operation, lengths, payload, and
request status/error receives the cached reply rather than reapplying a mutation.
Internal-error NACKs are not cached.

### Authoritative GET_CONFIG

`GET_CONFIG` returns operating mode, unlock state, receive mode/base universe,
telemetry target, IP mode/address/gateway/subnet, both complete descriptors, and
technical/character/performer identity. Discovery remains intentionally compact;
the 64-byte Node Report is not the complete configuration database.

### Explicit telemetry target and PST

`teleTarget` is a persisted four-byte unicast IPv4 address. `0.0.0.0`, a missing
key, or the clear HTTP action means no telemetry. The receiver never learns or
changes it from ArtDmx, ArtPoll, EOS, or the latest packet source.

`PST` v1 is a 28-byte packet sent approximately once per second with MAC-derived
phase jitter. It contains sequence, uptime, flags, rendered FPS x10, packet rate
x10, RSSI, firmware version, operating mode, battery mode, battery millivolts,
battery percent, and boot-unlock time. Sender diagnostics track age, health,
accepted/duplicate/out-of-order packets, inferred loss, sequence wrap, uptime
reset, and confirmed reboot.

Reordered packets do not automatically count as reboots. Reboot detection uses
sequence and uptime plausibility, confirmation, and a generation guard.

### Battery semantics

| Profile | Measurement | PST behavior |
|---|---|---|
| V1 HUZZAH32 | LiPo on A13/GPIO35 through onboard divider | Voltage and percent when valid; no VBUS sense, so normal valid mode is `battery` |
| V2 ESP32 Feather | No supported battery measurement | `unavailable`, 0 mV, percent 255 |
| V3 custom PCB | Regulated 5V rail on A4/GPIO14 through 100k/100k divider | x2 ADC scale, regulated-rail droop estimate; TFT may show time remaining |

Battery mode values are `battery`, `charging`, `plugged`, `switch_off`, `fault`,
and `unavailable`. Consumers must honor the battery-valid flag and mode rather
than interpreting 0 mV as an empty battery.

### Prototype, production, lock, and recovery

Prototype is the default editable mode. Entering production persists `opMode` and
locks:

- technical name and show metadata;
- DHCP/static IP configuration;
- output descriptors;
- receive mode and base universe;
- telemetry target.

Production does not disable ArtDmx, ArtPoll discovery, PST monitoring, or Hello.
Legacy mutation packets are ignored while locked; management mutations receive
`NACK/LOCKED`.

- **V3:** recover locally with the documented D1 long press. D1 short toggles the
  TFT while production starts with the display off.
- **V1/V2:** reboot and request boot-window unlock during the first 60 seconds.
  The current open/remaining state is reported by `GET_CONFIG` and PST.

Entering production is intentionally guarded in the UI. There is no ordinary
remote "turn production off" operation after the recovery window.

### UI behavior

[`sender/web/js/device-conn.js`](sender/web/js/device-conn.js) is the additive
shared store used by PrimusCentral, DeviceManager, and RadiusCentral. It owns
management capability gating, descriptor validation/editor state, presets,
telemetry setup, lock/recovery actions, feedback, and group operations.

DeviceManager and PrimusCentral provide:

- stable Off/A0/A1 rows;
- descriptor editing and wiring summary/order preview;
- preset CRUD and application;
- explicit telemetry target and diagnostics;
- production status, confirmation, and recovery guidance;
- `readback_pending` as "Applied; awaiting refresh," not failure.

Descriptor editor DOM is created with Alpine `template x-if`, so null drafts are
not dereferenced during initialization. Telemetry drafts use dirty revisions,
device identity, pending submission identity, and guarded state-fetch generations.
Out-of-order requests or polling cannot replace a newer edit.

Radius devices fail the Primus management capability predicate and retain their
simplified audio cards. Mobile View remains read-only except its existing Hello
action.

### DeviceManager monitor-only behavior

Monitor-only still prevents `/api/connect` and `/api/connect_all` and avoids
standing ArtDmx, including idle keepalives. One-off setup actions create only the
transient management/config exchange required for that action. They do not leave
the device connected for show output. When DeviceManager attaches to an already
running PrimusCentral backend, that backend remains the legitimate show-control
sender.

## Wire protocol reference

The executable reference is
[`sender/primus_protocol.py`](sender/primus_protocol.py), mirrored by
[`Arduino/primusV3_receiver/management_protocol.h`](Arduino/primusV3_receiver/management_protocol.h).

### Opcodes and packet families

| Opcode/magic | Direction | Purpose |
|---|---|---|
| `0x5000` ArtDmx | Controller to receiver | RGB physical-wire output |
| `0x6000` ArtAddress | Controller to receiver | Legacy rename |
| `0x8100` ArtOutputConfig | Controller to receiver | Legacy built-in output type |
| `0x8110` ArtReceiveConfig | Controller to receiver | Legacy split/combined receive config |
| `0x8130` ArtVirtualResolution | Controller to receiver | Legacy virtual pixel count |
| `0x8140` | Commissioning client to receiver | Management v1 request |
| `0x8141` | Receiver to commissioning client | Management v1 ACK/NACK reply |
| `0x8200` ArtIPConfig | Controller to receiver | Legacy DHCP/static IP |
| `0x8210` ArtShowInfo | Controller to receiver | Legacy character/performer metadata |
| `PST` on UDP 6455 | Receiver to configured target | Unified status v1 |

### Management operations

| Value | Operation | Payload/result |
|---|---|---|
| `0x01` | `GET_CONFIG` | No request payload; complete config reply |
| `0x10` | `SET_OUTPUT_DESCRIPTORS` | Atomic pair of A0/A1 descriptors |
| `0x11` | `SET_TELEMETRY_TARGET` | Four-byte IPv4; zero clears |
| `0x12` | `SET_OPERATING_MODE` | Prototype/production subject to recovery rules |
| `0x13` | `SET_RECEIVE_CONFIG` | Split/combined and base universe |
| `0x14` | `SET_IP_CONFIG` | DHCP/static address data |
| `0x15` | `SET_IDENTITY` | Technical, character, performer names |
| `0x16` | `BOOT_WINDOW_UNLOCK` | V1/V2 production recovery during boot window |

Reply status is `ACK=0` or `NACK=1`. Error codes are none, malformed packet,
unsupported version, unsupported operation, invalid payload, locked, out of
range, not available, and internal error.

### Management envelope

| Offset | Size | Encoding | Field |
|---|---:|---|---|
| 0 | 8 | bytes | `Art-Net\0` |
| 8 | 2 | little-endian | opcode |
| 10 | 2 | big-endian | Art-Net protocol version (14+) |
| 12 | 1 | integer | management protocol version |
| 13 | 1 | integer | operation |
| 14 | 2 | big-endian | request ID |
| 16 | 2 | big-endian | payload length |
| 18 | 1 | integer | reply status; zero in requests |
| 19 | 1 | integer | error code; zero in requests |
| 20 | variable | bytes | operation payload |

### OutputDescriptor wire layout

Each descriptor is 12 bytes:

| Offset | Size | Field |
|---|---:|---|
| 0 | 1 | enabled |
| 1 | 1 | layout: off=0, linear=1, grid=2 |
| 2 | 2 | physical pixels, big-endian |
| 4 | 1 | rows |
| 5 | 1 | columns |
| 6 | 1 | traversal: row-major=0, column-major=1 |
| 7 | 1 | scan: progressive=0, serpentine=1 |
| 8 | 1 | start corner: TL=0, TR=1, BL=2, BR=3 |
| 9 | 1 | reserved, must be zero |
| 10 | 2 | virtual pixels, big-endian |

Disabled descriptors must use the canonical Off shape: all dimensions/counts
zero with default enum values. Third-party clients should use the codec and
golden tests rather than building packets from ad hoc offsets.

### Discovery contract

Management-capable nodes advertise `PV3CAP1` and the `G` feature. `G:1P` means
protocol v1 prototype; `G:1L` means protocol v1 locked/production. The typical
feature string is `F:RIOHBMSG`: rename, IP, output, Hello, battery, receive mode,
show info, and management. Full descriptors are fetched through `GET_CONFIG`.
Legacy name-based fallback remains for older Primus firmware, but must not be
treated as proof of a specific board profile.

## Sender state and HTTP API

[`sender/state.py`](sender/state.py) maintains descriptor, telemetry, lock, and
diagnostic fields in each Primus device record. The HTTP facade in
[`sender/server.py`](sender/server.py) is the preferred integration point for
tools already using the V4 sender.

| Method and route | Purpose |
|---|---|
| `GET /api/device_full_config?device=N` | Return sender's current complete device config |
| `GET /api/device_lock_state?device=N` | Return management support and lock/recovery state |
| `POST /api/refresh_device_full_config` | Perform authoritative `GET_CONFIG` |
| `POST /api/apply_device_output_descriptor` | Replace one slot while validating the two-slot result |
| `POST /api/set_device_telemetry_target` | Set IPv4 target; null/`0.0.0.0` clears |
| `POST /api/enter_device_production_mode` | Enter persisted production lock |
| `POST /api/unlock_device_boot_window` | Request V1/V2 recovery during boot window |
| `GET /api/output_presets` | List built-in and user presets |
| `GET /api/output_presets/:id` | Read one preset |
| `POST /api/output_presets` | Create or update a user preset |
| `DELETE /api/output_presets/:id` | Delete a user preset |

State mutation routes return structured JSON errors and meaningful HTTP status,
including 409 for conflict/locked conditions. After an acknowledged mutation,
readback failure returns success with `readback_pending: true` and a warning.
Clients should display this as applied but unconfirmed, then explicitly refresh.

## Persistence and migration

### Firmware NVS

The Preferences namespace is `primus35`.

| Authoritative key/record | Contents | Compatibility mirrors or migration |
|---|---|---|
| `outDescAll` (28 bytes) | schema, slot count, both 12-byte descriptors, CRC-16/CCITT | migrates `outSchema` + `outDesc0/1`, then `otype0/1` + `vpx0/1`; continues writing type/virtual mirrors |
| `recvCfg` (54 bytes) | schema, receive mode, base universe, applied override build ID, CRC | migrates `recvMode` and `univBase`; mirrors remain non-authoritative |
| `netCfg` (64 bytes) | schema, DHCP/static, IP/gateway/subnet, applied override build ID, CRC | migrates `staticIP`, `gateway`, `subnet` |
| `identity` (199 bytes) | schema, technical/character/performer names, applied override build ID, CRC | migrates `shortName`, `characterName`, `performerName` |
| `teleTarget` | four-byte unicast IPv4 | missing/removed means disabled |
| `opMode` | prototype or production byte | defaults to prototype |

An authoritative record is a single Preferences write. Compatibility mirrors are
written only after that commit and are not used to reconstruct a present but
corrupt authoritative record. Invalid checksum/schema data falls back to safe
defaults and is recommitted. Compile-time override consumption is stored in the
same authoritative record as the fields it controls, making the override
one-time and reset-safe.

### Sender persistence

- Device state remains in `.primus_state.json` through [`sender/paths.py`](sender/paths.py).
- User output presets use `output_presets.json`, schema 1, through
  [`sender/output_presets.py`](sender/output_presets.py).
- Preset writes use a temporary file and `os.replace`.
- A shared in-process `RLock` and cross-process `.lock` file serialize preset
  transactions. The lock file is runtime-only and must not be committed.
- Built-ins are code-defined and merged with user presets on read.

## Important file inventory

| File/module | Responsibility |
|---|---|
| [`Arduino/primusV3_receiver/config.h`](Arduino/primusV3_receiver/config.h) | Profiles, pins, limits, opcodes, protocol sizes, NVS schemas |
| [`Arduino/primusV3_receiver/management_protocol.h`](Arduino/primusV3_receiver/management_protocol.h) | Management enums, replay cache, descriptor codec, descriptor persistence/migration |
| [`Arduino/primusV3_receiver/receive_mode.h`](Arduino/primusV3_receiver/receive_mode.h) | Split/combined universe behavior and atomic receive record |
| [`Arduino/primusV3_receiver/battery.h`](Arduino/primusV3_receiver/battery.h) | V1/V2/V3 battery acquisition and modes |
| [`Arduino/primusV3_receiver/primusV3_receiver.ino`](Arduino/primusV3_receiver/primusV3_receiver.ino) | Packet dispatch, management operations, identity/network/mode/target persistence, PST emission |
| [`sender/primus_protocol.py`](sender/primus_protocol.py) | Dependency-free executable wire codec |
| [`sender/artnet.py`](sender/artnet.py) | Discovery, serialized management transport, PST listener/diagnostics |
| [`sender/state.py`](sender/state.py) | Device schema, per-device transaction control, authoritative merge, API-facing operations |
| [`sender/server.py`](sender/server.py) | HTTP management and preset routes |
| [`sender/output_presets.py`](sender/output_presets.py) | Built-ins, validation, atomic JSON persistence, process locking |
| [`sender/web/js/device-conn.js`](sender/web/js/device-conn.js) | Shared management UI store and validation |
| [`sender/web/js/app-devices.js`](sender/web/js/app-devices.js) | DeviceManager polling and generation-gated state merge |
| [`sender/web/js/app-primus.js`](sender/web/js/app-primus.js) | PrimusCentral polling and generation-gated state merge |
| [`sender/web/index-devices.html`](sender/web/index-devices.html) | DeviceManager setup surfaces |
| [`sender/web/index-primus.html`](sender/web/index-primus.html) | PrimusCentral setup surfaces |
| [`sender/web/css/style.css`](sender/web/css/style.css) | Shared compact setup/editor styles |
| [`sender/tests/test_primus_protocol.py`](sender/tests/test_primus_protocol.py) | Golden protocol and firmware source contracts |
| [`sender/tests/test_primus_management_transport.py`](sender/tests/test_primus_management_transport.py) | UDP request/reply, retry, ACK/NACK behavior |
| [`sender/tests/test_management_state.py`](sender/tests/test_management_state.py) | State transactions, locks, readback, conflicts |
| [`sender/tests/test_management_server_routes.py`](sender/tests/test_management_server_routes.py) | HTTP routes/status/error contracts |
| [`sender/tests/test_primus_telemetry.py`](sender/tests/test_primus_telemetry.py) | PST ordering, loss, reboot, battery mapping |
| [`sender/tests/test_output_presets.py`](sender/tests/test_output_presets.py) | Preset CRUD, atomicity, thread/process concurrency |
| [`sender/tests/test_management_ui_contracts.py`](sender/tests/test_management_ui_contracts.py) | Static and Node runtime UI races/contracts |
| [`sender/tests/test_management_network_soak.py`](sender/tests/test_management_network_soak.py) | Concurrent PST listener, loopback ArtDmx/management UDP, real HTTP refresh, animation-tick proxy |

Related overview/reference documents:
[API_REFERENCE.md](../API_REFERENCE.md),
[ARCHITECTURE.md](ARCHITECTURE.md),
[FIRMWARE_DEVELOPMENT.md](FIRMWARE_DEVELOPMENT.md), and
[v0.94 release notes](094ReleaseNotes.md).

## Operator and integration workflows

### Configure a new device

1. Flash the correct V1, V2, or V3 profile.
2. Put the commissioning computer and receiver on the same trusted LAN.
3. Open DeviceManager or PrimusCentral and wait for discovery/sync.
4. Confirm the hardware profile. Treat legacy/unconfirmed profiles as unknown.
5. Refresh full configuration.
6. Set technical, character, and performer names.
7. Configure DHCP/static IP, receive mode, and base universe.
8. Configure A0 and A1; explicitly set unused slots to Off.
9. Set the telemetry target to the selected sender/interface IPv4 if monitoring is
   desired.
10. Verify PST health, sequence, FPS/packet rate, and battery semantics.
11. Send test ArtDmx/Hello and verify physical wiring.
12. Enter production only after saving a recovery plan.

### Create a custom strip

1. Open the descriptor editor for A0 or A1.
2. Select Strip.
3. Enter a whole-number physical length from 1 to 170.
4. Set virtual pixels from 1 to the physical length.
5. Review the summary and apply.
6. Confirm authoritative readback. If "Applied; awaiting refresh" appears, refresh
   again before locking production.

### Create a custom grid

1. Select Grid.
2. Enter whole-number rows and columns whose product is 1-170.
3. Select row-major or column-major traversal.
4. Select progressive or serpentine scan.
5. Select the physical start corner.
6. Set virtual pixels from 1 to physical count.
7. Compare the compact order preview with the actual wiring.
8. Apply and test a diagnostic pattern before production lock.

### Manage and apply presets

1. Build or load the desired descriptor in the editor.
2. Save it as a user preset with a unique name.
3. Rename/update it as the template evolves.
4. Apply it explicitly to A0 or A1.
5. For a group, preview the target group and review per-device results.
6. Confirm before deleting. Built-ins cannot be changed or deleted.

### Configure or clear telemetry

1. Choose the commissioning/monitoring host's stable interface IPv4.
2. Use "Use sender IP" or enter the address manually.
3. Apply and verify the configured target in authoritative readback.
4. Confirm `PST` protocol/version and a healthy age.
5. Use Clear to remove the target. Unset means the receiver sends no PST.

Do not point telemetry at a broadcast address and do not expect ArtDmx/EOS to
change it.

### Enter production and recover

1. Confirm names, IP, descriptors, receive mode, and telemetry first.
2. Read the UI explanation of locked fields.
3. Confirm the guarded production action.
4. Verify the locked badge and continued ArtDmx/Hello/PST operation.
5. To recover V3, use the physical D1 long press.
6. To recover V1/V2, reboot and request unlock within 60 seconds, then edit while
   the reported window is open.

### Third-party direct Art-Net integration

1. Discover `PV3CAP1` and check for management `G`; parse `G:1P`/`G:1L`.
2. Bind the request/reply socket as required by Art-Net port 6454 behavior.
3. Generate a unique 16-bit request ID and send `GET_CONFIG`.
4. Validate opcode, protocol version, source IP, request ID, operation, length,
   status, and error.
5. Preserve both descriptors when changing one slot; `SET_OUTPUT_DESCRIPTORS` is
   a two-slot atomic operation.
6. Retry a timed-out request with the identical request ID and payload so firmware
   replay prevents duplicate mutation.
7. Treat ACK as applied. Perform `GET_CONFIG`; if readback times out, report
   applied/unconfirmed rather than resending with a new ID immediately.
8. Render logical grid content into physical wire order and send normal ArtDmx.
9. Set telemetry explicitly only when the controller is prepared to receive PST
   on UDP 6455.

### Third-party HTTP integration

Prefer the HTTP facade when the V4 sender is already the commissioning authority.
Use the routes in [Sender state and HTTP API](#sender-state-and-http-api), honor
409 and structured error codes, and preserve `readback_pending`. Do not use
device list indices across a state refresh without revalidating device identity/IP.

### DeviceManager monitor-only limitations

- Monitoring and discovery are automatic.
- No standing ArtDmx connection is allowed.
- Connect/connect-all return 409.
- One-off setup packets are allowed and transient.
- Mobile View is not a setup surface.
- Monitor-only does not arbitrate against another commissioning sender; coordinate
  operators and use production lock.

## Compatibility behavior

- Legacy receivers remain discoverable and use capability-aware legacy controls.
- Legacy output type, receive mode, virtual resolution, IP, rename, and show-info
  packets remain accepted in prototype mode.
- Custom descriptors, full readback, explicit PST target, and production lock
  require management-capable firmware.
- The sender retains output type IDs and compatibility fallbacks; the flexible UI
  does not remove legacy tables.
- Atomic output migration order is earlier management per-slot records, then
  legacy type/virtual keys, then built-in defaults.
- Identity, network, and receive records migrate their compatibility keys once.
- Present but corrupt authoritative records are not rebuilt from stale mirrors.
- Old PFP/PBT parsing remains useful for older nodes, but new management firmware
  emits unified PST rather than new PFP/PBT.
- Radius discovery, audio opcodes, PTR/PFP telemetry, and cards are unchanged.

## Concurrency and reliability hardening

### Firmware

- Full request fingerprint and cached reply make identical retries idempotent.
- Payload/length/status/error are part of the fingerprint.
- Deterministic ACK/NACK replies are cached; internal failures are retriable.
- Checksummed authoritative records avoid hybrid reset state.
- Failed write verification rolls back or reports internal failure rather than ACK.

### Sender transport and state

- Art-Net request/reply exchanges sharing UDP 6454 are serialized.
- Each device has a lazy management lock, so same-device mutations serialize while
  different devices can proceed concurrently.
- Network I/O happens outside `ControllerState.lock`; animation ticks are not held
  behind management timeout windows.
- Two-phase operations snapshot intent, send, revalidate object/IP, and then merge.
- ACK followed by readback timeout updates expected local state and returns
  `readback_pending`.
- Removed or IP-changed devices produce conflict rather than receiving stale data.

### Presets

- Reads and mutations share a per-path in-process lock.
- Cross-process lock files protect read-modify-write transactions.
- Mutations reload from disk under lock.
- Temporary-file replacement prevents partial JSON.

### Browser UI

- Descriptor editors are instantiated only when a valid draft exists.
- Fractional dimensions are rejected before normalization.
- Telemetry drafts track edit revision, device IP, and pending submission identity.
- Telemetry mutations skip the generic immediate state fetch, validate their
  submission, then request a guarded refresh.
- App state fetches track start/completion generations. A newer accepted response
  prevents an older stale merge; a newer response rejected by its guard does not
  suppress an older valid response.
- Apply/clear completion cannot erase a newer edit made while the request is pending.

## Validation evidence

Final validation on the completed UI branch produced:

| Validation | Result |
|---|---|
| Non-packaging V4 sender suite | 343/343 passed |
| Full V4 sender suite | 349 run; only two established packaging baselines failed |
| Packaging baseline 1 | Test expects default app version `0.9`; implementation is `0.92` |
| Packaging baseline 2 | Windows Artifact Signing test cannot execute on macOS |
| Firmware compile | V1, V2, and V3 profiles passed |
| Python compile | `python3 -m py_compile V4/sender/*.py` passed |
| Web static validation | All JavaScript syntax checks and HTML parsing passed |
| UI contracts | 9/9 final static/runtime contracts passed |
| Patch hygiene | `git diff --check` passed |

The firmware compile evidence was rerun after protocol/UI integration. Firmware
sources were not changed by the final browser race-only commits.

### Soak scenario

[`test_management_network_soak.py`](sender/tests/test_management_network_soak.py)
uses:

- the real `PrimusTelemetryListener.run()` loop with a faithful datagram socket;
- many fake device PST heartbeat streams, including reordered packets;
- real loopback UDP ArtDmx traffic;
- a loopback receiver handling serialized management `GET_CONFIG`;
- the real HTTP server and concurrent `/api/refresh_device_full_config` requests;
- a concurrent `state.tick()` loop as the animation-lock blocking proxy.

It asserts stable telemetry target/config, accepted heartbeat volume, no false
reboot from reorder, actual ArtDmx and management-query counts, no overlapping
management queries, bounded completion, and robust worker cleanup even on failure.

### Focused regression coverage

- Golden codec and firmware source parity.
- ACK/NACK, retry, malformed packet, reply replay, and timeout behavior.
- Stable Off slots and descriptor migration.
- Per-device state serialization and cross-device concurrency.
- ACK/readback fallback and `readback_pending`.
- Preset thread/process locking and delete/update no-resurrection.
- PST loss/reorder/wrap/reboot and battery semantics.
- Alpine null-draft safety.
- Dirty telemetry drafts across polling.
- Edits and device replacement during pending apply/clear.
- Out-of-order mutation/state fetch completion.
- Rejected newer guarded fetch followed by an older valid response.

## Risks, troubleshooting, and operational guidance

### Operational guidance

- Use one commissioning authority.
- Prefer DHCP during initial commissioning; reserve/static addressing only after
  confirming the correct device.
- Configure and verify telemetry before production lock.
- Keep a documented physical recovery path for V3 and boot-window procedure for
  V1/V2.
- Test grid wiring with an index/order pattern, not only a solid color.
- Keep user preset files in normal app data and exclude `.lock` runtime artifacts.
- Treat legacy hardware-profile inference as unconfirmed.

### Troubleshooting

| Symptom | Likely cause | Action |
|---|---|---|
| A slot appears Off | Canonical disabled descriptor | Select a built-in/custom/preset and apply; do not reflash first |
| Descriptor rejected | Fraction, product mismatch, out-of-range count, combined virtual total >170 | Correct raw integers and validate both slots |
| Management 409/Locked | Production mode | Use V3 D1 recovery or V1/V2 boot-window unlock |
| Applied; awaiting refresh | ACK succeeded, `GET_CONFIG` timed out | Do not call it failure; refresh/discover and reconcile |
| No PST | Target unset/wrong interface, UDP 6455 conflict, network path | Read `teleTarget`, check target host/interface/firewall, clear stale app instances |
| False-looking battery zero | V2/unavailable semantics | Check valid flag and mode; 255 percent means unavailable |
| Increasing loss/reorder | Congestion, Wi-Fi quality, duplicate paths | Check RSSI and packet counters; do not infer reboot from one old packet |
| Preset lock file present | App/test process interrupted or still active | Stop active processes; never commit the runtime `.lock` file |
| DeviceManager emits show output | It attached to show-control backend rather than fresh monitor-only backend | Check `/api/runtime`; understand which backend owns output |
| Third-party retry reapplies | New request ID/payload was used | Retry the identical request fingerprint |

### Known risks

- No management ownership arbitration exists.
- The trusted-LAN HTTP API has no authentication boundary.
- Production recovery depends on hardware access or a short V1/V2 boot window.
- Node Report truncation remains possible; clients must use `GET_CONFIG`.
- Preset files are sender-local and can differ between commissioning computers.
- Virtual upscaling intentionally reduces addressable detail.
- Grid metadata interoperability depends on controllers following the same corner,
  traversal, and scan definitions.

## Future work

1. Define protocol-v2 multi-sender ownership/lease semantics.
2. Add explicit controller identity and conflict visibility without learning from
   ArtDmx.
3. Reconcile packaging version baselines and run Windows signing validation on
   Windows.
4. Add hardware-in-the-loop longevity testing for PST, production recovery, and
   interrupted NVS writes.
5. Consider preset import/export and show-bundle scoping.
6. Add richer wiring test patterns generated from descriptor metadata.
7. Evaluate authentication only if the deployment model moves beyond a trusted,
   isolated show network.
8. Keep Radius management separate unless a versioned product-neutral protocol is
   deliberately designed.

## Implementation layers and commits

The work was developed as a stacked plan. Commit identities below are useful when
auditing the implementation history; some layers include follow-up reliability
commits after independent review.

| Layer/date | Commit | Summary |
|---|---|---|
| Firmware protocol, 2026-07-15 | `fca0b938855223696e2c09a1deb2d39ce6fff4f3` | Final layer-1 firmware/protocol fixes after V1/V2/V3 compile and focused review |
| Firmware atomic persistence review | `576297deba47ee0bed9602609f6391edc45c7651` | Authoritative checksummed records and migration hardening |
| Sender/API integration | `737df10713273cb6675819dc38b94c1ab6420316` | Management transport/state/API plus integrated atomic firmware and UDP 6454 serialization |
| Sender reliability | `b89e4eea21ff458411e2743f5cf6f45fd7b64690` | Reply replay, lock/readback hardening, PST ordering, preset persistence serialization |
| Shared setup UI | `607b610bdb3c936c780edfdb83c6839c342e4b95` | Flexible Primus setup UI, presets, telemetry, lock UX, docs/tests |
| UI review fixes | `2ad3d634039db380333077709523bec4dea08c07` | Dirty drafts, Alpine gating, integer validation, faithful soak |
| Pending-edit safety | `0c71b2d0502fe81cc995ccbc3bcf98d8b00d2ef0` | Preserve edits during apply/clear; robust soak cleanup |
| Refresh ordering | `4358aff88467170f56181d3008587e13ee597573` | Guard telemetry state refresh ordering |
| Guard acceptance ordering | `ea4c78f4fc2b5e06cb3b085e263ff04e7cd8ba54` | Advance applied generation only after guard acceptance |

For current behavior, trust the final tree and executable tests over any individual
intermediate commit.
