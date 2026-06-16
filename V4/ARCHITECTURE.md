# V4 Unified Backend Architecture

V4 is the **canonical track** for PrimusV3 sender development. The goal is one Python backend that serves multiple product frontends (Primus LED, Radius audio) with shared device management, networking, firmware tooling, and packaging.

## Current state (June 2026)

| Layer | Status |
|-------|--------|
| **Firmware source** | Both families under `V4/Arduino/` |
| **Firmware UI + jobs** | Product-scoped profiles per app |
| **Radius backend** | `radius_state.py`, audio cues, netlog, push sync |
| **Radius frontend** | `index.html` + `app-radius.js` |
| **Primus backend** | `state.py`, clips, looks, mixer, OSC, ArtDmx loop |
| **Primus frontend** | `index-primus.html` + `app-primus.js`, look-mixer/controller |
| **Packaged apps** | Both built from V4 via `--product primus|radius` |

## Directory layout

```
V4/
  sender/                 Unified sender (Primus + Radius product split)
  Arduino/
    primusV3_receiver/    Primus LED firmware (v1, v2, v3 profiles)
    upload.sh             Primus compile/upload script
    radius_receiver/      Radius audio firmware (radius_v1)
    radius_upload.sh      Radius compile/upload script
  build_sender_app.py     PyInstaller packaging (--product primus|radius)
  ARCHITECTURE.md         This file
  FIRMWARE_DEVELOPMENT.md Firmware protocol notes (both families)
  PACKAGING.md            App bundle and release workflow
```

Historical copies under `V3_6/Arduino/` remain for the current PrimusCentral release line but **new firmware work should land in `V4/Arduino/`**.

## Firmware families

| Family | Profiles | Sketch | Upload script | Capability tag |
|--------|----------|--------|---------------|----------------|
| **Primus** | `v1`, `v2`, `v3` | `primusV3_receiver/` | `upload.sh` | `PV3CAP1\|…` |
| **Radius** | `radius_v1` | `radius_receiver/` | `radius_upload.sh` | `PVRAD1\|…` |

The sender resolves the correct script from `firmware.FIRMWARE_PROFILES` (`V4/sender/firmware.py`). Each packaged app exposes **only its product's profiles** — RadiusCentral serves `radius_v1` only; PrimusCentral serves `v1`/`v2`/`v3` only. Override for dev with `PRIMUSV3_SENDER_PRODUCT=primus|radius` or `python3 run.py --product …`.

## Product split (implemented)

| Concern | Primus | Radius |
|---------|--------|--------|
| Entry | `run_primus.py` via `run.py --product primus` | `run_radius.py` (default) |
| State | `state.py` → `ControllerState`, ArtDmx loop | `radius_state.py` → `RadiusState` |
| HTTP | `server_primus.py` (clips, looks, mixer, cues, OSC) | `server_radius.py` (audio, cue map, netlog) |
| UI | `index-primus.html`, `app-primus.js` | `index.html`, `app-radius.js` |
| App data | `PrimusV3/V4/sender/` + clips/looks/cues | `RadiusV3/V4/sender/` + audio |

`server.py` is a thin facade that delegates to the product-specific handler module.

## Future unification (optional)

1. **Single device state** — one device list with `device_class` routing (LED → ArtDmx, Radius → audio/FTP)
2. **Merged web UI** — Primus + Radius tabs in one `index.html`; workshop profile from V3_6
3. **Shared run loop** — one process with both telemetry listeners where needed

## Frontend model

Frontends are **static Alpine.js SPAs** served from `V4/sender/web/`. No build step. Mode tabs select panels; shared sidebar handles discovery/connect/rename/IP for all device types.

```
┌─────────────────────────────────────────┐
│  Navbar: product-specific mode tabs     │
├──────────┬──────────────────────────────┤
│ Sidebar  │  Active panel (Alpine x-data) │
│ devices  │  → HTTP JSON API            │
└──────────┴──────────────────────────────┘
                    │
                    ▼
            V4/sender/server.py  (facade)
                    │
        ┌───────────┴───────────┐
        ▼                       ▼
  server_primus.py       server_radius.py
  state.py               radius_state.py
  ArtDmx / clips         audio / FTP / cues
        │                       │
        └───────────┬───────────┘
                    ▼
              V4/sender/artnet.py
```

## Environment variables

| Variable | Purpose |
|----------|---------|
| `RADIUSV4_DATA_DIR` | Writable sender data (V4 default) |
| `RADIUSV4_USE_APP_DATA` | Use platform app data from source runs |
| `RADIUSV4_TOOLS_DIR` | Firmware tools directory override |
| `PRIMUSV3_DATA_DIR` | Writable Primus sender data (alias of legacy env) |
| `PRIMUSV3_SENDER_PRODUCT` | `primus` or `radius` — selects backend, UI, and firmware profiles |
| `PRIMUSV3_USE_APP_DATA` | Use platform app data from source runs (Primus) |

## Related docs

- [README.md](README.md) — quick start and UI modes
- [FIRMWARE_DEVELOPMENT.md](FIRMWARE_DEVELOPMENT.md) — opcode tables and hardware notes
- [PACKAGING.md](PACKAGING.md) — PyInstaller, signing, DMG
- [RADIUS_CENTRAL_BRANCH_FEATURES.md](RADIUS_CENTRAL_BRANCH_FEATURES.md) — branch parity inventory
