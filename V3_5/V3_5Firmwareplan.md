# Overview
Create a V3.5 firmware and controller based on V3.1 that can run V1, V2, and V3.1 Primus hardware together on the same network using the current Art-Net and web-controller protocol.

# Main Principles

## Shared firmware source for all boards
V3.5 uses one shared source tree with separate Arduino build profiles for each hardware generation. ESP32 and ESP32-S3 targets cannot share one literal binary, but the protocol and receiver logic stay shared.

### Board profiles
- `v1` - Adafruit Huzzah32, no screen, direct NeoPixel outputs on GPIO32 and GPIO12.
- `v2` - Adafruit ESP32 Feather V2, no screen, direct NeoPixel outputs on GPIO32 and GPIO12.
- `v3_1` - ESP32-S3 Reverse TFT Feather with NeoPXL8 FeatherWing outputs 6 and 7 on GPIO14/GPIO15.

### Board type discovery
The firmware advertises its profile in the ArtPollReply Node Report using the existing `PV3CAP1` capability tag plus a compatible `B:<profile>` segment. V1/V2 physical variants still rely on build-profile defaults and saved output configuration because the old boards do not expose a unique hardware ID signal.

## Color Data via current API
Versions 1 and 2 are reflashed with V3.5 firmware and receive color data through the current Art-Net sender path. The controller does not need to send the old V1 OSC messages or the old V2 brightness-byte Art-Net payload.

## Expand on the current controller

### Selectable outputs
Though some of the boards have the small grid physically attached, keep the same interface method that allows the user to simply choose the output type for each of the 2 outputs.

### Add new output types
- Small Grid 4x8 grid
- Extra Long Strip - 122 pixel strip

### Naming/IP via interface
Even though V1 and V2 do not have screens, they should be configurable via the control panel similar to V3.
- Auto IP / default name at first
- Settable/savable new name/IP via the interface
- Hello feature to "find" the board in the space

# Implementation status
- `V3_5/Arduino/primusV3_receiver/` has been scaffolded from V3.1 and now supports `v1`, `v2`, and `v3_1` build profiles.
- `V3_5/sender/` has been scaffolded from V3.1 and now includes `small_grid` and `extra_long_strip` output types.
- V3.5 discovery parses and exposes hardware profile metadata while remaining compatible with V3.1 `PV3CAP1` replies.
- `V3_5/Arduino/upload.sh` accepts `--board v1`, `--board v2`, and `--board v3_1`.
- See `V3_5/hardwareCompatibility.md` for profile, pin, output type, and compile details.