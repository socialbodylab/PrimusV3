# Packaging V3.6 Sender

The V3.6 sender can be packaged as a one-click macOS app or Windows executable because it is pure Python, serves its own static web UI, and has no runtime dependencies outside the Python standard library.

For the current Windows 11 build handoff, validation checklist, and known platform gaps, see [WINDOWS_BUILD.md](WINDOWS_BUILD.md).

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

## Host Network Settings

The Settings tab can select the sender interface used for Art-Net discovery/output and can apply a static IP or revert DHCP for macOS and Windows host network connections. Static/DHCP profiles are saved in the same `.primus_state.json` file as other sender state, under `sender_network`.

Applying host network changes runs `/usr/sbin/networksetup` through AppleScript's administrator prompt on macOS, and an elevated `netsh` command through the Windows UAC prompt on Windows. Primus Central does not store WiFi passwords, admin passwords, tokens, or other credentials. Packaged builds should keep this behavior visible to the user; no extra runtime Python dependencies are required.

## Build An App Or Executable

Build on the target OS. PyInstaller does not reliably cross-compile macOS apps from Windows or Windows executables from macOS.

Install the build-time packaging tools into your build environment:

```bash
python3 -m pip install -r V3_6/requirements-build.txt
```

On Windows, use the Python launcher if that is how Python is installed:

```powershell
py -m pip install -r V3_6\requirements-build.txt
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

Windows uses the same tracked source image and automatically converts it to `.ico`; `.icns` is macOS-only and should not be passed to PyInstaller for Windows builds. The generated Windows icon is written into the ignored build tree:

```text
V3_6\build\windows\icons\PrimusCentral.ico
```

The builder passes the generated `.ico` to PyInstaller by default:

```powershell
py V3_6\build_sender_app.py --target windows
```

The `.ico` includes common Windows icon sizes: 16, 24, 32, 48, 64, 128, and 256 px. Pillow is a build-only dependency for this conversion and is listed in `V3_6/requirements-build.txt`; do not add it as a sender runtime dependency. The builder asks Windows Explorer to refresh its icon cache after a successful build. If Explorer still shows an old/default icon for the same `.exe` path, test with a fresh output filename or clear the Windows Explorer icon cache before assuming PyInstaller failed. A custom icon can still be passed with `--icon`.

Build a Windows executable on Windows:

```powershell
py V3_6\build_sender_app.py --target windows
```

The unsigned Windows executable is written to:

```text
V3_6\dist\windows\PrimusCentral.exe
```

To sign the Windows executable with Azure Artifact Signing, provide a local
metadata JSON file and the Artifact Signing dlib path:

```powershell
py V3_6\build_sender_app.py --target windows `
	--windows-sign-metadata V3_6\build\windows\signing\metadata.json `
	--windows-sign-dlib "C:\Path\To\Azure.CodeSigning.Dlib.dll"
```

The build script signs after PyInstaller creates the `.exe`, verifies the
signature with SignTool, and then refreshes the Explorer icon cache. Signing
mutates the executable, so create release ZIPs and checksums only after signing.

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

## Sign Windows Builds With Azure Artifact Signing

Azure Artifact Signing provides Authenticode signatures without storing a private
key on the build machine. The local build uses SignTool plus Microsoft's
Artifact Signing dlib, and authenticates through Azure `DefaultAzureCredential`.
For local release work, the simplest credential path is Azure CLI login.

Install the required client tools on the Windows signing machine:

```powershell
winget install -e --id Microsoft.AzureCLI
winget install -e --id Microsoft.Azure.ArtifactSigningClientTools
winget install -e --id JRSoftware.InnoSetup
```

SignTool also needs Windows SDK build tools and .NET 8. The Artifact Signing
client tools installer includes the dlib dependency; SignTool is usually under a
Windows SDK path such as:

```text
C:\Program Files (x86)\Windows Kits\10\bin\<sdk-version>\x64\signtool.exe
```

Sign in to Azure with an account or service principal that has the **Artifact
Signing Certificate Profile Signer** role for the certificate profile:

```powershell
az login
az account set --subscription "<subscription name or id>"
```

Create a local metadata file under the ignored build tree, for example
`V3_6\build\windows\signing\metadata.json`:

```json
{
	"Endpoint": "https://eus.codesigning.azure.net",
	"CodeSigningAccountName": "<Artifact Signing account name>",
	"CertificateProfileName": "<Certificate profile name>",
	"CorrelationId": "PrimusCentral-0.7"
}
```

The endpoint must match the Azure region for the Artifact Signing account. A
region mismatch commonly appears as a 403 error during signing.

Build and sign the app:

```powershell
py V3_6\build_sender_app.py --target windows `
	--windows-sign-metadata V3_6\build\windows\signing\metadata.json `
	--windows-sign-dlib "C:\Path\To\Azure.CodeSigning.Dlib.dll"
```

To also build a simple installer, add `--windows-installer`. The builder uses
Inno Setup, installs PrimusCentral into a user-local app directory by default,
creates Start Menu shortcuts, and signs the installer after it is compiled when
Windows signing metadata is provided:

```powershell
py V3_6\build_sender_app.py --target windows --windows-installer `
	--windows-sign-metadata V3_6\build\windows\signing\metadata.json `
	--windows-sign-dlib "C:\Path\To\Azure.CodeSigning.Dlib.dll"
```

The default timestamp server is Microsoft's Artifact Signing timestamp service:

```text
http://timestamp.acs.microsoft.com
```

Timestamping is required because Artifact Signing certificates have short
validity windows; the timestamp preserves long-term Authenticode validity.

Equivalent environment variables for release machines:

```powershell
$env:PRIMUSV3_WINDOWS_SIGN_METADATA = "V3_6\build\windows\signing\metadata.json"
$env:PRIMUSV3_ARTIFACT_SIGNING_DLIB = "C:\Path\To\Azure.CodeSigning.Dlib.dll"
$env:PRIMUSV3_SIGNTOOL = "C:\Path\To\signtool.exe"
py V3_6\build_sender_app.py --target windows
```

Manual verification:

```powershell
& "C:\Path\To\signtool.exe" verify /pa /v V3_6\dist\windows\PrimusCentral.exe
& "C:\Path\To\signtool.exe" verify /pa /v V3_6\dist\windows\PrimusCentral-0.7-Windows-x64-Setup.exe
Get-AuthenticodeSignature V3_6\dist\windows\PrimusCentral.exe, V3_6\dist\windows\PrimusCentral-0.7-Windows-x64-Setup.exe | Format-List
```

After signing and verification pass, recreate the Windows ZIP, installer, and
`.sha256` release assets. Do not reuse a checksum generated before signing.

## Verify The App

1. Double-click `V3_6/dist/macos/PrimusCentral.app` or `V3_6\dist\windows\PrimusCentral.exe`.
2. Confirm the browser opens to the local sender UI.
3. On macOS, close the PrimusCentral browser window and confirm the app exits instead of leaving a blank browser process behind.
4. Confirm Art-Net discovery finds receiver nodes.
5. Connect a node and test Hello, Rename, and live preview.
6. Save a clip/look, quit, relaunch, and confirm data persists.

For macOS performance validation, launch through the app bundle with Finder or
LaunchServices. Do not use `Contents/MacOS/PrimusCentral` as the primary FPS
test path; it bypasses the app-bundle scheduling behavior that can affect live
output timing. For repeatable local testing with a known port, use:

```bash
open -n V3_6/dist/macos/PrimusCentral.app --args --port 8097
```

The packaged sender enables a `caffeinate` process assertion, user-interactive
QoS on the animation/render threads, and low-latency frame pacing so macOS app
launches maintain the target live-output FPS. Set
`PRIMUSV3_DISABLE_MACOS_ACTIVITY=1` only when intentionally disabling the
`caffeinate` assertion for diagnostics.

The v0.65 release is the baseline for this behavior. It fixed the case where
source `run.py` and direct binary execution reached about 30 FPS, but a real
`.app` launch through LaunchServices/Finder dropped to about 15-20 FPS. Keep
the LaunchServices test path in future release validation.

While validating timing, query the sender diagnostics endpoint:

```bash
curl -s http://127.0.0.1:8097/api/performance
```

Use steady-state deltas from `counters.animation_frames` for FPS; cumulative
`rates_per_second` includes startup, browser launch, restore, and reconnect time.

## Create A Release DMG

Create release DMGs from a clean staging directory. The staging directory must
contain only `PrimusCentral.app` and an `/Applications` symlink. Do not copy the
real `/Applications` folder into the DMG.

Example for version `0.65`:

```bash
rm -rf V3_6/build/macos/dmg-staging
mkdir -p V3_6/build/macos/dmg-staging
ditto V3_6/dist/macos/PrimusCentral.app V3_6/build/macos/dmg-staging/PrimusCentral.app
ln -s /Applications V3_6/build/macos/dmg-staging/Applications
rm -f V3_6/dist/macos/PrimusCentral-0.65-macOS-arm64.dmg \
	V3_6/dist/macos/PrimusCentral-0.65-macOS-arm64.dmg.sha256
hdiutil create -volname "PrimusCentral 0.65" \
	-srcfolder V3_6/build/macos/dmg-staging \
	-ov -format UDZO V3_6/dist/macos/PrimusCentral-0.65-macOS-arm64.dmg
```

Sign, notarize, staple, and verify the DMG itself:

```bash
codesign --force --timestamp \
	--sign "Developer ID Application: Nicholas Puckett (SAV2V7GXQ5)" \
	V3_6/dist/macos/PrimusCentral-0.65-macOS-arm64.dmg
xcrun notarytool submit V3_6/dist/macos/PrimusCentral-0.65-macOS-arm64.dmg \
	--keychain-profile "PrimusCentral Notary" --wait --timeout 1h
xcrun stapler staple V3_6/dist/macos/PrimusCentral-0.65-macOS-arm64.dmg
xcrun stapler validate V3_6/dist/macos/PrimusCentral-0.65-macOS-arm64.dmg
spctl -a -vvv --type open --context context:primary-signature \
	V3_6/dist/macos/PrimusCentral-0.65-macOS-arm64.dmg
hdiutil verify V3_6/dist/macos/PrimusCentral-0.65-macOS-arm64.dmg
```

Generate the checksum after the final stapling step, because stapling mutates
the DMG:

```bash
shasum -a 256 V3_6/dist/macos/PrimusCentral-0.65-macOS-arm64.dmg \
	> V3_6/dist/macos/PrimusCentral-0.65-macOS-arm64.dmg.sha256
```

GitHub release assets should be named:

```text
PrimusCentral-<version>-macOS-arm64.dmg
PrimusCentral-<version>-macOS-arm64.dmg.sha256
```

## Create Windows Release Assets

For GitHub distribution, offer a signed installer and a portable ZIP. The
installer is the easiest path for most Windows users because it creates normal
shortcuts and keeps the downloaded asset signed. The ZIP remains useful when a
user wants a portable folder or cannot run an installer. Avoid uploading the raw
`.exe`; direct executable downloads are more likely to be interrupted or warned
on by browsers and endpoint tools.

Recommended asset names for version `0.7`:

```text
PrimusCentral-0.7-Windows-x64-Setup.exe
PrimusCentral-0.7-Windows-x64-Setup.exe.sha256
PrimusCentral-0.7-Windows-x64.zip
PrimusCentral-0.7-Windows-x64.zip.sha256
```

Suggested ZIP contents:

```text
PrimusCentral.exe
README-Windows.txt
```

Build the signed executable and installer first:

```powershell
py V3_6\build_sender_app.py --target windows --windows-installer `
	--windows-sign-metadata V3_6\build\windows\signing\metadata.json `
	--windows-sign-dlib "C:\Path\To\Azure.CodeSigning.Dlib.dll"
```

Then stage and compress the release folder:

```powershell
Remove-Item V3_6\build\windows\release-staging -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force V3_6\build\windows\release-staging\PrimusCentral-0.7-Windows-x64 | Out-Null
Copy-Item V3_6\dist\windows\PrimusCentral.exe V3_6\build\windows\release-staging\PrimusCentral-0.7-Windows-x64\PrimusCentral.exe
Copy-Item V3_6\dist\windows\README-Windows.txt V3_6\build\windows\release-staging\PrimusCentral-0.7-Windows-x64\README-Windows.txt
Compress-Archive -Path V3_6\build\windows\release-staging\PrimusCentral-0.7-Windows-x64 -DestinationPath V3_6\dist\windows\PrimusCentral-0.7-Windows-x64.zip -Force
Get-FileHash V3_6\dist\windows\PrimusCentral-0.7-Windows-x64.zip -Algorithm SHA256 | ForEach-Object { "$($_.Hash)  PrimusCentral-0.7-Windows-x64.zip" } | Set-Content V3_6\dist\windows\PrimusCentral-0.7-Windows-x64.zip.sha256 -Encoding ASCII
Get-FileHash V3_6\dist\windows\PrimusCentral-0.7-Windows-x64-Setup.exe -Algorithm SHA256 | ForEach-Object { "$($_.Hash)  PrimusCentral-0.7-Windows-x64-Setup.exe" } | Set-Content V3_6\dist\windows\PrimusCentral-0.7-Windows-x64-Setup.exe.sha256 -Encoding ASCII
```

Windows does not have a notarization-and-stapling flow equivalent to macOS.
The comparable release hardening step is Authenticode signing with a trusted
code-signing certificate and timestamp. Unsigned Windows downloads may show
Microsoft Defender SmartScreen warnings until the publisher/app builds
reputation. EV code-signing certificates usually build SmartScreen reputation
faster than standard OV certificates, but both should still be tested from a
fresh download path.

For Windows workshop distribution, make the release notes explicit:

- Prefer the signed installer from the official GitHub release.
- Use the ZIP only when a portable folder is preferred; extract it before
	running the app.
- If SmartScreen appears, choose **More info** and **Run anyway** only after
	confirming the file came from the official release and the checksum matches.
- Allow Windows Defender Firewall for the private/show network when prompted;
	Art-Net discovery/output and receiver FPS telemetry use UDP traffic.
- Network Settings static IP and DHCP changes trigger a Windows UAC prompt.
	PrimusCentral does not store administrator credentials.

## Distribution Notes

Unsigned builds are suitable for local testing. Shared macOS releases should be Developer ID signed, notarized, and stapled. Windows distribution should be Authenticode signed when possible to reduce SmartScreen warnings and establish publisher identity.