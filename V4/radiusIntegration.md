# Overview

**Status: implemented in V4.** See [RADIUS_INTEGRATION.md](RADIUS_INTEGRATION.md) for the shipped architecture, API, UI, and validation guide.

This file retains the original integration goals for reference.

## Devices

There are two distinct types of devices that work on the same network: Primus and Radius. V4 DeviceManager now monitors both from a single `primus`-product backend.

## Phase 1 — New editable, saved data

Radius firmware (`V4/Arduino/radius_receiver/`) now uses `PVRAD1` identity, ArtShowInfo `0x8210`, and the same character/performer/device-name/IP patterns as PrimusCentral. Radius devices do not expose receive mode, universe, output types, or virtual resolution.

## Phase 2 — Interface updates

- **DeviceManager:** Primus and Radius sections, simplified Radius cards, split character filters, per-device product labeling.
- **RadiusCentral:** sidebar identity block (character/performer editing).

## Phase 3 — Mixed firmware upload

DeviceManager Firmware tab toggles Primus vs Radius, then board version (V1/V2/V3 or V1/V2), via `scope=mixed` on `/api/firmware/*`.

## Future work

- Adaptive polling / battery telemetry for Radius monitor cards.
