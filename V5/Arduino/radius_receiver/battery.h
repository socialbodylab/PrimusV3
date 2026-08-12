/*
 * battery.h — Radius battery monitoring for the PRS status back-channel
 *
 * V1 (HUZZAH32): LiPo on A13 / GPIO35 via the stock onboard VBAT/2 divider.
 * ADC1 pin, so it is safe to read while WiFi is active.
 *
 * This file is deliberately independent of the Primus tree
 * (V5/Arduino/primusV3_receiver/battery.h). The LiPo percent curve, validity
 * window, and switch-off streak logic are copied from there; the sampling
 * strategy is NOT: Primus averages 8 reads with delay(2) between them
 * (~16 ms blocked), which on Radius would starve the VS1053 FIFO (drains in
 * ~11.6 ms at 44.1k/16/stereo) and cause audible dropouts. Radius takes
 * exactly ONE analogReadMilliVolts() per second and smooths with a 4:1 EMA.
 * No delay() calls, no multi-sample loops — keep it that way.
 */

#ifndef RADIUS_BATTERY_H
#define RADIUS_BATTERY_H

#include "config.h"

enum BatteryPowerMode : uint8_t {
  BATTERY_MODE_BATTERY     = 0,
  BATTERY_MODE_CHARGING    = 1,
  BATTERY_MODE_PLUGGED     = 2,
  BATTERY_MODE_SWITCH_OFF  = 3,
  BATTERY_MODE_FAULT       = 4,
  BATTERY_MODE_UNAVAILABLE = 5,
};

struct RadiusBatteryStatus {
  uint8_t  powerMode;
  uint16_t batteryMv;
  uint8_t  batteryPct;  // 255 = not available
};

static RadiusBatteryStatus radiusBatteryStatus = {
  BATTERY_MODE_UNAVAILABLE, 0, 255
};

#if RADIUS_BATTERY_MONITOR

#ifndef RADIUS_BATTERY_PIN
#define RADIUS_BATTERY_PIN A13   // GPIO35, ADC1, stock VBAT/2 divider
#endif

static uint16_t radiusBatteryEmaMv = 0;
static uint8_t  radiusBatterySwitchOffStreak = 0;

// LiPo percent curve — same shape as Primus battery.h.
static uint8_t batteryPercentFromLiPoMv(uint16_t mv) {
  if (mv >= 4200) return 100;
  if (mv >= 3700) return (uint8_t)(50 + ((mv - 3700) * 50) / 500);
  if (mv >= 3200) return (uint8_t)(((mv - 3200) * 50) / 500);
  return 0;
}

static bool batteryIsValidLiPoMv(uint16_t mv) {
  return mv >= 3200 && mv <= 4200;
}

// Call at 1 Hz from the PRS status tick. One ADC one-shot (tens of µs),
// nothing blocking.
static void radiusBatterySample(bool wifiConnectedFlag) {
  uint16_t rawMv = (uint16_t)(analogReadMilliVolts(RADIUS_BATTERY_PIN) * 2);
  if (radiusBatteryEmaMv == 0) {
    radiusBatteryEmaMv = rawMv;
  } else {
    radiusBatteryEmaMv = (uint16_t)(((uint32_t)radiusBatteryEmaMv * 4 + rawMv) / 5);
  }

  RadiusBatteryStatus status;
  status.powerMode = BATTERY_MODE_UNAVAILABLE;
  status.batteryMv = 0;
  status.batteryPct = 255;

  // Switch-off streak: a rail collapse while WiFi still reports connected
  // means the battery switch was just flipped off (copied from Primus).
  if (wifiConnectedFlag && radiusBatteryEmaMv < 800) {
    if (radiusBatterySwitchOffStreak < 255) radiusBatterySwitchOffStreak++;
  } else {
    radiusBatterySwitchOffStreak = 0;
  }

  if (wifiConnectedFlag && radiusBatterySwitchOffStreak >= 2) {
    status.powerMode = BATTERY_MODE_SWITCH_OFF;
    radiusBatteryStatus = status;
    return;
  }

  if (!batteryIsValidLiPoMv(radiusBatteryEmaMv)) {
    if (wifiConnectedFlag && radiusBatteryEmaMv >= 800 && radiusBatteryEmaMv < 3200) {
      status.powerMode = BATTERY_MODE_FAULT;
    }
    radiusBatteryStatus = status;
    return;
  }

  status.powerMode = BATTERY_MODE_BATTERY;
  status.batteryMv = radiusBatteryEmaMv;
  status.batteryPct = batteryPercentFromLiPoMv(radiusBatteryEmaMv);
  radiusBatteryStatus = status;
}

#else  // !RADIUS_BATTERY_MONITOR

static void radiusBatterySample(bool wifiConnectedFlag) {
  (void)wifiConnectedFlag;
}

#endif  // RADIUS_BATTERY_MONITOR

static bool radiusBatteryIsValid() {
  return radiusBatteryStatus.batteryPct != 255 && radiusBatteryStatus.batteryMv > 0;
}

#endif  // RADIUS_BATTERY_H
