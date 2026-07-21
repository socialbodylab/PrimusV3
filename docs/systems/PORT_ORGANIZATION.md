# Port organization — Primus & Radius (V5)

**Status:** Implemented on branch `port-organization` (V5 firmware + sender). Dual-listen (`PORT_DUAL_LISTEN=1`) remains enabled for one release so Setup opcodes still work on Show during migration.  
**Scope:** V5 Primus + Radius cohabitation.  
**Related:** [API_CONTROLS.md](API_CONTROLS.md) · [SYSTEMS_OUTLINE.md](SYSTEMS_OUTLINE.md) · site study [site/explore-01-lan.html](site/explore-01-lan.html)

### Migration note

- Existing receivers that only listen on `:6454` keep working while dual-listen is on: senders fall back Setup → Show when `MGMT:` is absent from discovery.
- New Primus firmware binds Show `:6454` + Setup `:6457` and advertises `|SHOW:|MGMT:|TELE:|`. New Radius binds discovery `:6454`, audio Show `:6456`, Setup `:6457`, and advertises `|AUD:|MGMT:|TELE:|FTP:|`.
- **Recovery:** discover on `:6454` → open Setup on advertised/default `:6457` → `SET_LANE_PORTS` / ArtLanePorts `0x8220` (or boot-window unlock) to restore defaults.
- Sender network defaults live under Settings → UDP Lanes; per-device overrides via DeviceManager expanded card / `GET|POST /api/device_lane_ports`.

---

## 1. Goal

Cleaner **lane separation** on the show LAN:

| Lane | Job | Must not |
|------|-----|----------|
| **Show** | Drive media on the costume (pixels / audio cues) | Be blocked by Setup or Watch |
| **Setup** | Commission, name, IP, geometry, locks, FTP gate | Own the cue at GO |
| **Watch** | Telemetry into DeviceManager / Centrals | Fire cues or open standing ArtDmx |

Separate **UDP ports per lane** (defaults below) improve firewall rules, socket isolation, and operator mental model. They do **not** create extra WiFi bandwidth — one radio still shares airtime.

---

## 2. Default port map

These are **defaults**. Every lane port is **overridable** (see §4).

| Lane | Port | Protocol | Primus | Radius | Notes |
|------|------|----------|:------:|:------:|-------|
| **Show (Primus)** | UDP **6454** | Art-Net: ArtDmx, ArtPoll / ArtPollReply | ✓ | discovery only* | Eos-compatible. Keep as show + discovery home. |
| **Show (Radius)** | UDP **6456** | ArtAudioCmd `0x8300` | — | ✓ | Live cue / transport commands only (target). |
| **Watch** | UDP **6455** | PST / PTR / PFP (and legacy PBT) | ✓ | ✓ | Shared telemetry plane. Outbound from receivers. |
| **Setup** | UDP **6457** | Management / naming / commission | ✓ | ✓ | **New default.** Device commands, show-info, production enter, etc. |
| **Content (Radius)** | TCP **21** | FTP data plane | — | ✓ | Opened after ArtFtpCmd gate; not a UDP lane. |
| **Operator facades** | TCP (HTTP) | JSON API on Centrals / DM | ✓ | ✓ | Unchanged; not Art-Net. |
| **Optional cues** | OSC (configurable) | Into PrimusCentral / RadiusCentral | ✓ | ✓ | App-local; not a receiver listen port. |

\*Radius may still answer ArtPoll on 6454 for discovery/capability visibility; it must **not** accept ArtDmx.

### Explicit non-goals

- Do **not** assign a unique UDP port per opcode (rename vs IP vs geometry, etc.). Override at **lane** granularity only.
- Do **not** move Primus live color off 6454 as the default — stock Eos / Art-Net consoles expect 6454.
- Do **not** expect port splits alone to fix FPS or WiFi saturation.

### FTP gate placement

Today ArtFtpCmd (`0x8301`) shares Radius Art-Net UDP with ArtAudioCmd. Target shape:

- **Prefer:** ArtFtpCmd on **Setup :6457** (or Radius show port only as transitional), data plane remains TCP 21.
- **Show :6456** should be live audio commands in the steady state.

Transitional dual-accept (FtpCmd on 6456 **or** 6457) is acceptable during migration.

---

## 3. Current → target

| Traffic | Current (typical) | Target default |
|---------|-------------------|----------------|
| Primus ArtDmx + discovery | :6454 | :6454 (unchanged) |
| Primus management `0x8140`, rename, IP, show-info, output config, … | :6454 (same socket) | **:6457** Setup |
| Telemetry PST/PTR/PFP | :6455 | :6455 (unchanged) |
| Radius ArtAudioCmd | :6456 | :6456 (unchanged) |
| Radius ArtFtpCmd | :6456 | **:6457** Setup (migrate) |
| Radius identity / IP (legacy Art-Net style) | often :6454/:6456 family | **:6457** Setup (align with Primus) |

---

## 4. Defaults, but changeable

### 4.1 Principles

1. **Device owns listen ports** — stored in NVS; survive reboot. Sender does not guess.
2. **Discovery advertises ports** — capability string and/or management `GET_CONFIG` must publish the active map.
3. **Sender stores a profile** — show/network defaults + per-device overrides when a node reports non-defaults.
4. **Paired updates** — changing Watch port updates receiver `teleTarget` **and** sender listen bind together.
5. **Bootstrap fallback** — ArtPoll / discovery remains reachable on the **well-known default show/discovery port (6454)** even if Setup moves, so a misconfigured mgmt port is recoverable.
6. **Lane-level overrides only** — not per-opcode ports.

### 4.2 Suggested config fields

**On receiver (NVS)** — illustrative names:

| Field | Default | Lane |
|-------|---------|------|
| `portShow` | 6454 (Primus) / 6456 (Radius audio) | Show |
| `portSetup` | 6457 | Setup |
| `portWatch` | 6455 | Watch (destination port when sending telemetry) |
| `ftpPort` | 21 | Content (Radius) |

Primus `portShow` default 6454; Radius live-audio listen default 6456. A device only binds the ports its product needs.

**On sender**

| Field | Role |
|-------|------|
| Network/show defaults | Same four defaults for new sessions |
| Per-device override map | Filled from discovery/GET_CONFIG |
| Telemetry listen port | Must match devices’ Watch destination |

### 4.3 Advertisement

Extend capability / Node Report (64-byte pressure still applies — keep tokens short), e.g.:

```text
...|SHOW:6454|MGMT:6457|TELE:6455
...|AUD:6456|MGMT:6457|TELE:6455|FTP:21
```

Management `GET_CONFIG` should return the same map as structured fields for DeviceManager.

### 4.4 Validation rules

- Reject port `0`; reject privileged ports below 1024 except FTP 21 if you allow that exception explicitly.
- Reject assigning two lanes to the same UDP port unless demux-on-shared is an explicit supported mode (default: **forbid**).
- UI warning: Primus `portShow ≠ 6454` ⇒ “custom Art-Net — stock Eos will not hit this node.”
- Production lock (Primus): changing ports is a **Setup** write → **LOCKED** in production; unlock/boot-window / physical recovery required (same as other commission writes).

### 4.5 Recovery

- Boot-window or production unlock can **reset ports to factory defaults**.
- Document a recovery path: discover on 6454 → open Setup on advertised/default 6457 → fix ports.
- Never silently fall back on the sender to defaults when the device advertised different ports (causes lab/stage split-brain).

---

## 5. Trade-offs (do not re-litigate casually)

| Benefit | Cost |
|---------|------|
| Clear Show / Setup / Watch firewall story | More sockets on ESP32 (`WiFiUDP` bind + poll) |
| Setup bursts off ArtDmx/ArtAudio receive queues | Dual-port migration period; docs + UI |
| Shared Setup port language across Primus + Radius | Must advertise ports or devices become unfindable |
| Telemetry already isolated (:6455) | Ports ≠ bandwidth; WiFi design still dominates FPS |

**Better levers for “bandwidth” than more ports:** quieter Setup at GO, production lock, ArtDmx rate, `sdBusy` (Radius), AP channel plan, optional DSCP/WMM later.

---

## 6. Implementation checklist (V5 thread)

Use this as the work breakdown in a new implementation thread. Order is suggestive.

### 6.1 Preconditions

- [ ] Merge V5 (`npuckett-create-v5-tree` / management-v2) into `main` so Primus head and this work share one tree.
- [ ] Confirm Radius track (`radius-central` lineage) port assumptions (:6456 audio, :6455 tele) on the branch you implement against.

### 6.2 Firmware

- [ ] Primus: bind Show `:6454` + Setup `:6457` + Watch send `:6455` (defaults); NVS overrides.
- [ ] Primus: move management / naming / commission opcodes from the Show socket to the Setup socket (accept transitional dual-listen during migrate).
- [ ] Radius: keep Show `:6456`; add Setup `:6457`; migrate ArtFtpCmd + identity/IP writes toward Setup.
- [ ] Both: advertise `SHOW`/`AUD`/`MGMT`/`TELE`/`FTP` in caps and GET_CONFIG.
- [ ] Both: factory/boot-window reset of ports to defaults.
- [ ] Tests: wrong Setup port does not affect ArtDmx/ArtAudio; production lock blocks port changes.

### 6.3 Sender (PrimusCentral / DeviceManager / RadiusCentral)

- [ ] Network settings: editable lane defaults.
- [ ] Discovery parser: read advertised ports into device records.
- [ ] Art-Net send paths: Show vs Setup sockets (or one socket bound to destination port per send).
- [ ] Telemetry listener: bind Watch port from profile; per-device destination port when sending teleTarget.
- [ ] HTTP API: get/set device ports; document 409 on production lock / monitor_only rules as applicable.
- [ ] UI: lane port fields + Eos warning when Primus show ≠ 6454.

### 6.4 Docs / compatibility

- [ ] Update [API_CONTROLS.md](API_CONTROLS.md) wire columns for :6457 Setup.
- [ ] Update SYSTEMS_OUTLINE / site explore data to match.
- [ ] Migration note for existing shows still managing on :6454 only.
- [ ] Packaged app: default profile numbers; persisted overrides in app data.

### 6.5 Non-goals for the first PR

- Per-opcode ports  
- Moving default Primus ArtDmx off 6454  
- QoS/DSCP implementation  
- Reworking HTTP listen ports  

---

## 7. Decision summary (for the implementer)

1. **Three UDP lanes:** Show, Setup (`6457` default), Watch (`6455`) — plus Radius content on TCP 21.  
2. **Primus Show stays 6454** by default for Eos.  
3. **Radius Show stays 6456** by default.  
4. **Setup is shared conceptually** across products on **6457**.  
5. **All lane ports are overridable** via NVS + advertisement + sender profile, with discovery fallback on 6454 and production-lock / boot-window recovery.  
6. **Implement on V5 after merge to main** — this document is the reference; do not bury the design only in chat.

---

## 8. Open points (resolve in implementation thread if needed)

- Exact capability token spelling under 64-byte Node Report pressure.  
- Whether ArtPollReply remains **only** on 6454 while Setup is 6457-only for writes.  
- How long dual-listen (mgmt on 6454 **and** 6457) lasts before deprecation.  
- Whether Radius ArtFtpCmd moves in the same PR as Primus Setup split or a follow-up.

When starting the implementation thread, paste or link:

> Implement [docs/systems/PORT_ORGANIZATION.md](PORT_ORGANIZATION.md) on V5/`main` — defaults + NVS overrides + advertisement + sender profile.
