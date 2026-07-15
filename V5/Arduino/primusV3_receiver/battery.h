/*
 * battery.h — Battery monitoring for unified status telemetry
 *
 * V1: LiPo on A13 (HUZZAH32 onboard divider, no VBUS sense).
 * V3: 5V buck/boost rail on A4 via 100k/100k divider (×2 scale).
 */

#ifndef BATTERY_H
#define BATTERY_H

#include "config.h"

enum BatteryPowerMode : uint8_t {
  BATTERY_MODE_BATTERY = 0,
  BATTERY_MODE_CHARGING = 1,
  BATTERY_MODE_PLUGGED = 2,
  BATTERY_MODE_SWITCH_OFF = 3,
  BATTERY_MODE_FAULT = 4,
  BATTERY_MODE_UNAVAILABLE = 5,
};

struct BatteryStatus {
  uint8_t powerMode;
  uint16_t batteryMv;
  uint8_t batteryPct;
};

#if BOARD_BATTERY_MONITOR

#include <WiFi.h>

#ifndef BOARD_BATTERY_PIN
#define BOARD_BATTERY_PIN A13
#endif

#ifndef BATTERY_REPORT_INTERVAL_MS
#define BATTERY_REPORT_INTERVAL_MS 5000
#endif

static uint16_t batterySmoothedMv = 0;
static uint8_t batterySwitchOffStreak = 0;
static unsigned long lastBatteryReportMs = 0;
static BatteryStatus batteryLastStatus = {
  BATTERY_MODE_UNAVAILABLE, 0, 255
};
static char batteryTimeRemainingText[12] = "---";

#if BOARD_BATTERY_TYPE_RAIL
static unsigned long batteryTimeSampleMs[10] = {};
static uint16_t batteryTimeSampleMv[10] = {};
static uint8_t batteryTimeSampleCount = 0;
static uint8_t batteryTimeSampleIndex = 0;
static unsigned long lastBatteryTimeSampleMs = 0;
#endif

static uint16_t batteryScaleAdcMv(uint16_t adcMv) {
  return (uint16_t)((uint32_t)adcMv * BOARD_BATTERY_ADC_SCALE_NUM / BOARD_BATTERY_ADC_SCALE_DEN);
}

static uint16_t batteryReadRawMv() {
  const uint8_t samples = 8;
  uint16_t readings[samples];
  uint16_t minVal = 65535;
  uint16_t maxVal = 0;
  uint32_t sum = 0;
  uint8_t used = 0;

  for (uint8_t i = 0; i < samples; i++) {
    uint16_t adcMv = (uint16_t)analogReadMilliVolts(BOARD_BATTERY_PIN);
    uint16_t scaledMv = batteryScaleAdcMv(adcMv);
    readings[i] = scaledMv;
    if (scaledMv < minVal) minVal = scaledMv;
    if (scaledMv > maxVal) maxVal = scaledMv;
    delay(2);
  }

  for (uint8_t i = 0; i < samples; i++) {
    if (readings[i] == minVal) {
      minVal = 65535;
      continue;
    }
    if (readings[i] == maxVal) {
      maxVal = 0;
      continue;
    }
    sum += readings[i];
    used++;
  }

  if (used == 0) {
    return readings[0];
  }
  return (uint16_t)(sum / used);
}

static uint8_t batteryPercentFromLiPoMv(uint16_t mv) {
  if (mv >= 4200) return 100;
  if (mv >= 3700) return (uint8_t)(50 + ((mv - 3700) * 50) / 500);
  if (mv >= 3200) return (uint8_t)(((mv - 3200) * 50) / 500);
  return 0;
}

static uint8_t batteryPercentFromRailMv(uint16_t mv) {
  if (mv >= BOARD_BATTERY_MV_REGULATED) return 100;
  if (mv <= BOARD_BATTERY_MV_EMPTY) return 0;
  if (mv >= BOARD_BATTERY_MV_FULL) {
    uint16_t span = BOARD_BATTERY_MV_REGULATED - BOARD_BATTERY_MV_FULL;
    if (span == 0) return 100;
    return (uint8_t)(90 + ((mv - BOARD_BATTERY_MV_FULL) * 10) / span);
  }
  return (uint8_t)(((mv - BOARD_BATTERY_MV_EMPTY) * 99) /
                     (BOARD_BATTERY_MV_REGULATED - BOARD_BATTERY_MV_EMPTY));
}

static bool batteryIsValidLiPoMv(uint16_t mv) {
  return mv >= 3200 && mv <= 4200;
}

static bool batteryIsValidRailMv(uint16_t mv) {
  return mv >= (BOARD_BATTERY_MV_EMPTY - 200) && mv <= (BOARD_BATTERY_MV_FULL + 300);
}

#if BOARD_BATTERY_TYPE_RAIL
static void batteryUpdateTimeEstimate(uint16_t railMv, unsigned long now) {
  if (now - lastBatteryTimeSampleMs < 30000UL) {
    return;
  }
  lastBatteryTimeSampleMs = now;

  batteryTimeSampleMs[batteryTimeSampleIndex] = now;
  batteryTimeSampleMv[batteryTimeSampleIndex] = railMv;
  batteryTimeSampleIndex = (batteryTimeSampleIndex + 1) % 10;
  if (batteryTimeSampleCount < 10) batteryTimeSampleCount++;

  if (railMv >= BOARD_BATTERY_MV_REGULATED) {
    strncpy(batteryTimeRemainingText, "---", sizeof(batteryTimeRemainingText));
    batteryTimeRemainingText[sizeof(batteryTimeRemainingText) - 1] = '\0';
    return;
  }

  if (batteryTimeSampleCount < 2) {
    strncpy(batteryTimeRemainingText, "---", sizeof(batteryTimeRemainingText));
    batteryTimeRemainingText[sizeof(batteryTimeRemainingText) - 1] = '\0';
    return;
  }

  uint8_t oldest = (batteryTimeSampleIndex + 10 - batteryTimeSampleCount) % 10;
  uint8_t newest = (batteryTimeSampleIndex + 9) % 10;
  unsigned long dtMs = batteryTimeSampleMs[newest] - batteryTimeSampleMs[oldest];
  if (dtMs < 60000UL) {
    return;
  }

  int32_t dMv = (int32_t)batteryTimeSampleMv[newest] - (int32_t)batteryTimeSampleMv[oldest];
  if (dMv >= -3) {
    strncpy(batteryTimeRemainingText, "---", sizeof(batteryTimeRemainingText));
    batteryTimeRemainingText[sizeof(batteryTimeRemainingText) - 1] = '\0';
    return;
  }

  float mvPerMin = (float)dMv * 60000.0f / (float)dtMs;
  float remainingMin = ((float)railMv - (float)BOARD_BATTERY_MV_EMPTY) / (-mvPerMin);
  if (remainingMin < 1.0f) {
    strncpy(batteryTimeRemainingText, "<5m", sizeof(batteryTimeRemainingText));
  } else if (remainingMin < 60.0f) {
    snprintf(batteryTimeRemainingText, sizeof(batteryTimeRemainingText), "~%um", (unsigned)(remainingMin + 0.5f));
  } else {
    unsigned hours = (unsigned)(remainingMin / 60.0f);
    unsigned mins = (unsigned)(remainingMin - hours * 60.0f + 0.5f);
    if (mins >= 60) { hours++; mins = 0; }
    snprintf(batteryTimeRemainingText, sizeof(batteryTimeRemainingText), "~%uh%02u", hours, mins);
  }
  batteryTimeRemainingText[sizeof(batteryTimeRemainingText) - 1] = '\0';
}
#endif

static BatteryStatus batteryEvaluate(bool wifiConnected) {
  BatteryStatus status;
  status.powerMode = BATTERY_MODE_UNAVAILABLE;
  status.batteryMv = 0;
  status.batteryPct = 255;

  uint16_t rawMv = batteryReadRawMv();
  if (batterySmoothedMv == 0) {
    batterySmoothedMv = rawMv;
  } else {
    batterySmoothedMv = (uint16_t)((batterySmoothedMv * 4 + rawMv) / 5);
  }

#if BOARD_BATTERY_TYPE_RAIL
  batteryUpdateTimeEstimate(batterySmoothedMv, millis());

  if (!batteryIsValidRailMv(batterySmoothedMv)) {
    if (batterySmoothedMv < BOARD_BATTERY_MV_EMPTY) {
      status.powerMode = BATTERY_MODE_FAULT;
    }
    return status;
  }

  status.powerMode = BATTERY_MODE_BATTERY;
  status.batteryMv = batterySmoothedMv;
  status.batteryPct = batteryPercentFromRailMv(batterySmoothedMv);
  return status;
#else
  if (wifiConnected && batterySmoothedMv < 800) {
    batterySwitchOffStreak++;
  } else {
    batterySwitchOffStreak = 0;
  }

  if (wifiConnected && batterySwitchOffStreak >= 2) {
    status.powerMode = BATTERY_MODE_SWITCH_OFF;
    return status;
  }

  if (wifiConnected && !batteryIsValidLiPoMv(batterySmoothedMv)) {
    if (batterySmoothedMv >= 800 && batterySmoothedMv < 3200) {
      status.powerMode = BATTERY_MODE_FAULT;
      return status;
    }
    status.powerMode = BATTERY_MODE_UNAVAILABLE;
    return status;
  }

  if (!batteryIsValidLiPoMv(batterySmoothedMv)) {
    status.powerMode = BATTERY_MODE_UNAVAILABLE;
    return status;
  }

  status.powerMode = BATTERY_MODE_BATTERY;
  status.batteryMv = batterySmoothedMv;
  status.batteryPct = batteryPercentFromLiPoMv(batterySmoothedMv);
  return status;
#endif
}

static const BatteryStatus& batteryLastDisplayStatus() {
  return batteryLastStatus;
}

static const char* batteryTimeRemainingLabel() {
  return batteryTimeRemainingText;
}

static void batteryStatusTick(bool wifiConnectedFlag, bool diagnosticsEnabled) {
  unsigned long now = millis();
  if (now - lastBatteryReportMs < BATTERY_REPORT_INTERVAL_MS) {
    return;
  }
  lastBatteryReportMs = now;

  BatteryStatus status = batteryEvaluate(wifiConnectedFlag);
  batteryLastStatus = status;
  if (diagnosticsEnabled) {
    Serial.print("Battery mv=");
    Serial.print(status.batteryMv);
    Serial.print(" pct=");
    Serial.println(status.batteryPct == 255 ? 0 : status.batteryPct);
  }
}

#else

static BatteryStatus batteryLastStatus = {
  BATTERY_MODE_UNAVAILABLE, 0, 255
};

static const BatteryStatus& batteryLastDisplayStatus() {
  return batteryLastStatus;
}

static const char* batteryTimeRemainingLabel() {
  return "---";
}

static void batteryStatusTick(bool wifiConnectedFlag, bool diagnosticsEnabled) {
  (void)wifiConnectedFlag;
  (void)diagnosticsEnabled;
}

#endif // BOARD_BATTERY_MONITOR

#endif // BATTERY_H
