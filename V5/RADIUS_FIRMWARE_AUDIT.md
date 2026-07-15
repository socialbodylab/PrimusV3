# Radius Firmware Audit — `origin/radius-central` vs V4 `radius_receiver`

Compared June 2026. Branch tip: `origin/radius-central` → `V3_6/Arduino/radiusV2/`. V4 track: `V4/Arduino/radius_receiver/`.

## Feature matrix

| Feature | Branch `radiusV2` | V4 before port | Port decision |
|---------|-------------------|----------------|---------------|
| V1 HUZZAH32 + Music Maker | Yes (`TARGET_BOARD`) | Yes (V1 only) | **Port** unified V1+V2 switch |
| V2 S3 Reverse TFT + display | Yes | display.h present, unused on V1 | **Port** |
| Capability tag | `PV3CAP1\|F:RIH` | `PVRAD1\|B:v1\|F:RA` | **Modernize** → `PVRAD1\|B:v1\|v2\|F:RIHAS` |
| ArtShowInfo `0x8210` | No | No | **Add** from Primus pattern |
| ArtAddress rename | Yes | Yes | **Keep** |
| ArtIPConfig `0x8200` | Yes | Yes | **Keep** |
| ArtAudioCmd `0x8300` | Yes | Yes | **Keep** |
| ArtFtpCmd `0x8301` | Yes | Yes | **Keep** |
| ArtAudioStatus `0x8302` | Yes (UDP 6455) | No | **Port** (supplemental) |
| PTR track telemetry | No | Yes (UDP 6455) | **Keep V4** as primary sender path |
| PFP packet rate | Serial only | Yes (UDP 6455) | **Keep V4** |
| OSC `/cue/N`, `/stop`, `/hello` | Yes (53001) | No | **Port** |
| Marius BLE puck | Yes (`marius.h`) | No | **Port** |
| `/cues.json` cue map | Yes | Yes | **Keep** |
| FTP credentials | `primus`/`primus` | `radius`/`radius` | **Keep V4** |
| Show info NVS seeding | No | No | **Add** (character from device name, performer default) |

## NodeReport target (post-port)

```
#0001 [pppp] PVRAD1|B:v2|IP:D|F:RIHAS|MC:1|MP:PuckName
```

Static IP uses full `IP:S:a.b.c.d:g.w.x.y:s.u.b.n` triple (V4 format). Marius `MC`/`MP` tokens appended when configured.

## Upload profiles

| Profile | Board | Script flag |
|---------|-------|-------------|
| `radius_v1` / `rv1` | HUZZAH32 | `--board radius_v1` |
| `radius_v2` / `rv2` | ESP32-S3 Reverse TFT | `--board radius_v2` |

## Deferred (not in this port)

- Sender ingestion of `0x8302` ArtAudioStatus (PTR remains primary)
- Battery telemetry on Radius hardware

## Safety

Primus firmware (`V4/Arduino/primusV3_receiver/`) is not modified. All changes are isolated to `V4/Arduino/radius_receiver/` and `radius_upload.sh`.
