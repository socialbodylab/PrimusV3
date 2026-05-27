# Windows Build Handoff For PrimusCentral 0.7

This document captures the current macOS build knowledge and the Windows 11 context needed to build PrimusCentral 0.7 from the same V3.6 source tree.

The goal is one codebase:

- macOS builds produce `PrimusCentral.app`.
- Windows builds produce `PrimusCentral.exe`.
- Sender, receiver firmware, protocol tables, saved data format, and workshop UI profile remain shared.
- Platform differences stay behind small platform checks in the existing build/runtime modules.

Build on the target operating system. PyInstaller does not reliably cross-compile a macOS app from Windows or a Windows executable from macOS.

## Current macOS Build Snapshot

The current macOS release path is implemented in [build_sender_app.py](build_sender_app.py) and documented in [PACKAGING.md](PACKAGING.md).

The macOS build command for the current release process is:

```bash
python3 V3_6/build_sender_app.py \
  --target macos \
  --sign-identity "Developer ID Application: Nicholas Puckett (SAV2V7GXQ5)" \
  --notary-profile "PrimusCentral Notary" \
  --notary-timeout 1h
```

The build creates:

```text
V3_6/dist/macos/PrimusCentral.app
```

The builder bundles these source resources into the PyInstaller output:

```text
V3_6/Arduino/
V3_6/sender/web/
V3_6/sender/clips/
V3_6/sender/looks/
V3_6/sender/cues.json
```

macOS-specific build behavior:

- `V3_6/assets/appIcon.png` is converted to an `.icns` file under `V3_6/build/macos/icons/`.
- The bundle identifier is `com.socialbodylab.PrimusCentral`.
- Release builds are Developer ID signed with hardened runtime and timestamp.
- Notarization uses `xcrun notarytool` and the `PrimusCentral Notary` keychain profile.
- The accepted ticket is stapled to the `.app`.
- Gatekeeper verification runs with `spctl` when available.

The release DMG process is intentionally separate from the app build:

1. Recreate `V3_6/build/macos/dmg-staging` from scratch.
2. Copy only `PrimusCentral.app` into staging.
3. Add `Applications` as a symlink to `/Applications`.
4. Create `PrimusCentral-<version>-macOS-arm64.dmg` with `hdiutil create -format UDZO`.
5. Sign, notarize, staple, and verify the DMG.
6. Generate the `.sha256` file after stapling, because stapling mutates the DMG.

The v0.65 macOS release is the packaged performance baseline. It fixed a case where source `run.py` and direct binary execution reached about 30 FPS, but a real `.app` launch through Finder or LaunchServices dropped to about 15-20 FPS. Future macOS validation must launch the app as an app bundle:

```bash
open -n V3_6/dist/macos/PrimusCentral.app --args --port 8097
curl -s http://127.0.0.1:8097/api/performance
```

Do not use this as the primary packaged FPS test path:

```text
V3_6/dist/macos/PrimusCentral.app/Contents/MacOS/PrimusCentral
```

That direct binary path bypasses the app-bundle scheduling behavior that previously caused the packaged FPS regression.

## Windows Build Goal

The Windows 0.7 pass should start with a local standalone executable built from the same source tree. The expected command on Windows 11 is:

```powershell
py V3_6\build_sender_app.py --target windows
```

The current default Windows artifact is a one-file executable:

```text
V3_6\dist\windows\PrimusCentral.exe
```

Useful build variants while debugging:

```powershell
py V3_6\build_sender_app.py --target windows --console
py V3_6\build_sender_app.py --target windows --onedir
```

`--console` keeps stdout and stderr visible in the terminal. `--onedir` creates a folder-based PyInstaller output, which can make missing bundled files easier to inspect.

The first Windows build should verify behavior before adding installer, signing, or platform optimizations. Keep a written note of the exact Windows version, Python version, PyInstaller version, hardware, receiver firmware profile, and network setup used for the first successful baseline.

## What Already Works Cross-Platform

The sender is a good Windows candidate because the runtime is pure Python standard library and the web UI is static HTML/CSS/JavaScript. There is no npm build step and no external Python runtime dependency for the app itself.

Already shared between macOS and Windows:

- HTTP sender UI served locally from `V3_6/sender/web/`.
- JSON API served by `V3_6/sender/server.py`.
- Default HTTP binding to `127.0.0.1`, with port 8080 falling back to an auto-selected port if busy.
- Art-Net UDP output and discovery on port 6454.
- Receiver FPS telemetry listener on UDP port 6455.
- OSC cue listener, default UDP port 53001, when enabled.
- Clip, Look, Cue, Controller, Mixer, sharing bundle, and import/export behavior.
- Sender-side Clip, Look, and segment brightness scaling.
- Workshop UI profile for 0.7: UI-only output filtering and names, with full output tables preserved in sender state, API, and firmware.
- Browser launch logic for Chrome, Edge, Brave, Chromium, and fallback default browser.
- Packaged app-data paths and managed firmware-tool paths in `V3_6/sender/paths.py`.

Writable packaged data locations:

```text
macOS:   ~/Library/Application Support/PrimusV3/V3_6/sender/
Windows: %APPDATA%\PrimusV3\V3_6\sender\
```

Managed firmware tool locations:

```text
macOS:   ~/Library/Application Support/PrimusV3/V3_6/tools/
Windows: %APPDATA%\PrimusV3\V3_6\tools\
```

Useful path environment overrides work on both platforms:

| Variable | Purpose |
| --- | --- |
| `PRIMUSV3_DATA_DIR` | Force sender data into a specific writable directory. |
| `PRIMUSV3_USE_APP_DATA=1` | Use platform app data while running from source. |
| `PRIMUSV3_TOOLS_DIR` | Force the managed firmware tools directory. |
| `PRIMUS_BROWSER` | Force a specific browser executable for UI launch. |

## Windows 11 Permissions And Security

Windows permissions are different from macOS notarization and AppleScript prompts. Expect the first build to require local validation of firewall, SmartScreen, adapter settings, and USB/serial behavior.

### Windows Firewall

PrimusCentral uses local HTTP for the browser UI and UDP for receiver/network traffic.

| Function | Protocol | Port | Direction |
| --- | --- | --- | --- |
| Local browser UI | TCP HTTP | 8080 or auto-selected | Browser to sender on `127.0.0.1` |
| Art-Net discovery/output/control | UDP | 6454 | Sender to receiver, bidirectional discovery |
| Receiver FPS telemetry | UDP | 6455 | Receiver to sender |
| OSC cue input | UDP | 53001 default | Show-control tool to sender |

The localhost HTTP UI should not require a firewall exception because it binds to `127.0.0.1`. Art-Net, FPS telemetry, and OSC may trigger Windows Defender Firewall prompts, especially in a packaged `.exe`.

For initial testing, allow PrimusCentral on the network profile used for the show router. If discovery works but receiver FPS does not appear, check UDP 6455 inbound. If OSC is used, check UDP 53001 inbound.

For public Windows distribution, consider an installer-managed firewall rule instead of asking users to diagnose prompts manually. A standalone unsigned `.exe` is acceptable for local 0.7 validation, but not ideal for workshops or public release.

### SmartScreen And Signing

The current Windows build path does not sign the `.exe`. Unsigned Windows executables commonly show Microsoft Defender SmartScreen warnings, especially before reputation builds up.

Future release options:

- Authenticode signing with `signtool.exe` and a standard or EV code-signing certificate.
- An installer format that signs both installer and executable.
- Documented local-only distribution with explicit SmartScreen instructions for internal testing.

Do not store private keys, `.pfx` files, certificate passwords, or signing credentials in the repository.

### UAC And Host Network Changes

Windows static IP and DHCP changes require administrator rights. The current sender does not implement Windows host adapter changes.

For the first Windows build, configure the PC network adapter manually in Windows Settings or Control Panel, then use PrimusCentral only for receiver discovery, receiver IP config, output config, rename, hello, clips, looks, and cues.

Windows host network controls are implemented through PowerShell status probes and elevated `netsh interface ipv4` commands. Static IP and DHCP changes should trigger a Windows UAC prompt. The app should not run entirely as Administrator; only the host network change command should elevate.

Avoid making the whole app run as Administrator unless there is a clear reason. A full elevated app changes file ownership, firewall behavior, and browser launch assumptions.

### USB And Serial Access

Firmware uploads need the ESP32 board to appear as a Windows COM port. Depending on the board and cable, the Windows machine may need USB serial drivers before Arduino CLI sees the port.

Start firmware validation with list-ports only. Do not attempt batch upload until COM port detection is reliable.

## Network Interface And IP Configuration

Receiver control over Art-Net and host network switching are intended to work on Windows.

Current implementation status:

- `V3_6/sender/artnet.py` uses standard UDP sockets and can send Art-Net frames on Windows.
- `V3_6/sender/state.py` can bind Art-Net senders to a selected source IP when one is provided.
- `V3_6/sender/network_settings.py` supports macOS and Windows host interface discovery, preferred Art-Net source routing, static IP apply, and DHCP revert.
- On Windows, interface status comes from PowerShell NetTCPIP commands plus `netsh wlan`; static IP and DHCP changes run through an elevated Windows prompt and `netsh`.
- On platforms other than macOS and Windows, `get_network_status()` reports unsupported.

Practical Windows 11 validation flow:

1. Connect the Windows machine to the show router or Ethernet adapter used for receiver traffic.
2. Use Settings to select the desired sender connection for Art-Net.
3. Confirm the PC and receivers are on the same IPv4 subnet.
4. Launch PrimusCentral.
5. Allow Windows Firewall prompts for the show network.
6. Use the PrimusCentral device discovery/connect flow.
7. If discovery fails, try manual add by receiver IP before changing sender code.
8. If manual add works but discovery does not, suspect broadcast/firewall/interface selection.

Recommended future Windows hardening shape:

- Keep the public API used by `server.py` stable.
- Keep Windows-specific helpers narrow inside `network_settings.py` or a small platform helper module.
- Preserve the current persisted `sender_network` state format where possible.
- Do not fork the sender UI or create a separate Windows-only sender.

## Speed, Latency, And Timing Validation

The sender target frame rate is 30 FPS by default. Timing-sensitive code lives mainly in `V3_6/sender/state.py` and `V3_6/sender/run.py`.

Current macOS timing protections:

- `run.py` starts `caffeinate -dimsu -w <pid>` for packaged macOS launches unless `PRIMUSV3_DISABLE_MACOS_ACTIVITY=1` is set.
- `state.py` raises animation and mixer/controller threads to user-interactive QoS on Darwin unless `PRIMUSV3_DISABLE_THREAD_QOS=1` is set.
- `state.py` uses chunked low-latency frame sleep with a short spin tail before the deadline.
- `/api/performance` reports timing samples and counters for validation.

Current Windows timing status:

- There is no Windows `timeBeginPeriod(1)` timer-resolution boost.
- There is no Windows `SetThreadPriority` or process-priority tuning.
- There is no Windows equivalent of the macOS `caffeinate` process assertion.
- The same hybrid Python sleep/spin frame pacer still runs, but Windows timer wake latency may differ.

First Windows timing baseline:

1. Launch the source app or packaged `.exe`.
2. Connect one receiver.
3. Run a simple 30 FPS animation or live preview.
4. Query performance twice several seconds apart:

```powershell
curl http://127.0.0.1:8080/api/performance
```

If the app selected another port, use the URL printed by `run.py` or the browser address bar.

Track these metrics:

| Metric | Meaning | First-pass expectation |
| --- | --- | --- |
| `counters.animation_frames` | Total rendered frames. Use deltas for real FPS. | About 28-30 FPS steady-state at 30 FPS target. |
| `counters.animation_frame_overruns` | Frames that missed their target deadline. | Ideally zero; rare overruns are acceptable. |
| `samples.animation_sleep_latency_ms` | How late the app woke from frame sleep. | Likely higher on Windows than macOS. Record the baseline. |
| `samples.tick_total_ms` | Total sender tick work. | Should stay comfortably below a 33 ms frame budget at 30 FPS. |
| Receiver FPS telemetry | Receiver-reported FPS and packet rate. | Should roughly match sender FPS. |

Use steady-state counter deltas instead of cumulative `rates_per_second`, because cumulative rates include startup, browser launch, reconnect, and restore time.

If Windows cannot sustain 30 FPS, investigate in this order:

1. Receiver/network health and firewall behavior.
2. CPU load from browser or antivirus scanning the one-file PyInstaller extraction.
3. One-file versus `--onedir` package behavior.
4. Windows timer resolution via `timeBeginPeriod(1)` guarded behind Windows-only code.
5. Windows thread/process priority through `ctypes`, guarded behind Windows-only code and validated with `/api/performance`.

Do not add timing optimizations without measuring before and after on a packaged Windows build.

## Firmware Build And Upload On Windows

Arduino CLI itself is cross-platform, and `V3_6/sender/paths.py` already expects `arduino-cli.exe` on Windows. Managed tools should live under:

```text
%APPDATA%\PrimusV3\V3_6\tools\
```

The current firmware job manager still constructs compile/upload commands as:

```text
bash <path-to-upload.sh> --board <profile> ...
```

That means the Windows firmware panel currently depends on a usable `bash` plus the existing `V3_6/Arduino/upload.sh` script. This may work with Git Bash or an MSYS-style environment, but it should be treated as unvalidated until tested on the Windows laptop.

Firmware validation order on Windows:

1. Install or confirm Python and PyInstaller for the sender build.
2. Install Git Bash only if firmware panel validation is in scope for the first Windows pass.
3. Launch PrimusCentral.
4. Open the Firmware panel.
5. Run Firmware Tools setup.
6. Test list-ports with one ESP32 connected.
7. Confirm Arduino CLI reports the board as a COM port.
8. Compile one profile.
9. Upload only after list-ports and compile succeed.

Future cleanup option: replace the Bash upload orchestration with a cross-platform Python wrapper around Arduino CLI. That would preserve one codebase better than maintaining separate Bash and PowerShell implementations long-term.

## Windows Packaging Details Still Needed

The current builder creates a Windows `.exe`, but release-grade Windows packaging still needs decisions.

### Icon

The macOS `.icns` generation is automated. Windows `.ico` generation is automated too.

Use the same tracked source image:

```text
V3_6/assets/appIcon.png
```

The builder converts that PNG into a Windows `.ico` in the ignored build tree:

```text
V3_6\build\windows\icons\PrimusCentral.ico
```

The generated icon is passed to PyInstaller by default:

```powershell
py V3_6\build_sender_app.py --target windows
```

Pillow is required as a build-time tool for the conversion and is listed in `V3_6\requirements-build.txt`; it is not a sender runtime dependency. A custom `.ico` can still be supplied with `--icon` when needed.

The `.ico` should include common Windows sizes: 16, 24, 32, 48, 64, 128, and 256 px.

### Signing

The builder supports optional Windows Authenticode signing with Azure Artifact Signing. The build machine needs:

- An Artifact Signing account with completed identity validation.
- A certificate profile.
- The signing user or service principal assigned the **Artifact Signing Certificate Profile Signer** role.
- Azure CLI login or another Azure `DefaultAzureCredential` method.
- Windows SDK SignTool, .NET 8, and the Artifact Signing Client Tools dlib.

Install the Azure client-side tools:

```powershell
winget install -e --id Microsoft.AzureCLI
winget install -e --id Microsoft.Azure.ArtifactSigningClientTools
winget install -e --id JRSoftware.InnoSetup
```

Create local metadata under the ignored build tree:

```json
{
  "Endpoint": "https://eus.codesigning.azure.net",
  "CodeSigningAccountName": "<Artifact Signing account name>",
  "CertificateProfileName": "<Certificate profile name>",
  "CorrelationId": "PrimusCentral-0.7"
}
```

The endpoint must match the Azure region for the signing account. Then sign as part of the Windows build:

```powershell
az login
az account set --subscription "<subscription name or id>"
py V3_6\build_sender_app.py --target windows `
  --windows-sign-metadata V3_6\build\windows\signing\metadata.json `
  --windows-sign-dlib "C:\Path\To\Azure.CodeSigning.Dlib.dll"
```

The builder uses SHA-256 and Microsoft's Artifact Signing timestamp URL, `http://timestamp.acs.microsoft.com`, then verifies the signature with SignTool. Signing mutates the `.exe`; rebuild the release ZIP and checksum after signing.

### Installer Versus Standalone Executable

The recommended Windows 0.7 GitHub release publishes both a signed installer and a portable ZIP. The installer is the easiest option for most users: it installs PrimusCentral into a user-local app directory, creates Start Menu shortcuts, offers an optional desktop shortcut, and can be signed alongside the app. The ZIP remains the fallback for portable use or environments where an installer is inconvenient. Do not upload the raw `.exe`; direct executable downloads are more likely to be interrupted or warned on by browsers and endpoint tools.

Recommended release asset names:

```text
PrimusCentral-0.7-Windows-x64-Setup.exe
PrimusCentral-0.7-Windows-x64-Setup.exe.sha256
PrimusCentral-0.7-Windows-x64.zip
PrimusCentral-0.7-Windows-x64.zip.sha256
```

The ZIP should contain:

```text
PrimusCentral.exe
README-Windows.txt
```

Build the installer with Inno Setup after the app has been signed:

```powershell
py V3_6\build_sender_app.py --target windows --windows-installer `
  --windows-sign-metadata V3_6\build\windows\signing\metadata.json `
  --windows-sign-dlib "C:\Path\To\Azure.CodeSigning.Dlib.dll"
```

The current installer intentionally stays simple:

- User-local install under `%LOCALAPPDATA%\Programs\PrimusCentral`.
- Start Menu shortcut and optional desktop shortcut.
- App and installer signing when Azure metadata is supplied.
- No firewall-rule automation or USB-driver installation yet.

A signed installer or ZIP should reduce warnings compared with an unsigned raw executable, but users may still need manual firewall approval and occasional SmartScreen confirmation while the app builds Windows reputation.

## Windows Build Checklist

Run this checklist from a fresh Windows checkout when possible.

### 1. Basic Environment

```powershell
py --version
py -m pip --version
py -m pip install --upgrade pip
py -m pip install -r V3_6\requirements-build.txt
```

Optional virtual environment:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
py -m pip install --upgrade pip
py -m pip install -r V3_6\requirements-build.txt
```

If PowerShell blocks activation scripts, either use `cmd.exe` activation or adjust the current-user execution policy intentionally:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

### 2. Source Checks

PowerShell wildcard expansion differs from Unix shells, so use a small Python command for compile checks:

```powershell
py -c "import pathlib, py_compile; [py_compile.compile(str(p), doraise=True) for p in pathlib.Path('V3_6/sender').glob('*.py')]"
py -m unittest discover -s V3_6\sender\tests
```

Run the source sender without opening a browser:

```powershell
py V3_6\sender\run.py --no-browser --port 0
```

Open the printed localhost URL manually and confirm the UI loads.

### 3. Build The Executable

```powershell
py V3_6\build_sender_app.py --target windows
```

Expected artifact:

```text
V3_6\dist\windows\PrimusCentral.exe
```

If the app closes immediately or behavior is unclear, rebuild with a console:

```powershell
py V3_6\build_sender_app.py --target windows --console
```

If one-file extraction seems related to startup, antivirus, or timing, compare with:

```powershell
py V3_6\build_sender_app.py --target windows --onedir
```

### 4. First Launch

1. Double-click `V3_6\dist\windows\PrimusCentral.exe`.
2. Confirm Chrome, Edge, Brave, Chromium, or the default browser opens to PrimusCentral.
3. Confirm the app writes logs/data under `%APPDATA%\PrimusV3\V3_6\sender\`.
4. Save a clip or look.
5. Quit and relaunch.
6. Confirm saved data persists.

### 5. Receiver And Network

1. Connect the Windows machine to the show router or receiver network.
2. Put the Windows adapter on the correct DHCP/static IPv4 setup manually.
3. Launch PrimusCentral.
4. Allow Windows Firewall prompts for the show network.
5. Run discovery.
6. If discovery fails, add a receiver manually by IP.
7. Connect the receiver.
8. Test live preview.
9. Test Hello and Rename if the receiver advertises those capabilities.
10. Test output config if needed.
11. Test receiver IP config only if the receiver capability is present and the network is prepared.
12. Query `/api/performance` while output is running.

### 6. Firmware Panel, If In Scope

1. Confirm Git Bash or another usable `bash` is installed and on `PATH`.
2. Confirm Python is available as `python3` or through the managed shim path.
3. Run Firmware Tools setup.
4. Connect exactly one ESP32 board.
5. Run list-ports.
6. Compile the intended profile.
7. Upload only after list-ports and compile are reliable.

## Known Gaps And Do-Not-Fork Rule

Do not create a separate Windows sender branch. The Windows work should preserve the existing V3.6 sender, firmware, protocol, output tables, and saved data model.

Known Windows gaps to address only when needed:

- Windows timer-resolution or thread-priority tuning if packaged FPS misses target.
- Windows firewall rule installation for public distribution.
- Authenticode signing and release reputation.
- Non-Bash firmware uploader path.
- More explicit Windows tests for browser launch, app-data paths, firmware tool availability, and unsupported network Settings behavior.

When adding Windows-specific behavior, keep it narrow and guarded:

- `build_sender_app.py` for packaging differences.
- `paths.py` for filesystem/resource/tool paths.
- `run.py` for browser/process/platform runtime behavior.
- `network_settings.py` or a small helper module for host network adapter logic.
- `firmware.py` for firmware job command construction.
- `state.py` only for measured timing improvements.

The 0.7 workshop profile remains UI-only. Do not remove output types from sender state, API, saved files, or firmware to simplify Windows packaging.

## Useful References

- [PACKAGING.md](PACKAGING.md) - current app packaging and macOS release procedure.
- [SENDER_DEVELOPMENT.md](SENDER_DEVELOPMENT.md) - sender architecture and test commands.
- [FIRMWARE_DEVELOPMENT.md](FIRMWARE_DEVELOPMENT.md) - receiver build profiles and firmware validation.
- [ConnectionSettings.md](ConnectionSettings.md) - macOS sender network Settings behavior and API.
- [../API_REFERENCE.md](../API_REFERENCE.md) - Art-Net, FPS telemetry, OSC, and HTTP API protocol reference.
- [07ReleaseNotes.md](07ReleaseNotes.md) - 0.7 workshop profile context.

## First Windows Baseline Notes Template

Copy this into the release notes or a test log after the first Windows pass.

```text
Windows build date:
Windows version:
Machine CPU/RAM:
Python version:
PyInstaller version:
Build command:
Artifact path:
Onefile or onedir:
Signed or unsigned:
Firewall prompt observed:
Browser used:
Receiver hardware/profile:
Receiver firmware version:
Network type:
Adapter IP mode:
Discovery result:
Manual add result:
Live preview result:
Receiver FPS:
/api/performance animation frame delta:
/api/performance sleep latency avg/max:
Firmware panel setup result:
Firmware list-ports result:
Known issues:
Next action:
```
