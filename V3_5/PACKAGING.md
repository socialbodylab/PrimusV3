# Packaging V3.5 Sender

The V3.5 sender can be packaged as a one-click macOS app or Windows executable because it is pure Python, serves its own static web UI, and has no runtime dependencies outside the Python standard library.

## Runtime Paths

Source checkouts keep using `V3_5/sender/` for clips, looks, cues, and `.primus_state.json`.

Packaged apps use a writable app data directory instead.

macOS:

```text
~/Library/Application Support/PrimusV3/V3_5/sender/
```

Windows:

```text
%APPDATA%\PrimusV3\V3_5\sender\
```

The app copies bundled starter clips, looks, and `cues.json` there on first run. Existing user data is not overwritten on later launches or app updates.

For local testing, set `PRIMUSV3_DATA_DIR` to force a specific writable data directory:

```bash
PRIMUSV3_DATA_DIR=/tmp/primus-data python3 V3_5/sender/run.py --no-browser
```

Set `PRIMUSV3_USE_APP_DATA=1` to use the platform app data directory while running from source.

## Build An App Or Executable

Build on the target OS. PyInstaller does not reliably cross-compile macOS apps from Windows or Windows executables from macOS.

Install PyInstaller into your build environment:

```bash
python3 -m pip install pyinstaller
```

On Windows, use the Python launcher if that is how Python is installed:

```powershell
py -m pip install pyinstaller
```

Build for the current OS:

```bash
python3 V3_5/build_sender_app.py
```

Build a macOS app explicitly:

```bash
python3 V3_5/build_sender_app.py --target macos
```

The unsigned macOS app bundle is written to:

```text
V3_5/dist/macos/PrimusV3.5 Sender.app
```

Build a Windows executable on Windows:

```powershell
py V3_5\build_sender_app.py --target windows
```

The unsigned Windows executable is written to:

```text
V3_5\dist\windows\PrimusV3.5 Sender.exe
```

The older macOS-only wrapper still works:

```bash
python3 V3_5/build_macos_app.py
```

For a console build that keeps stdout/stderr visible while testing:

```bash
python3 V3_5/build_sender_app.py --console
```

Windows defaults to a one-file `.exe`. Use `--onedir` if you prefer a folder-based build while debugging.

## Verify The App

1. Double-click `V3_5/dist/macos/PrimusV3.5 Sender.app` or `V3_5\dist\windows\PrimusV3.5 Sender.exe`.
2. Confirm the browser opens to the local sender UI.
3. Confirm Art-Net discovery finds receiver nodes.
4. Connect a node and test Hello, Rename, and live preview.
5. Save a clip/look, quit, relaunch, and confirm data persists.

## Distribution Notes

The first build is suitable for local testing. Sharing with other Macs will likely require code signing, and wider macOS distribution may require notarization. Windows distribution may require code signing to reduce SmartScreen warnings.