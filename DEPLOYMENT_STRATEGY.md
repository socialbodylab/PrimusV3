# PrimusV2 Deployment Strategy

Guidelines for packaging and distributing the PrimusV2 LED controller to non-technical users.

---

## Current Architecture

The sender (`led_controller.py`) is a single-file Python 3 program with **zero external dependencies** (stdlib only). It provides:

- UDP sockets for Art-Net (send/receive)
- A basic HTTP server for the web UI
- An embedded HTML/JS control interface
- ArtPoll discovery
- FPS telemetry listener

Total: ~1000 lines. The web UI auto-opens in the user's default browser.

---

## Deployment Options

### 1. PyInstaller — Recommended Short Term

Bundle the Python script into a standalone executable. No Python installation required for end users.

| | Detail |
|---|---|
| **Output** | `.app` (macOS), `.exe` (Windows) |
| **Install size** | ~30 MB |
| **Cross-platform** | Build per platform (macOS, Windows, Linux) |
| **User experience** | Double-click → browser opens → done |
| **Dev effort** | Low — same Python code, add one build script |
| **Rebuild needed** | Yes, when code changes |

**Build command:**
```bash
pip install pyinstaller
pyinstaller --onefile --windowed --name "PrimusV2 Controller" led_controller.py
```

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

---

### 2. Go Rewrite — Recommended Long Term

Rewrite the server in Go for production-grade distribution.

| | Detail |
|---|---|
| **Output** | Single static binary |
| **Install size** | ~8 MB |
| **Cross-platform** | Cross-compile trivially (`GOOS=windows go build`) |
| **User experience** | Double-click → browser opens → done |
| **Dev effort** | Medium — rewrite ~1000 lines |
| **Rebuild needed** | Yes, but cross-compilation from one machine |

**Why Go fits this project:**
- Go's stdlib has everything needed: `net` (UDP/Art-Net), `net/http` (web server), `encoding/binary` (packet parsing)
- Produces a single static binary — no runtime, no dependencies, no installer
- Cross-compilation is a single env var: `GOOS=windows GOARCH=amd64 go build`
- Small binaries (~8 MB vs ~30 MB PyInstaller)
- Many professional Art-Net/lighting tools are written in Go for exactly these reasons
- Concurrency model (goroutines) maps cleanly to the current threading architecture

**Migration path:**
1. Keep Python version for development and testing
2. Port the Art-Net sender/receiver logic first (most mechanical)
3. Port the HTTP server and embed the HTML as a Go `embed.FS`
4. Port effects engine last (most creative code)
5. Validate against the same ESP32 hardware

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

**Verdict: Overkill for this project.** 150 MB to wrap a web UI already served via HTTP is hard to justify. The browser _is_ the UI — that's a feature, not a limitation.

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

The Arduino firmware is self-contained on the hardware. For end-user flashing without `arduino-cli`:

1. **Pre-build `.bin` files** using the existing `upload.sh --compile` workflow
2. **Distribute via [ESP Web Flasher](https://esp.huhn.me/)** — a browser-based tool that flashes ESP32s over USB with zero installs
3. Users: plug in USB → open web page → click Flash → done

This eliminates the Arduino CLI dependency entirely for end users.

---

## Recommended Roadmap

| Phase | Action | When |
|---|---|---|
| **Now** | Continue developing in Python | Current |
| **Next** | Add PyInstaller build script, produce Mac + Windows binaries | When ready to share with first users |
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
