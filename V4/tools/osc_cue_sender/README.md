# OSC Cue Sender

Small standalone utility for sending OSC cue triggers to PrimusCentral. Use it to test the Cue Controller external OSC integration without QLab or another show-control tool.

## Run from source

```bash
python3 V4/tools/osc_cue_sender/run.py
python3 V4/tools/osc_cue_sender/run.py --port 8105 --no-browser
```

The UI opens in your browser. Default OSC target is `127.0.0.1:53001` (PrimusCentral’s default listener port).

## Features

- **OSC target config** — type `192.168.1.50:53001` (or host + port fields); each GO/cue send uses the live address without saving first
- **Message style** — Primus addresses (`/primus/cue/...`) or QLab-style aliases (`/cue/.../start`)
- **Transport** — GO, STOP, BLACKOUT (optional fade)
- **Debug send** — type any OSC address and optional args (e.g. `/primus/cue/goto` with `1`) without creating a cue
- **Cue board** — square tiles matching the Primus Cue Controller look; click to fire
- **Cue sources** — manual add/edit, import `cues.json`, sync from PrimusCentral, or save/load named cue boards
- **Send log** — recent outbound OSC messages with target and status

## Test with PrimusCentral

OSC listening is **built into PrimusCentral** — you do not start a second Central server for OSC.

1. Run **one** PrimusCentral instance (packaged app or dev sender):

   ```bash
   # Packaged: open PrimusCentral.app from Applications
   # Dev:
   python3 V4/sender/run.py --product primus --no-browser --port 8080
   ```

2. In Cue Controller → External Control, confirm OSC is enabled. For **local** testing on one Mac, `127.0.0.1:53001` is fine. For **remote** machines on the LAN, set OSC host to `0.0.0.0` (or the machine's LAN IP) so UDP from another computer is accepted.

3. Optional — start **OSC Cue Sender** (separate test UI on HTTP 8105; sends OSC *to* PrimusCentral, not a second sender):

   ```bash
   python3 V4/tools/osc_cue_sender/run.py
   ```

4. Set **Target address** to the remote Central's LAN IP, e.g. `192.168.1.50:53001`, then fire cues. Use **Save Target** only if you want that address restored on next launch.

5. Sync cues from the Central HTTP URL (e.g. `http://192.168.1.50:8080` for a remote machine, or `http://127.0.0.1:8080` locally), fire cues, and verify them in PrimusCentral's OSC message history.

For QLab or other show-control apps on the same Mac, point OSC output at `127.0.0.1:53001` while PrimusCentral is running.

## App data

Packaged runs and `OSC_CUE_SENDER_USE_APP_DATA=1` store settings under:

- macOS: `~/Library/Application Support/PrimusV3/V4/tools/osc_cue_sender/`
- Windows: `%APPDATA%\PrimusV3\V4\tools\osc_cue_sender\`

Override with `OSC_CUE_SENDER_DATA_DIR`.

## Package

Install build tools once:

```bash
python3 -m pip install -r V4/requirements-build.txt
```

Build:

```bash
# macOS .app
python3 V4/tools/build_app.py --target macos

# Windows .exe
python3 V4/tools/build_app.py --target windows

# Unsigned console build (debug)
python3 V4/tools/build_app.py --console --onedir
```

Output: `V4/tools/dist/macos/OscCueSender.app` or `V4/tools/dist/windows/OscCueSender.exe`

Optional macOS signing:

```bash
python3 V4/tools/build_app.py --target macos \
  --sign-identity "Developer ID Application: …"
```

## Tests

```bash
python3 -m unittest discover -s V4/tools/osc_cue_sender/tests
python3 -m py_compile V4/tools/osc_cue_sender/*.py
```
