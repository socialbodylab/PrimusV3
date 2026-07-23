/*
 * telemetry.h — UDP 6455 back-channel (PFP + PTR) to Radius Central sender
 */

#ifndef TELEMETRY_H
#define TELEMETRY_H

#include "config.h"

void sendTrackTelemetry(uint8_t state, const char* filename);  // PTR — retained (fallback)
void sendFpsTelemetry(uint16_t pktRate);
void sendAudioStatus(uint8_t status, const char* filename);    // 0x8302 — primary, event-driven
void telemetryHeartbeat();

#endif // TELEMETRY_H
