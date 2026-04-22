# PrimusV3 Deployment Strategy

Guidelines for packaging and distributing the PrimusV3 LED controller to non-technical users.

---

## Current Architecture

The V3.1 sender (`V3_1/sender/`) is a modular Python 3 application with **zero external dependencies** (stdlib only). It consists of:

- `run.py` — Entry point. Starts all subsystems.
- `state.py` — Core state, animation loop, device tracking.
- `server.py` — HTTP server (port 8080) serving static web UI and 27 JSON API endpoints.
- `effects.py` — 10 built-in effects engine.
- `clips.py` — Clip CRUD and preview computation.
- `mixer.py` — Look Mixer crossfade logic.
- `controller.py` — Cue Controller for sequential playback.
- `artnet.py` — Art-Net protocol (ArtPoll, ArtDmx, ArtAddress, ArtOutputConfig).
- `web/` — Static Alpine.js SPA (HTML, JS, CSS — no build step).
- `clips/` — 114 preset clip JSON files.
- `looks/` — Saved look JSON files.
- `cues.json` — Cue list.

Total: ~2500 lines of Python across 8 modules, plus the web UI. The web UI auto-opens in the user's default browser.

The original V3.0 sender (`sender/led_controller.py`) is a single-file (~1800 lines) archived version that is still functional.

---

## Deployment Options

### 1. PyInstaller — Recommended Short Term

Bundle the Python application into a standalone executable. No Python installation required for end users.

| | Detail |
|---|---|
| **Output** | `.app` (macOS), `.exe` (Windows) |
| **Install size** | ~30 MB |
| **Cross-platform** | Build per platform (macOS, Windows, Linux) |
| **User experience** | Double-click → browser opens → done |
| **Dev effort** | Low — same Python code, add one build script |
| **Rebuild needed** | Yes, when code changes |

**Build command (V3.1):**
```bash
pip install pyinstaller
pyinstaller --onefile --windowed \
  --name "PrimusV3 Controller" \
  --add-data "V3_1/sender/web:web" \
  --add-data "V3_1/sender/clips:clips" \
  --add-data "V3_1/sender/looks:looks" \
  --add-data "V3_1/sender/cues.json:. " \
  V3_1/sender/run.py
```

Note: V3.1's modular structure requires bundling the `web/`, `clips/`, and `looks/` data directories alongside the Python modules. The `--add-data` flags handle this. `server.py` must resolve its static file paths relative to the bundled data (PyInstaller sets `sys._MEIPASS` at runtime).

**Distribution:** Attach platform binaries to GitHub Releases or provide a download link.

**Pros:**
- Minimal changes to existing code
- Users never see a terminal or know Python is involved
- `webbrowser.open()` already handles launching the UI
- Quick path to distributable builds

**Cons:**
- Must build separately for each OS
- Binary is ~30 MB (bundles Python interpreter)
- macOS may require code signing / notarization for Gatekeeper
- Needs rebuild on every code change
- V3.1 requires bundling data directories (web UI, clips, looks) — slightly more complex than the old single-file build

---

### 2. Go Rewrite — Recommended Long Term

Rewrite the server in Go for production-grade distribution.

| | Detail |
|---|---|
| **Output** | Single static binary |
| **Install size** | ~8 MB |
| **Cross-platform** | Cross-compile trivially (`GOOS=windows go build`) |
| **User experience** | Double-click → browser opens → done |
| **Dev effort** | Medium — rewrite ~2500 lines of Python + web UI |
| **Rebuild needed** | Yes, but cross-compilation from one machine |

**Why Go fits this project:**
- Go's stdlib has everything needed: `net` (UDP/Art-Net), `net/http` (web server), `encoding/binary` (packet parsing)
- Produces a single static binary — no runtime, no dependencies, no installer
- Cross-compilation is a single env var: `GOOS=windows GOARCH=amd64 go build`
- Small binaries (~8 MB vs ~30 MB PyInstaller)
- Many professional Art-Net/lighting tools are written in Go for exactly these reasons
- Concurrency model (goroutines) maps cleanly to V3.1's threaded architecture (animation loop, Art-Net listener, HTTP server)
- `embed.FS` natively embeds static files — perfect for bundling the Alpine.js web UI, preset clips, and default looks into a single binary

**Migration path:**
1. Keep Python V3.1 for development and testing
2. Port the Art-Net module (`artnet.py`) first (most mechanical)
3. Port state management and device tracking (`state.py`)
4. Port the HTTP server (`server.py`) and embed the web UI via Go `embed.FS`
5. Port effects engine (`effects.py`) last (most creative code)
6. Port clip/look/cue data model (`clips.py`, `mixer.py`, `controller.py`)
7. Validate against the same ESP32 hardware

---

### 3. Electron — Desktop App Wrapper

Wrap the web UI in a native desktop application shell.

| | Detail |
|---|---|
| **Output** | `.app` / `.exe` with native window |
| **Install size** | ~150 MB |
| **Cross-platform** | Mac + Windows + Linux |
| **User experience** | Native app feel, tray icon, menu bar |
| **Dev effort** | Medium — rewrite server in Node.js or spawn Python as subprocess |

**Verdict: Overkill for this project.** 150 MB to wrap a web UI already served via HTTP is hard to justify. V3.1 already serves a full Alpine.js SPA over HTTP — the browser _is_ the UI, and that's a feature, not a limitation.

---

### 4. Node.js + pkg

Rewrite in Node.js and bundle with `pkg` or `nexe`.

| | Detail |
|---|---|
| **Output** | Single executable |
| **Install size** | ~40 MB |
| **Cross-platform** | Mac + Windows + Linux |
| **Dev effort** | Medium — rewrite in JavaScript |

**Verdict: Viable** but no clear advantage over PyInstaller (short term) or Go (long term). Larger binary than Go, more runtime overhead.

---

### 5. Rust Rewrite

| | Detail |
|---|---|
| **Output** | Single static binary |
| **Install size** | ~4 MB |
| **Cross-platform** | Cross-compile with cargo |
| **Dev effort** | Higher — steeper learning curve |

**Verdict: Best binary size** but the development overhead isn't justified for this scale of project.

---

## ESP32 Firmware Distribution

There are two firmware variants to distribute:

| Variant | Path | Use Case |
|---------|------|----------|
| `primusV3_receiver` | `V3_1/Arduino/` | LED-only nodes (V3.0 / V3.1) |
| `primusV3_audio_receiver` | `V3_2/Arduino/` | LED + audio nodes (V3.2) |

The audio receiver also has a compile-time board switch (`AUDIO_BOARD` in `config.h`), so two `.bin` files are needed for V3.2: one for Music Maker FeatherWing and one for Audio BFF.

For end-user flashing without `arduino-cli`:

1. **Pre-build `.bin` files** using the existing `upload.sh --compile` workflow for each variant
2. **Distribute via [ESP Web Flasher](https://esp.huhn.me/)** — a browser-based tool that flashes ESP32s over USB with zero installs
3. Users: plug in USB → open web page → select the correct `.bin` → click Flash → done

This eliminates the Arduino CLI dependency entirely for end users.

---

## Recommended Roadmap

| Phase | Action | When |
|---|---|---|
| **Now** | Continue developing V3.1 in Python (modular sender) | Current |
| **Next** | Add PyInstaller build script for V3.1, produce Mac + Windows binaries | When ready to share with first users |
| **Later** | Port to Go for production distribution | When project stabilizes and user base grows |
| **ESP32** | Pre-build firmware `.bin` files, document ESP Web Flasher workflow | Alongside first user distribution |

---

## macOS-Specific Notes

- **Gatekeeper:** Unsigned apps trigger "unidentified developer" warnings. Users must right-click → Open on first launch, or you can sign with an Apple Developer ID ($99/year).
- **Notarization:** Required for distribution outside the App Store on recent macOS. `xcrun notarytool submit` after signing.
- **Firewall:** macOS may prompt to allow incoming network connections on first launch. The user must click "Allow" for Art-Net discovery (UDP broadcast) to work.

## Windows-Specific Notes

- **Windows Defender SmartScreen:** Unsigned `.exe` files trigger a warning. Users click "More info" → "Run anyway." An EV code signing certificate eliminates this (~$200–400/year).
- **Firewall:** Windows Firewall will prompt to allow network access on first launch. User must allow for both private and public networks.
- **Antivirus:** PyInstaller executables sometimes trigger false positives. Code signing helps; so does submitting to Microsoft for analysis.
