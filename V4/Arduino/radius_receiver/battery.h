/*
 * battery.h — V1 LiPo monitoring and PBT telemetry (UDP 6455)
 *
 * HUZZAH32 has no VBUS GPIO, so only voltage/percent are reported.
 */

#ifndef BATTERY_H
#define BATTERY_H

#include "config.h"

#if BOARD_BATTERY_MONITOR

#include <WiFi.h>
#include <WiFiUdp.h>

#ifndef BOARD_BATTERY_PIN
#define BOARD_BATTERY_PIN A13
#endif

#ifndef BATTERY_REPORT_INTERVAL_MS
#define BATTERY_REPORT_INTERVAL_MS 5000
#endif

static const uint8_t BATTERY_MAGIC[3] = { 'P', 'B', 'T' };

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

static uint16_t batterySmoothedMv = 0;
static uint8_t batterySwitchOffStreak = 0;
static unsigned long lastBatteryReportMs = 0;

static uint16_t batteryReadRawMv() {
  const uint8_t samples = 8;
  uint16_t readings[samples];
  uint16_t minVal = 65535;
  uint16_t maxVal = 0;
  uint32_t sum = 0;
  uint8_t used = 0;

  for (uint8_t i = 0; i < samples; i++) {
    uint16_t halfMv = (uint16_t)analogReadMilliVolts(BOARD_BATTERY_PIN);
    uint16_t fullMv = (uint16_t)(halfMv * 2U);
    readings[i] = fullMv;
    if (fullMv < minVal) minVal = fullMv;
    if (fullMv > maxVal) maxVal = fullMv;
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

static uint8_t batteryPercentFromMv(uint16_t mv) {
  if (mv >= 4200) return 100;
  if (mv >= 3700) return (uint8_t)(50 + ((mv - 3700) * 50) / 500);
  if (mv >= 3200) return (uint8_t)(((mv - 3200) * 50) / 500);
  return 0;
}

static bool batteryIsValidLiPoMv(uint16_t mv) {
  return mv >= 3200 && mv <= 4200;
}

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
  status.batteryPct = batteryPercentFromMv(batterySmoothedMv);
  return status;
}

static void sendBatteryTelemetry(WiFiUDP& udp, IPAddress senderIP, bool senderKnownFlag,
                                 const BatteryStatus& status) {
  if (!senderKnownFlag || WiFi.status() != WL_CONNECTED) return;

  uint8_t buf[9];
  buf[0] = BATTERY_MAGIC[0];
  buf[1] = BATTERY_MAGIC[1];
  buf[2] = BATTERY_MAGIC[2];
  buf[3] = status.powerMode;
  buf[4] = (status.batteryMv >> 8) & 0xFF;
  buf[5] = status.batteryMv & 0xFF;
  buf[6] = status.batteryPct;
  buf[7] = FIRMWARE_VERSION_L;
  buf[8] = FIRMWARE_VERSION_H;

  udp.beginPacket(senderIP, FPS_REPORT_PORT);
  udp.write(buf, sizeof(buf));
  udp.endPacket();
}

static void batteryTelemetryTick(WiFiUDP& udp, IPAddress senderIP, bool senderKnownFlag,
                                 bool wifiConnectedFlag) {
  unsigned long now = millis();
  if (now - lastBatteryReportMs < BATTERY_REPORT_INTERVAL_MS) {
    return;
  }
  lastBatteryReportMs = now;

  BatteryStatus status = batteryEvaluate(wifiConnectedFlag);
  sendBatteryTelemetry(udp, senderIP, senderKnownFlag, status);

  Serial.print("Battery mv=");
  Serial.print(status.batteryMv);
  Serial.print(" pct=");
  Serial.println(status.batteryPct == 255 ? 0 : status.batteryPct);
}

#endif // BOARD_BATTERY_MONITOR

#endif // BATTERY_H
