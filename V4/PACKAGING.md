# V4 Packaging

V4 packages the **unified sender tree** into two macOS/Windows apps from the same codebase:

| App | Build flag | Bundle ID |
|-----|------------|-----------|
| **RadiusCentral** | `--product radius` (default) | `com.socialbodylab.RadiusCentral` |
| **PrimusCentral** | `--product primus` | `com.socialbodylab.PrimusCentral` |

Both bundle `V4/Arduino/` (Primus + Radius firmware) and the static web UI. PrimusCentral additionally bundles starter `clips/`, `looks/`, and `cues.json`.

## Runtime paths

Source checkouts use `V4/sender/` for writable state and content.

Packaged apps use product-specific app data:

| Product | macOS | Windows |
|---------|-------|---------|
| **Radius** | `~/Library/Application Support/RadiusV3/V4/sender/` | `%APPDATA%\RadiusV3\V4\sender\` |
| **Primus** | `~/Library/Application Support/PrimusV3/V4/sender/` | `%APPDATA%\PrimusV3\V4\sender\` |

Firmware tools install on demand to the matching product root under `…/V4/tools/`.

Overrides: `RADIUSV4_DATA_DIR`, `PRIMUSV3_DATA_DIR`, `RADIUSV4_USE_APP_DATA`, `PRIMUSV3_USE_APP_DATA`, `RADIUSV4_TOOLS_DIR`, `PRIMUSV3_TOOLS_DIR`.

Set product at runtime with `PRIMUSV3_SENDER_PRODUCT=primus|radius` (packaged apps set this from the executable name).

## Build RadiusCentral

```bash
python3 -m pip install -r V4/requirements-build.txt
python3 V4/build_sender_app.py --target macos --product radius --name RadiusCentral
```

Output: `V4/dist/macos/RadiusCentral.app`

## Build PrimusCentral

```bash
python3 V4/build_sender_app.py --target macos --product primus --name PrimusCentral
```

Output: `V4/dist/macos/PrimusCentral.app`

## Signing (optional)

```bash
python3 V4/build_sender_app.py \
  --target macos \
  --product primus \
  --name PrimusCentral \
  --sign-identity "Developer ID Application: …" \
  --notary-profile "PrimusCentral Notary"
```

Environment overrides: `PRIMUSV3_CODESIGN_IDENTITY`, `PRIMUSV3_NOTARY_PROFILE`.

## Legacy V3_6 PrimusCentral

`V3_6/build_sender_app.py` still produces the prior release-line app for comparison. **New PrimusCentral builds should use V4** with `--product primus`.

## Bundled assets

PyInstaller `_data_files()` includes:

- `V4/Arduino/` — `primusV3_receiver/`, `radius_receiver/`, upload scripts
- `V4/sender/web/` — static UI (`index.html` + `index-primus.html`)
- **Primus only:** `clips/`, `looks/`, `cues.json`

## Validation

```bash
python3 -m unittest discover -s V4/sender/tests
python3 -m py_compile V4/sender/*.py
./V4/Arduino/upload.sh --board v3 --compile
./V4/Arduino/radius_upload.sh --board radius_v1 --compile
```

Source smoke tests:

```bash
python3 V4/sender/run.py --product primus --no-browser --port 8090
python3 V4/sender/run.py --product radius --no-browser --port 8098
```

For packaged macOS FPS validation of PrimusCentral, launch through Finder/LaunchServices — see root `CLAUDE.md` v0.65 notes.
