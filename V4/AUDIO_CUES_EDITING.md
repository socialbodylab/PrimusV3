# Editing the Audio Cue JSON Files Directly

Two different JSON files drive Radius audio cues. They live in different
places, have different schemas, and reload at different times:

| File | Lives | Used by | Reloads |
|------|-------|---------|---------|
| `audio_cues.json` | Sender data directory | Audio Cues page, OSC `/cue/N`, `/api/audio_cues/fire` | **At sender startup only** |
| `/cues.json` | Each device's SD card | Firmware cue commands (ArtAudioCmd 6/7) | **At device boot only** |

The sender cue sheet resolves cues itself and sends plain play/loop/stop
commands with filenames. The device cue map lets a cue number be fired at
the device directly (or from OSC hardware) without the sender resolving it.

---

## 1. Sender cue sheet — `audio_cues.json`

### Where it is

- Source runs: `V4/sender/audio_cues.json`
- Packaged macOS app: `~/Library/Application Support/PrimusV3/...` (see `paths.py`)

### The one rule that bites: stop the sender first

The server loads this file **once at startup** into memory
(`server.py`, `Handler.audio_cues_data`). While Radius Central is running:

- your file edits are invisible to the app until restart, and
- any edit made in the Audio Cues page **saves the in-memory copy back to
  disk, overwriting your changes**.

So: quit Radius Central → edit the file → start Radius Central.
(Editing while it runs is fine only if nobody touches the Audio Cues UI
before the restart.)

Make a backup first: `cp audio_cues.json audio_cues.json.bak`

### Schema

```json
{
  "cues": [
    {
      "number": 1,
      "note": "Overture",
      "actions": {
        "192.168.8.150": {
          "cmd": "play",
          "filename": "Radius_Overture.wav",
          "volume": 97,
          "duration": 0,
          "delay_ms": 0
        }
      }
    },
    { "number": 2, "note": "", "actions": {} }
  ]
}
```

Per cue:

- `number` — integer 1–255. **Must be unique across the file.** Duplicates
  break the page (cards silently fail to render past the duplicate) and
  break firing (fire-by-number picks the first match; the other can never
  fire). Empty `actions: {}` is a placeholder cue.
- `note` — free text, shown on the cue card.
- `actions` — object keyed by **device IP**. A device not listed is simply
  skipped when the cue fires. IP keys must match the current device list —
  if a device gets a new DHCP address, its actions stop matching silently.

Per action:

- `cmd` — `"play"`, `"loop"`, or `"stop"` (`"none"` also means skip).
- `filename` — must match the WAV on that device's SD card **exactly**,
  including case and spelling (max 64 chars). A wrong name fails silently
  from the UI's perspective: the command sends fine, the device logs
  `could not open` and plays nothing. Copy-paste names; never retype.
- `volume` — 0–100. Note that 0 is a valid value and plays silence.
- `duration` — seconds; `0` = play the whole file.
- `delay_ms` — milliseconds before the device executes. Caution: the
  firmware has a **single pending-cue slot per device**; a second delayed
  command arriving before the first fires replaces it.

### Validate after editing

```bash
python3 -c "
import json
data = json.load(open('V4/sender/audio_cues.json'))
nums = [c['number'] for c in data['cues']]
dupes = sorted(n for n in set(nums) if nums.count(n) > 1)
print(len(nums), 'cues; duplicates:', dupes or 'none')
"
```

Anything other than `duplicates: none` must be fixed before starting the app.

### Bulk edits

For anything beyond a couple of cues, generate the file with a small Python
script (load → modify → dump with `indent=2`) instead of hand-editing —
it guarantees valid JSON and makes "same file on all seven devices" a loop
instead of 80 copy-pasted blocks. See the git history of this repo's cue
sheet work for examples.

---

## 2. Device cue map — `/cues.json` on the SD card

### Schema (all forms accepted)

```json
{
  "1": "file.wav",
  "2": { "file": "file.wav", "duration": 30 },
  "3": { "cmd": "loop", "file": "a.wav", "volume": 80 },
  "5": { "cmd": "stop" },
  "6": { "cmd": "volume", "volume": 70 }
}
```

- Keys are cue numbers **as strings**, 1–255. Max **64 entries** load.
- `cmd`: `"play"` (default), `"loop"`, `"stop"`, `"volume"`.
- Omit `volume` to use the device's current volume.
- `delay` (ms) is also accepted per entry.

### How to get it onto a device

- Cue Map panel in Radius Central (`GET/POST /api/audio/cue_map`), or
- any FTP client to the device (user/pass in `config.h`), or
- pull the SD card and edit directly.

### The one rule that bites: reboot the device

Firmware parses `/cues.json` **once, in `setup()`** (`cuesLoad()`).
Pushing a new file does **not** take effect until the device power-cycles.
A parse error disables all cue commands on that device until fixed —
check the serial log for `[Cues] Parse error:` if cues 6/7 stop working.

---

## Quick reference: which file do I edit?

- "Fire from the Audio Cues page / OSC to the sender" → `audio_cues.json`,
  restart the **sender**.
- "Fire cue numbers at the device directly (ArtAudioCmd 6/7)" →
  `/cues.json` on that device's SD, reboot the **device**.
