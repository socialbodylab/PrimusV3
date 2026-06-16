# AGENTS.md

See `CLAUDE.md` for the full project overview, repository layout, run/test commands, and conventions. That file is the source of truth for how the codebase is organized.

## Cursor Cloud specific instructions

### Environment

- The senders are **pure Python 3 stdlib** — there are **no runtime dependencies to install** to run or test them. Python 3.12 is preinstalled. `V3_6/requirements-build.txt` / `V4/requirements-build.txt` (`pyinstaller`, `pillow`) are **packaging-only** and are not needed for development, tests, or running the apps.
- The startup update script therefore does no dependency installation; it only confirms Python is present.

### Runnable services (all are local web apps; see `CLAUDE.md` for canonical commands)

- **PrimusCentral V3.6** (active LED track): `python3 V3_6/sender/run.py --no-browser --port 8097` → UI at `http://127.0.0.1:8097/`.
- **Radius/Primus Central V4**: `python3 V4/sender/run.py --no-browser --port 8090` → one server serves `/radius`, `/primus`, and `/devices`. Note V4 `run.py` uses `--frontend {primus,radius,devices}` (not `--product`) to pick the default UI.
- Always pass `--no-browser` in the cloud VM, otherwise the launcher tries to spawn Chrome.

### Non-obvious run caveats

- Only one process can bind the UDP **telemetry port 6455** at a time. Running more than one sender simultaneously logs a harmless "telemetry port in use" warning on the later one(s); HTTP/API/UI still work. For clean isolation run one sender at a time.
- `V3_6/sender/run.py` **kills any previously running V3.x sender instance** on startup (`_kill_existing`). `V4/sender/run.py` instead **attaches to an already-running Central** rather than starting a second server; use `--replace` to force a fresh start.
- Running senders from source writes runtime artifacts into the repo tree (e.g. `V4/sender/.central_server.json`, `V4/sender/audio_cues.json`, and new clip JSON under `V3_6/sender/clips/`). These are runtime/test state — do not commit them. App state files (`.primus_state.json`, `.radius_state.json`) are already gitignored.
- The ESP32 receiver firmware under `*/Arduino/` **cannot run in the cloud VM** (no hardware/serial port). It can only be compiled with `arduino-cli`; flashing requires a connected board.

### Test caveats (pre-existing failures, not environment issues)

Run with `python3 -m unittest discover -s V3_6/sender/tests` and `... -s V4/sender/tests`.

- `V3_6` has 2 **Windows-only** packaging tests that error on Linux (`Windows installer/Artifact Signing must run on Windows`) and 1 outdated test (`test_server_lifecycle.test_runtime_reports_lifecycle_enabled`) that doesn't expect the new `product` field in `/api/runtime`.
- `V4` has 2 deterministic failures in `test_mixer_timeline_wrapping` (effect-computation expectations).
- These are pre-existing and unrelated to environment setup. The rest of the suites pass (V3_6 129/132, V4 119/121).
- Some tests (`test_packaging_builder`, `test_run_launcher`, `test_central_launcher`) shell out to build/launch scripts, so the suite prints stray "Building windows..." / "Central already running" lines — this is expected test noise.
