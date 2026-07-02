# Puck.js v2 Setup Guide

## Prerequisites

**Grant Bluetooth access to your terminal** (required on macOS — without this you get `Abort trap: 6`):
- System Settings → Privacy & Security → Bluetooth → add Terminal.app or iTerm2

**Install the Espruino CLI:**
```bash
npm install -g espruino
```

> If you hit native build errors during install, use Node.js 18 or 20 rather than bleeding-edge versions.

---

## First-Time Setup

**Discover the Puck:**
```bash
espruino --list
```

**Clear any existing code** (important if the Puck was previously used):
```bash
espruino -d Puck -e "reset(true)"
```

**Upload firmware and save to flash:**
```bash
espruino -d Puck puckjsbutton.js -e "save()"
```

`-d Puck` matches any device whose name starts with "Puck". After the first connection the full name (e.g. `Puck.js abc`) can also be used with `-d "Puck.js abc"`.

---

## Re-flashing

```bash
espruino -d Puck -e "reset(true)" && espruino -d Puck puckjsbutton.js -e "save()"
```

---

## Development / Live Reload

Upload without saving to flash — code runs but is lost on power cycle. Good for testing changes:
```bash
espruino -d Puck -w puckjsbutton.js
```

---

## Hardware Factory Reset

If you cannot connect over BLE at all:

1. Hold the button for ~10 seconds
2. Green LED lights, then all 3 LEDs light, then red blinks 5 times
3. Release — all saved code and BLE bonding data is cleared

---

## Behaviour

| Gesture | Output |
|---|---|
| Button press | `btn/press` over BLE UART |
| Button release | `btn/release` over BLE UART |
| Button held | `accel x y z` at 12.5 Hz over BLE UART |
| Triple tap | `btn/sleep` then device sleeps |

Press once to wake from sleep. The Radius will detect the reconnect automatically.

---

## Known Issues

| Symptom | Fix |
|---|---|
| `Abort trap: 6` on connect | Add terminal to macOS Bluetooth privacy list |
| Device not found by `--list` | Use `-d Puck` (name match) rather than MAC address on first connect |
| `save()` fails silently | Device has prior Web IDE code — run `reset(true)` first |
| Build errors on `npm install` | Use Node.js 18 or 20; or add `--ignore-scripts` |
