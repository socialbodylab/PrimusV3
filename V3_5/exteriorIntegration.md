# External Integration

Primus Central can receive inbound OSC cue triggers from show-control tools such as QLab. This first implementation is receive-only: external software can fire Primus cues, stop controller playback, or send blackout, while Primus does not yet send status back to the external tool.

## Listener

Default endpoint:

```text
127.0.0.1:53001
```

The Cue Controller panel shows the current OSC status, bound host/port, recent received messages, and per-cue QLab-style trigger addresses. The listener can be enabled, disabled, or rebound from that panel. Settings persist under the `osc_control` key in `.primus_state.json`.

## Supported OSC Messages

| Address | Arguments | Action |
| --- | --- | --- |
| `/primus/cue/go` | none | Fire the next cue. |
| `/cue/go` or `/go` | none | Fire the next cue. |
| `/primus/cue/goto` | integer cue number | Fire a cue by number. |
| `/primus/cue/name` | string cue name | Fire a cue by exact name, then unique slug fallback. |
| `/cue/goto` | integer cue number | Fire a cue by number using a shorter external-tool alias. |
| `/cue/name` | string cue name | Fire a cue by name using a shorter external-tool alias. |
| `/primus/cue/<slug>` | none | Fire a cue by number or slug. |
| `/cue/<slug>/start` | none | Fire a cue by number or slug using a QLab-friendly path. |
| `/primus/cue/stop`, `/cue/stop`, `/stop` | none | Stop controller playback and release output. |
| `/primus/blackout`, `/blackout`, `/panic` | optional fade seconds | Fade or cut to blackout. |

Cue slug rules: lowercase the cue name, replace non-alphanumeric runs with `-`, and trim leading/trailing dashes. For example, `Opening Look` becomes `opening-look`.

Name matching is exact case-insensitive first. If no exact name is found, Primus tries the slug. Slug matches must be unique; ambiguous names or slugs are rejected and shown in the OSC message history.

## QLab Setup

Create a Network cue in QLab with an OSC message targeted at the Primus Central host and port. For Primus Central running on the same Mac as QLab, use `127.0.0.1` and port `53001`.

Common cue messages:

```text
/cue/opening-look/start
/primus/cue/goto 3
/primus/cue/go
/primus/blackout 0.5
```

For a show router workflow with another show-control computer, bind Primus OSC to the sender computer's show-network IP in the Cue Controller panel, then point QLab at that IP and port. Keep Art-Net receiver networking and OSC sender networking on the same intended show network when possible.

## Implementation Notes

OSC parsing and UDP listening live in `V3_5/sender/osc_control.py` and use only Python stdlib modules. The OSC command router calls the same `CueList` and `ControllerState` methods used by the HTTP Cue Controller API, so external triggers share the current cue playback, blackout, device targeting, and controller playback-source behavior.