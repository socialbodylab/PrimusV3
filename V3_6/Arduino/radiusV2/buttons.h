/*
 * buttons.h — PrimusV3 Button Handler
 * ===========================================
 * D0 (active-LOW):  Cycle TFT info screens
 * D1 (active-HIGH): Context action — varies by screen
 * D2 (active-HIGH): Context action — varies by screen (ESP32-S3 only)
 */

#ifndef BUTTONS_H
#define BUTTONS_H

#include "config.h"

// =====================================================================
//  State
// =====================================================================
static bool lastBtnState[3] = { false, false, false };
static const uint8_t btnPins[3] = { BTN_D0, BTN_D1, BTN_D2 };

// =====================================================================
//  Actions — set by button presses, consumed by main loop
// =====================================================================
volatile bool btnScreenCycle = false;   // D0 pressed
volatile bool btnD1          = false;   // D1 pressed — context action
volatile bool btnD2          = false;   // D2 pressed — context action

// =====================================================================
//  Init
// =====================================================================
void buttonsInit() {
  pinMode(BTN_D0, INPUT_PULLUP);     // D0: active-LOW
#if TARGET_BOARD != BOARD_FEATHER_ESP32
  // On HUZZAH32, BTN_D1=GPIO14 conflicts with MM_SDCS_PIN — do not init
  pinMode(BTN_D1, INPUT_PULLDOWN);   // D1: active-HIGH
  pinMode(BTN_D2, INPUT_PULLDOWN);   // D2: active-HIGH
#endif
}

// =====================================================================
//  Read with polarity handling
// =====================================================================
static bool readButton(uint8_t index) {
  bool raw = digitalRead(btnPins[index]);
  // D0 is active-LOW → invert; D1/D2 are active-HIGH → use as-is
  return (index == 0) ? !raw : raw;
}

// =====================================================================
//  Poll — call once per loop iteration
// =====================================================================
void buttonsPoll() {
#if TARGET_BOARD == BOARD_FEATHER_ESP32
  // HUZZAH32: only poll D0 — BTN_D1/BTN_D2 conflict with SD CS and have no physical button
  const uint8_t btnCount = 1;
#else
  const uint8_t btnCount = 3;
#endif
  for (uint8_t i = 0; i < btnCount; i++) {
    bool pressed = readButton(i);
    if (pressed && !lastBtnState[i]) {
      if      (i == 0) btnScreenCycle = true;
      else if (i == 1) btnD1          = true;
      else             btnD2          = true;
    }
    lastBtnState[i] = pressed;
  }
}

#endif // BUTTONS_H
