# V5 Unified Backend Architecture

V5 is the **canonical track** for PrimusV3 sender development. The goal is one Python backend that serves multiple product frontends (Primus LED, Radius audio) with shared device management, networking, firmware tooling, and packaging.

## Current state (June 2026)

| Layer | Status |
|-------|--------|
| **Firmware source** | Both families under `V5/Arduino/` |
| **Firmware UI + jobs** | Product-scoped profiles per app |
| **Radius backend** | `radius_state.py`, audio cues, netlog, push sync |
| **Radius frontend** | `index.html` + `app-radius.js` |
| **Primus backend** | `state.py`, clips, looks, mixer, OSC, ArtDmx loop |
| **Primus frontend** | `index-primus.html` + `app-primus.js`, look-mixer/controller |
| **Packaged apps** | Both built from V5 via `--product primus|radius` |

## Directory layout

```
V5/
  sender/                 Unified sender (Primus + Radius product split)
  Arduino/
    primusV3_receiver/    Primus LED firmware (v1, v2, v3 profiles)
    upload.sh             Primus compile/upload script
    radius_receiver/      Radius audio firmware (radius_v1)
    upload.sh      Radius compile/upload script
  build_sender_app.py     PyInstaller packaging (--product primus|radius)
  ARCHITECTURE.md         This file
  FIRMWARE_DEVELOPMENT.md Firmware protocol notes (both families)
  PACKAGING.md            App bundle and release workflow
```

Historical copies under `V4/Arduino/` and `V3_6/Arduino/` remain for reference, but **new firmware work should land in `V5/Arduino/`**.

## Firmware families

| Family | Profiles | Sketch | Upload script | Capability tag |
|--------|----------|--------|---------------|----------------|
| **Primus** | `v1`, `v2`, `v3` | `primusV3_receiver/` | `upload.sh` | `PV3CAP1\|…` |
| **Radius** | `radius_v1` | `radius_receiver/` | `upload.sh` | `PVRAD1\|…` |

The sender resolves the correct script from `firmware.FIRMWARE_PROFILES` (`V5/sender/firmware.py`). Each packaged app exposes **only its product's profiles** — RadiusCentral serves `radius_v1` only; PrimusCentral serves `v1`/`v2`/`v3` only. Override for dev with `PRIMUSV3_SENDER_PRODUCT=primus|radius` or `python3 run.py --product …`.

## Product split (implemented)

One **HTTP server** (`server.py`) exposes the full Primus + Radius JSON API. Static UI is served from separate HTML entry points:

| URL | Frontend |
|-----|----------|
| `/primus` | Look Designer + Cue Controller (`index-primus.html`) |
| `/radius` | Audio production UI (`index.html`) |
| `/devices` | Mixed monitoring and Primus setup (`index-devices.html`) |
| `/` | Redirects to the default frontend for the active product (`PRIMUSV3_SENDER_PRODUCT` or app bundle name) |

Packaged apps open their default path (`/primus` or `/radius`) on launch. Both frontends are always available on the same server process when running from source.

| Concern | Primus backend | Radius backend |
|---------|----------------|----------------|
| Entry | `run_primus.py` via `run.py --product primus` | `run_radius.py` (default) |
| State | `state.py` → `ControllerState`, ArtDmx loop | `radius_state.py` → `RadiusState` |
| UI path | `/primus` | `/radius` |
| App data | `PrimusV3/V5/sender/` + clips/looks/cues | `RadiusV3/V5/sender/` + audio |

Product-specific routes return `503` when that backend is not running (e.g. clip APIs on a Radius-only launch).

## Future unification (optional)

1. **Single device state** — one device list with `device_class` routing (LED → ArtDmx, Radius → audio/FTP)
2. **Merged web UI** — Primus + Radius tabs in one `index.html`; workshop profile from V3_6
3. **Shared run loop** — one process with both telemetry listeners where needed

## Frontend model

Frontends are **static Alpine.js SPAs** served from `V5/sender/web/`. No build step. Mode tabs select panels; shared sidebar handles discovery/connect/rename/IP for all device types.

```
┌─────────────────────────────────────────┐
│  Navbar: product-specific mode tabs     │
├──────────┬──────────────────────────────┤
│ Sidebar  │  Active panel (Alpine x-data) │
│ devices  │  → HTTP JSON API            │
└──────────┴──────────────────────────────┘
                    │
                    ▼
            V5/sender/server.py  (unified API + static frontends)
                    │
        ┌───────────┴───────────┐
        ▼                       ▼
  ControllerState          RadiusState
  (Primus runtime)         (Radius runtime)
  ArtDmx / clips           audio / FTP / cues
        │                       │
        └───────────┬───────────┘
                    ▼
              V5/sender/artnet.py
```

## Primus management-v2 setup path

`device-conn.js` is the additive shared setup layer used by DeviceManager and
PrimusCentral. It owns descriptor validation/order summaries, output preset
CRUD/application, explicit telemetry targeting, production/recovery actions,
and consistent `409`/NACK/readback-pending presentation. It gates all of those
actions on a non-Radius `management_supported` record.

The backend remains authoritative:

```text
UI draft → HTTP management route → 0x8140 mutation → 0x8141 ACK/NACK
                                               ↘ GET_CONFIG readback
                                                  ↘ /api/state
```

Off A0/A1 slots remain in `/api/state` and in both UIs. Grid metadata maps
logical coordinates onto physical wire order; sender ArtDmx remains physical
wire order. Output presets live in sender app data and only reach receiver NVS
when explicitly applied.

DeviceManager's `monitor_only` invariant is unchanged: periodic sync never
connects devices for output, and one-off setup packets do not create standing
DMX. Mobile mode hides setup while retaining its existing Hello action. Radius
records stay in the mixed monitor but never enter the Primus management path.

PST has one explicit persisted target. The sender/UI never learns it from
ArtDmx or EOS, which prevents traffic from another console from silently
redirecting monitoring. Production lock is the commissioning boundary, not a
multi-sender ownership mechanism. Management-v1 arbitration/leases are
deliberately deferred to a future protocol version.

## Environment variables

| Variable | Purpose |
|----------|---------|
| `RADIUSV5_DATA_DIR` | Writable sender data (V5 default; `RADIUSV4_DATA_DIR` remains a compatibility alias) |
| `RADIUSV5_USE_APP_DATA` | Use platform app data from source runs (`RADIUSV4_USE_APP_DATA` remains accepted) |
| `RADIUSV5_TOOLS_DIR` | Firmware tools directory override (`RADIUSV4_TOOLS_DIR` remains accepted) |
| `PRIMUSV3_DATA_DIR` | Writable Primus sender data (alias of legacy env) |
| `PRIMUSV3_SENDER_PRODUCT` | `primus` or `radius` — selects backend, UI, and firmware profiles |
| `PRIMUSV3_USE_APP_DATA` | Use platform app data from source runs (Primus) |

## Related docs

- [README.md](README.md) — quick start and UI modes
- [FIRMWARE_DEVELOPMENT.md](FIRMWARE_DEVELOPMENT.md) — opcode tables and hardware notes
- [PACKAGING.md](PACKAGING.md) — PyInstaller, signing, DMG
- [RADIUS_CENTRAL_BRANCH_FEATURES.md](RADIUS_CENTRAL_BRANCH_FEATURES.md) — branch parity inventory
