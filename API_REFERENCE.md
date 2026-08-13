# API Reference — moved

The canonical protocol and HTTP API documentation now lives with the V5 tree
it describes:

- **[V5/API_REFERENCE.md](V5/API_REFERENCE.md)** — the complete backend HTTP
  API (all routes), Art-Net integration guide for external tools, and wire
  formats for the custom opcodes.
- **[V5/PORTS_AND_LANES.md](V5/PORTS_AND_LANES.md)** — UDP lane model
  (Show / Setup / Watch), Node Report advertisement, migration state.
- **[V5/FIRMWARE_REFERENCE.md](V5/FIRMWARE_REFERENCE.md)** — receiver
  firmware behavior, telemetry byte layouts, capability tags, NVS.

The V3.6-era protocol description this file used to contain is preserved in
git history (`git log -- API_REFERENCE.md`); the V3.6 source tree under
`V3_6/` still documents that track.
