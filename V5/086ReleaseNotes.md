# PrimusCentral v0.86

macOS release built from the V4 unified sender (`--product primus`).

## Changes

- **OSC multi-interface listener** — binds UDP on all interfaces, each active LAN IP, and loopback with `SO_REUSEPORT` so remote packets reach the listener on multi-homed Macs.
- **OSC network log** — Cue Controller shows bind results, socket list, and per-packet local/LAN receipt for debugging.
- **No OSC host setting** — only enable and port are configurable; host bind is always automatic.
- **Packaging fix** — signs the inner app executable with network entitlements before the bundle; embeds app version at build time.
- **UI** — navbar shows `PrimusCentral v0.86`.

## Validation

- `python3 -m unittest discover -s V4/sender/tests`
- `PrimusCentral.app` Developer ID signed with network entitlements, notarized, and stapled
- `PrimusCentral-0.86-macOS-arm64.dmg` signed, notarized, stapled, and verified with `hdiutil verify`
- `py -m unittest discover -s V4\sender\tests`
- `py -c "import pathlib, py_compile; [py_compile.compile(str(p), doraise=True) for p in pathlib.Path('V4/sender').glob('*.py')]"`
- `PrimusCentral.exe` and `PrimusCentral-0.86-Windows-x64-Setup.exe` signed with Azure Artifact Signing and verified with SignTool
- Packaged Windows smoke test: runtime reports `primus` / `0.86`, OSC receives loopback and Wi-Fi-address packets, `/api/performance` holds about 30 FPS idle
- Windows installer shortcut validation: Start Menu and Desktop shortcuts install `PrimusCentral.ico` and set `IconLocation` to that custom icon

## Assets

- `PrimusCentral-0.86-macOS-arm64.dmg`
- `PrimusCentral-0.86-macOS-arm64.dmg.sha256`
- `PrimusCentral-0.86-Windows-x64-Setup.exe`
- `PrimusCentral-0.86-Windows-x64-Setup.exe.sha256`
- `PrimusCentral-0.86-Windows-x64.zip`
- `PrimusCentral-0.86-Windows-x64.zip.sha256`

## SHA-256

```text
6f17428546ac32acbe71952159da414a538e766f6b5672f8e86db1ce3e855959  PrimusCentral-0.86-macOS-arm64.dmg
C5E8DFE0FA1D4CCAB915B3F3FE13D997F997A9B53C56F5362A8363394D36EF1A  PrimusCentral-0.86-Windows-x64-Setup.exe
0DC43B4ADCA90E48F5D974C0144DB45CB8BC4AC06D0AEBF0410D1BB76141E94B  PrimusCentral-0.86-Windows-x64.zip
```
