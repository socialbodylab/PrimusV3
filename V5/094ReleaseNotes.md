# PrimusCentral and DeviceManager v0.94

Source release notes for the V4 flexible receiver setup layer.

## Changes

- **Complete management-v2 setup** — PrimusCentral and DeviceManager can refresh
  authoritative config, edit custom strip/grid descriptors, configure explicit
  PST targets, and manage production lock/recovery.
- **Recoverable physical slots** — A0 and A1 stay visible when Off and can return
  to a built-in, custom descriptor, or reusable preset without reflashing.
- **Output presets** — built-ins plus create/update/rename/delete user presets,
  per-output application, and group application with per-device results.
- **Telemetry diagnostics** — target, PST version, health/age, sequence/loss/
  reorder/reboot, and V1/V2/V3 battery semantics are visible in both setup apps.
- **Safety preserved** — DeviceManager monitor-only and Mobile View behavior are
  unchanged; Radius cards never receive Primus management controls.
- **Reliability coverage** — static UI contracts and deterministic multi-device
  PST + ArtDmx + config-query soak coverage guard lock latency, target stability,
  and reordered-heartbeat reboot detection.

## Compatibility

Legacy built-in output controls remain available. Custom descriptors, explicit
telemetry targets, authoritative readback, and production lock require firmware
that advertises Primus management. Existing descriptor NVS formats migrate to
the atomic management schema; output preset files remain sender-side until
applied.

Multi-sender ownership/arbitration is not part of management v1 and remains
deferred. Use one commissioning authority and production lock.
