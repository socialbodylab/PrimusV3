# ReceiveMode — implemented

This draft plan has been implemented in the V4 track. See:

- [`V4/Arduino/primusV3_receiver/receive_mode.h`](../V4/Arduino/primusV3_receiver/receive_mode.h) — firmware module
- [`API_REFERENCE.md`](../API_REFERENCE.md) §5.1 — ArtReceiveConfig `0x8110`
- [`V3_6/ARTNET_EXTERNAL_INTEGRATION.md`](ARTNET_EXTERNAL_INTEGRATION.md) — EOS combined-universe patching
- [`V4/FIRMWARE_DEVELOPMENT.md`](../V4/FIRMWARE_DEVELOPMENT.md) — upload flags and NVS keys

Firmware version **3.8.0** introduces split/combined receive modes with discovery tokens `U:S:N` / `U:C:N` and feature flag `M`.
