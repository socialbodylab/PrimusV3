# Remote Backend Readiness Notes (2026-08-12 audit)

Future goal: the unified backend runs on a dedicated machine on the show
network; PrimusCentral / RadiusCentral / DeviceManager become pure network
clients. Not being built yet — this document records what is already in
place, what is one flag away, and what genuinely needs design, so interim
work doesn't dig the hole deeper.

## Already solved (don't break these)

- **Frontends are 100% origin-relative.** Every `fetch` goes through
  `api(method, path)` with a bare path; no `http://127.0.0.1` literals in any
  app JS. Exports are relative URLs. Keep it that way — no `API_BASE`
  constants, no config-injected hosts. If an absolute URL is ever needed,
  derive it from `window.location`.
- **The UI is served by the backend**, so there is no CORS surface. Adding
  CORS headers would mean the origin split — don't.
- **The discovery probe is HTTP** (`probe_central_server(host, port)` →
  `GET /api/runtime`) and takes a host; `try_attach_before_start`,
  `reserve_ui_session`, `stop_running_central` all thread `host=` through.
  The plumbing exists; only the callers default to loopback.
- **Art-Net / telemetry / OSC already bind all interfaces** — the show-network
  side never assumed loopback. `get_artnet_interface()` correctly reads the
  *backend's* NICs.
- **Serial monitor already streams over HTTP** (`/api/serial/status`),
  uploads/downloads are byte streams, all app data is server-side via
  `paths.py`.
- **UI heartbeats are origin-relative POSTs** with per-window session ids —
  multi-client already works.
- **`POST /api/server/stop` + `--server-status`/`--stop-server`** are the
  network-capable control primitives (prefer these over `--replace`, which is
  local ps-name matching and cannot reach a remote backend).
- `caffeinate` / QoS / dialogs are platform-guarded (`PRIMUSV3_NO_DIALOGS`,
  darwin checks); a Linux backend degrades cleanly except the network
  settings panel (reports `supported: false`).

## Shallow (a flag/config away when the time comes)

- Default bind is loopback purely via the `--lan` default in `run_primus.py`.
  No env var for bind host yet (a service unit would pass argv).
- Launcher call sites never pass `host=` — exercise the existing parameters
  instead of adding new defaults.
- Headless mismatch handling: `launcher_dialog` degrades to print+default;
  make sure new dialog defaults are safe without a human.
- Packaged apps are `--windowed`; a service deployment runs from source or a
  `--console` build under supervision.

## Structural (needs design before the move)

1. **Server discovery by remote clients.** The registry is a local file
   (`central_server.json`) validated by local `os.kill(pid, 0)` — meaningless
   across machines. Remote attach needs a host source: static host config
   (cheapest), registry-over-HTTP, or mDNS/Bonjour (`_primus-central._tcp`,
   zero-config but real work — stdlib-only rules out `zeroconf`). Liveness
   must become "did `/api/runtime` answer", never PID checks.
2. **UI lifecycle / desktop coupling.** Auto-quit ("all windows closed ⇒
   quit") is right for a laptop app, catastrophic for a shared backend — a
   network backend runs as a supervised service with
   `ui_lifecycle_enabled=False` as a stated intent, not a `--no-browser` side
   effect. `UiFocusServer` (AF_UNIX) and `/api/ui/focus` (raises a window on
   the *server's* desktop) are same-machine by construction: freeze them as
   legacy, never build new signalling on them.
3. **Polling cost.** Rates were tuned for loopback: `/api/state` at 100 ms
   (Primus) / 500 ms (Radius) / 1 s (Devices), preview frames at 66 ms,
   plus `Connection: close` per request (HTTP/1.0, no keep-alive). Multiply
   by N remote clients. Direction when it matters: keep-alive first, then
   event-shaped updates (SSE/WebSocket) instead of more `setInterval`s.
4. **USB firmware flashing locality.** `arduino-cli` runs server-side and
   enumerates the *backend's* serial ports. Right model for OTA; inverted for
   USB flashing on a rack (operator holds the board at the laptop, rack holds
   the port). Decide before more firmware UI hardens around server-side port
   lists: local flash agent vs walk-to-the-rack vs OTA-only in production.
5. **Security posture.** The stated no-auth stance is explicitly conditioned
   on the isolated-laptop model; a permanently LAN-bound backend exposes
   firmware flash, FTP, network reconfig, and server stop to the whole LAN.
   Cheap, sane levers short of real auth: bind to the management NIC's IP
   (not 0.0.0.0), and/or a shared-secret token seeded into the served HTML
   and checked in one place — possibly only on destructive routes
   (firmware, network config, server stop). Decide this in the same change
   that flips the default bind, not after.
6. **Host network reconfiguration** (`/api/network/*` static-IP apply)
   escalates via interactive GUI prompts (osascript / UAC) — impossible
   headless. A rack backend pre-configures its NICs at the OS level; the
   panel stays a laptop feature.

## Standing rules for interim work

- Never add another `127.0.0.1` literal — take addresses from
  `server.server_address`, a `host=` parameter, or the registry.
- New launcher↔server signalling goes over HTTP, never the focus socket.
- Don't make auto-quit smarter; don't extend registry PID logic.
- Anything new that updates the UI should be throttled or event-shaped, not
  another fast `setInterval`.
- Don't widen the `--lan` promise in docs without deciding the hardening
  story in the same change.
