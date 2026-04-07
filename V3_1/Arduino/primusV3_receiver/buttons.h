/*
 * buttons.h — PrimusV3 Button Handler
 * ===========================================
 * D0 (active-LOW):  Cycle TFT info screens
 * D1 (active-HIGH): Toggle test mode
 *
 * D2 / brightness cycling has been removed — brightness is locked to 255.
 */

#ifndef BUTTONS_H
#define BUTTONS_H

#include "config.h"

// =====================================================================
//  State
// =====================================================================
static bool lastBtnState[2] = { false, false };
static const uint8_t btnPins[2] = { BTN_D0, BTN_D1 };

// =====================================================================
//  Actions — set by button presses, consumed by main loop
// =====================================================================
volatile bool btnScreenCycle = false;   // D0 pressed
volatile bool btnTestToggle  = false;   // D1 pressed

// =====================================================================
//  Init
// =====================================================================
void buttonsInit() {
  pinMode(BTN_D0, INPUT_PULLUP);     // D0: active-LOW
  pinMode(BTN_D1, INPUT_PULLDOWN);   // D1: active-HIGH
}

// =====================================================================
//  Read with polarity handling
// =====================================================================
static bool readButton(uint8_t index) {
  bool raw = digitalRead(btnPins[index]);
  // D0 is active-LOW → invert; D1 is active-HIGH → use as-is
  return (index == 0) ? !raw : raw;
}

// =====================================================================
//  Poll — call once per loop iteration
// =====================================================================
void buttonsPoll() {
  for (uint8_t i = 0; i < 2; i++) {
    bool pressed = readButton(i);
    if (pressed && !lastBtnState[i]) {
      if (i == 0) btnScreenCycle = true;
      else        btnTestToggle  = true;
    }
    lastBtnState[i] = pressed;
  }
}

#endif // BUTTONS_H
