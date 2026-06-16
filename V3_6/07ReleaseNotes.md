# PrimusCentral 0.7 Release Notes

## Overview

This release focuses the available software and hardware choices for a specific workshop context. Up to this point, V3.6 has been about adding options and functionality; 0.7 is about reducing the visible decision space so workshop participants see only the controls and output names that match the materials in front of them.

- This is not about removing any functionality. It is about hiding/focussing features for a specific use
- Full functionality and a path to remapping it should be documented clearly in a way that can be referenced in the future
- NO changes should be made to the firmware unless absolutely necessary. This should all be cosmetic issues handled in the UI

## Workshop UI Profile

0.7 defaults the browser UI to a workshop profile. The sender, API, saved files, and firmware still support the full output type table. The workshop profile only changes what the UI offers by default.

The full UI profile can be restored without changing code by opening Primus Central with:

```text
http://127.0.0.1:8080/?ui=full
```

The profile choice is saved in browser `localStorage` as `primusUiProfile`. To return to the workshop UI, open:

```text
http://127.0.0.1:8080/?ui=workshop
```

The older `?profile=full` and `?profile=workshop` query parameters are also accepted. This is a convenience/obfuscation layer, not a security boundary.

## Reduced Output Types And New Names

Though the long-term goal is to control most NeoPixel-style outputs, this workshop focuses on a smaller kit and should not show participants choices that are unavailable during the workshop.

| Available Output | New Name In UI |
| --- | --- |
| Small Grid | Badge |
| Short Strip | Collar |
| Extra Long Strip | Belt |
| None | None |

Hidden in the default workshop UI:

- Long Strip
- Grid 8x8

These hidden output types remain available through the full UI profile and through the existing API/saved data model.


