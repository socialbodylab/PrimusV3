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

## Windows PrimusCentral 0.9

Build Windows releases on Windows. The current PrimusCentral release target is
the V4 unified sender with the Primus product selected:

```powershell
py -m pip install -r V4\requirements-build.txt
py V4\build_sender_app.py --target windows --product primus
```

Output:

```text
V4\dist\windows\PrimusCentral.exe
```

For release distribution, publish a signed installer and a portable ZIP. Do not
upload the raw executable as a GitHub release asset.

Expected 0.9 assets:

```text
PrimusCentral-0.9-Windows-x64-Setup.exe
PrimusCentral-0.9-Windows-x64-Setup.exe.sha256
PrimusCentral-0.9-Windows-x64.zip
PrimusCentral-0.9-Windows-x64.zip.sha256
```

The installer includes `README-Windows.txt`, generated from the tracked
`V4/PrimusCentral-Windows-README.txt` template. The installer remains
user-local under `%LOCALAPPDATA%\Programs\PrimusCentral` and does not create
firewall rules.

### Azure Artifact Signing

Install the required signing and installer tools on the Windows release machine:

```powershell
winget install -e --id Microsoft.AzureCLI
winget install -e --id Microsoft.Azure.ArtifactSigningClientTools
winget install -e --id JRSoftware.InnoSetup
```

SignTool also needs Windows SDK build tools and .NET 8. Sign in with an account
that has the **Artifact Signing Certificate Profile Signer** role:

```powershell
az login
az account set --subscription "<subscription name or id>"
```

Create ignored local metadata such as
`V4\build\windows\signing\metadata.json`:

```json
{
  "Endpoint": "https://eus.codesigning.azure.net",
  "CodeSigningAccountName": "<Artifact Signing account name>",
  "CertificateProfileName": "<Certificate profile name>",
  "CorrelationId": "PrimusCentral-0.9"
}
```

Build, sign, verify, and create the installer:

```powershell
py V4\build_sender_app.py --target windows --product primus --windows-installer `
  --windows-sign-metadata V4\build\windows\signing\metadata.json `
  --windows-sign-dlib "C:\Path\To\Azure.CodeSigning.Dlib.dll"
```

Equivalent environment variables:

```powershell
$env:PRIMUSV3_WINDOWS_SIGN_METADATA = "V4\build\windows\signing\metadata.json"
$env:PRIMUSV3_ARTIFACT_SIGNING_DLIB = "C:\Path\To\Azure.CodeSigning.Dlib.dll"
$env:PRIMUSV3_SIGNTOOL = "C:\Path\To\signtool.exe"
py V4\build_sender_app.py --target windows --product primus --windows-installer
```

Manual signature checks:

```powershell
signtool verify /pa /v V4\dist\windows\PrimusCentral.exe
signtool verify /pa /v V4\dist\windows\PrimusCentral-0.9-Windows-x64-Setup.exe
Get-AuthenticodeSignature V4\dist\windows\PrimusCentral.exe, V4\dist\windows\PrimusCentral-0.9-Windows-x64-Setup.exe | Format-List
```

### ZIP And Checksums

Generate ZIPs and checksums only after signing, because signing mutates the
binary files:

```powershell
Remove-Item V4\build\windows\release-staging -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force V4\build\windows\release-staging\PrimusCentral-0.9-Windows-x64 | Out-Null
Copy-Item V4\dist\windows\PrimusCentral.exe V4\build\windows\release-staging\PrimusCentral-0.9-Windows-x64\PrimusCentral.exe
Copy-Item V4\dist\windows\README-Windows.txt V4\build\windows\release-staging\PrimusCentral-0.9-Windows-x64\README-Windows.txt
Compress-Archive -Path V4\build\windows\release-staging\PrimusCentral-0.9-Windows-x64 -DestinationPath V4\dist\windows\PrimusCentral-0.9-Windows-x64.zip -Force
Get-FileHash V4\dist\windows\PrimusCentral-0.9-Windows-x64.zip -Algorithm SHA256 | ForEach-Object { "$($_.Hash)  PrimusCentral-0.9-Windows-x64.zip" } | Set-Content V4\dist\windows\PrimusCentral-0.9-Windows-x64.zip.sha256 -Encoding ASCII
Get-FileHash V4\dist\windows\PrimusCentral-0.9-Windows-x64-Setup.exe -Algorithm SHA256 | ForEach-Object { "$($_.Hash)  PrimusCentral-0.9-Windows-x64-Setup.exe" } | Set-Content V4\dist\windows\PrimusCentral-0.9-Windows-x64-Setup.exe.sha256 -Encoding ASCII
```

### Windows Network Validation

PrimusCentral 0.9 removed the OSC host setting. The listener opens sockets on
all interfaces, active LAN IPs, and loopback; the Cue Controller shows active
sockets and a network log. Windows users may still need to allow Defender
Firewall on the private/show network when the packaged app first uses UDP.

Validate these paths before publishing:

- Local browser UI opens on `127.0.0.1` and does not require a firewall rule.
- Art-Net discovery/output works on UDP `6454`.
- Receiver FPS telemetry appears on UDP `6455`.
- External OSC cue input works from another computer on UDP `53001` by sending
  to one of the LAN addresses shown in Cue Controller.
- Cue Controller network log shows active sockets and packet receipts for the
  OSC test.

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
