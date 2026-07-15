# PrimusCentral v0.9

macOS release built from the V4 unified sender (`--product primus`).

## Changes

- **Clip preview flicker fix** — hover previews in the Clip Library and Look Designer palette overlay the thumbnail instead of expanding the card, preventing layout reflow and flashing on narrow windows.
- **V4 as canonical PrimusCentral track** — repo docs now point development, packaging, and firmware work at `V4/`; shipped app reports `PrimusCentral v0.9`.
- **UI** — navbar shows `PrimusCentral v0.9`.

## Validation

- `python3 -m unittest discover -s V4/sender/tests`
- `PrimusCentral.app` Developer ID signed with network entitlements, notarized, and stapled
- `PrimusCentral-0.9-macOS-arm64.dmg` signed, notarized, stapled, and verified with `hdiutil verify`
- `py -m unittest discover -s V4\sender\tests`
- `py -c "import pathlib, py_compile; py_compile.compile('V4/build_sender_app.py', doraise=True); [py_compile.compile(str(p), doraise=True) for p in pathlib.Path('V4/sender').glob('*.py')]"`
- `PrimusCentral.exe` and `PrimusCentral-0.9-Windows-x64-Setup.exe` signed with Azure Artifact Signing and verified with SignTool
- Packaged Windows smoke test: runtime reports `primus` / `0.9`, OSC receives a Wi-Fi-address packet, `/api/performance` holds about 30 FPS idle
- Packaged Windows responsiveness test: `/api/integrations/osc` returns in about 26-41 ms and OSC packets appear in the Cue Controller log in about 34 ms
- Windows installer shortcut validation: Start Menu and Desktop shortcuts install `PrimusCentral.ico` and set `IconLocation` to that custom icon

## Assets

- `PrimusCentral-0.9-macOS-arm64.dmg`
- `PrimusCentral-0.9-macOS-arm64.dmg.sha256`
- `PrimusCentral-0.9-Windows-x64-Setup.exe`
- `PrimusCentral-0.9-Windows-x64-Setup.exe.sha256`
- `PrimusCentral-0.9-Windows-x64.zip`
- `PrimusCentral-0.9-Windows-x64.zip.sha256`

## SHA-256

```text
b845fc7077f7c6512cb1c551a9a290c7a3347afa6a318c9bea560821442b0ad6  PrimusCentral-0.9-macOS-arm64.dmg
2797479E97CE335C90F8C640336DC8513D3889AC9177CAD2BF8102A2AE29A3C9  PrimusCentral-0.9-Windows-x64-Setup.exe
8552C2BC526AF4106BF030DF93A5BEA2D57EE87AAB3695F0EAF23974073C65F0  PrimusCentral-0.9-Windows-x64.zip
```
