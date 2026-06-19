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
4B7B187FB11D227D3BC0C27A7874935921FF808138A65E495237CB211D525BD3  PrimusCentral-0.86-Windows-x64-Setup.exe
AB07FB407964C660A98FDDA16C19B7E0D7658DAFBAC16CA28C19D5FE286EEFC9  PrimusCentral-0.86-Windows-x64.zip
```
