# Packaging V3.6 Sender

The V3.6 sender can be packaged as a one-click macOS app or Windows executable because it is pure Python, serves its own static web UI, and has no runtime dependencies outside the Python standard library.

## Runtime Paths

Source checkouts keep using `V3_6/sender/` for clips, looks, cues, and `.primus_state.json`.

Packaged apps use a writable app data directory instead.

macOS:

```text
~/Library/Application Support/PrimusV3/V3_6/sender/
```

Windows:

```text
%APPDATA%\PrimusV3\V3_6\sender\
```

The app copies bundled starter clips, looks, and `cues.json` there on first run. Existing user data is not overwritten on later launches or app updates.

Firmware tool downloads are kept outside the app bundle in a managed tools directory.

macOS:

```text
~/Library/Application Support/PrimusV3/V3_6/tools/
```

Windows:

```text
%APPDATA%\PrimusV3\V3_6\tools\
```

The Firmware panel can install Arduino CLI, ESP32 board support, and receiver firmware libraries into this directory on demand. The main app bundle includes the receiver firmware source and upload script, but not downloaded Arduino cores or caches. Arduino CLI config for this managed setup is stored at `tools/arduino-cli.yaml`.

For local testing, set `PRIMUSV3_DATA_DIR` to force a specific writable data directory:

```bash
PRIMUSV3_DATA_DIR=/tmp/primus-data python3 V3_6/sender/run.py --no-browser
```

Set `PRIMUSV3_USE_APP_DATA=1` to use the platform app data directory while running from source.

Set `PRIMUSV3_TOOLS_DIR` to force a specific firmware tools directory while testing the installer.

## macOS Network Settings

The Settings tab can select the sender interface used for Art-Net discovery/output and can apply a static IP or revert DHCP for a macOS network service. Static/DHCP profiles are saved in the same `.primus_state.json` file as other sender state, under `sender_network`.

Applying host network changes runs `/usr/sbin/networksetup` through AppleScript's administrator prompt. Primus Central does not store WiFi passwords, admin passwords, tokens, or other credentials. Packaged macOS builds should keep this behavior visible to the user; no extra runtime Python dependencies are required.

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
python3 V3_6/build_sender_app.py
```

Build a macOS app explicitly:

```bash
python3 V3_6/build_sender_app.py --target macos
```

The unsigned macOS app bundle is written to:

```text
V3_6/dist/macos/PrimusCentral.app
```

macOS builds generate the app icon from:

```text
V3_6/assets/appIcon.png
```

The generated `.icns` file is written under `V3_6/build/macos/icons/` and passed to PyInstaller automatically.

Windows will need the same source image converted to `.ico`; `.icns` is macOS-only and should not be passed to PyInstaller for Windows builds. When Windows packaging is implemented/tested, keep using `V3_6/assets/appIcon.png` as the tracked source and generate the Windows icon into the ignored build tree, for example:

```text
V3_6\build\windows\icons\PrimusCentral.ico
```

Then pass it to PyInstaller with:

```powershell
--icon V3_6\build\windows\icons\PrimusCentral.ico
```

The `.ico` should include common Windows icon sizes: 16, 24, 32, 48, 64, 128, and 256 px. This conversion can use a build-only tool such as ImageMagick (`magick`) or Pillow; do not add either as a sender runtime dependency. If the Windows icon does not appear immediately after rebuilding, test with a fresh output filename or clear the Windows Explorer icon cache before assuming PyInstaller failed.

Build a Windows executable on Windows:

```powershell
py V3_6\build_sender_app.py --target windows
```

The unsigned Windows executable is written to:

```text
V3_6\dist\windows\PrimusCentral.exe
```

The older macOS-only wrapper still works:

```bash
python3 V3_6/build_macos_app.py
```

For a console build that keeps stdout/stderr visible while testing:

```bash
python3 V3_6/build_sender_app.py --console
```

Windows defaults to a one-file `.exe`. Use `--onedir` if you prefer a folder-based build while debugging.

## Sign And Notarize macOS Builds

Direct GitHub distribution uses a Developer ID Application certificate, not a Mac App Store certificate. The current bundle identifier is:

```text
com.socialbodylab.PrimusCentral
```

The visible app name remains `PrimusCentral.app`; build-to-build tracking belongs in release notes and checksums, not in the app bundle name.

One-time local setup:

```bash
xcrun notarytool store-credentials "PrimusCentral Notary" \
	--apple-id "dev@puckettrand.com" \
	--team-id "SAV2V7GXQ5"
```

When prompted, paste the app-specific password generated at `appleid.apple.com`. Do not store Apple passwords, private keys, `.p12` files, certificate signing requests, or notarization credentials in the repository.

Build, sign, notarize, staple, and verify the macOS app:

```bash
python3 V3_6/build_sender_app.py \
	--target macos \
	--sign-identity "Developer ID Application: Nicholas Puckett (SAV2V7GXQ5)" \
	--notary-profile "PrimusCentral Notary"
```

If Apple notarization is slow, add an explicit wait timeout. Apple continues processing after the local command times out, and the submission can be checked later with `xcrun notarytool history` or `xcrun notarytool info`.

```bash
python3 V3_6/build_sender_app.py \
	--target macos \
	--sign-identity "Developer ID Application: Nicholas Puckett (SAV2V7GXQ5)" \
	--notary-profile "PrimusCentral Notary" \
	--notary-timeout 1h
```

After a timed-out submission is accepted, staple and verify the existing app without rebuilding:

```bash
python3 V3_6/build_sender_app.py --target macos --staple-existing
```

The same values can be supplied through environment variables:

```bash
PRIMUSV3_CODESIGN_IDENTITY="Developer ID Application: Nicholas Puckett (SAV2V7GXQ5)" \
PRIMUSV3_NOTARY_PROFILE="PrimusCentral Notary" \
python3 V3_6/build_sender_app.py --target macos
```

The build script passes the bundle identifier to PyInstaller, then signs the finished app with hardened runtime and timestamp, submits a notary zip with `notarytool`, staples the accepted ticket, validates the staple, and runs Gatekeeper verification with `spctl` when available.

Manual verification commands:

```bash
codesign --verify --deep --strict --verbose=2 V3_6/dist/macos/PrimusCentral.app
xcrun stapler validate V3_6/dist/macos/PrimusCentral.app
spctl -a -vvv --type exec V3_6/dist/macos/PrimusCentral.app
```

## Verify The App

1. Double-click `V3_6/dist/macos/PrimusCentral.app` or `V3_6\dist\windows\PrimusCentral.exe`.
2. Confirm the browser opens to the local sender UI.
3. On macOS, close the PrimusCentral browser window and confirm the app exits instead of leaving a blank browser process behind.
4. Confirm Art-Net discovery finds receiver nodes.
5. Connect a node and test Hello, Rename, and live preview.
6. Save a clip/look, quit, relaunch, and confirm data persists.

## Distribution Notes

Unsigned builds are suitable for local testing. Shared macOS releases should be Developer ID signed, notarized, and stapled. Windows distribution may require code signing to reduce SmartScreen warnings.