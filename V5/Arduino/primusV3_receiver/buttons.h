/*
 * buttons.h — PrimusV3 Button Handler
 * ===========================================
 * D0 (active-LOW):  Cycle TFT info screens
 * D1 (active-HIGH): Short = action, Long (>600ms) = edit focus cycle (pg3)
 */

#ifndef BUTTONS_H
#define BUTTONS_H

#include "config.h"

#if BOARD_HAS_BUTTONS

static bool lastBtnState[2] = { false, false };
static const uint8_t btnPins[2] = { BTN_D0, BTN_D1 };

#ifndef BTN_LONG_PRESS_MS
#define BTN_LONG_PRESS_MS 600
#endif

volatile bool btnScreenCycle = false;
volatile bool btnTestToggle  = false;
volatile bool btnEditFocusCycle = false;

static bool btn1Held = false;
static unsigned long btn1PressStart = 0;
static bool btn1LongFired = false;

void buttonsInit() {
  pinMode(BTN_D0, INPUT_PULLUP);
  pinMode(BTN_D1, INPUT_PULLDOWN);
}

static bool readButton(uint8_t index) {
  bool raw = digitalRead(btnPins[index]);
  return (index == 0) ? !raw : raw;
}

void buttonsPoll() {
  for (uint8_t i = 0; i < 2; i++) {
    bool pressed = readButton(i);

    if (i == 1) {
      if (pressed && !lastBtnState[i]) {
        btn1Held = true;
        btn1PressStart = millis();
        btn1LongFired = false;
      } else if (pressed && btn1Held && !btn1LongFired &&
                 (millis() - btn1PressStart >= BTN_LONG_PRESS_MS)) {
        btn1LongFired = true;
        btnEditFocusCycle = true;
      } else if (!pressed && lastBtnState[i]) {
        if (btn1Held && !btn1LongFired) {
          btnTestToggle = true;
        }
        btn1Held = false;
        btn1LongFired = false;
      }
      lastBtnState[i] = pressed;
      continue;
    }

    if (pressed && !lastBtnState[i]) {
      btnScreenCycle = true;
    }
    lastBtnState[i] = pressed;
  }
}

#else

volatile bool btnScreenCycle = false;
volatile bool btnTestToggle  = false;
volatile bool btnEditFocusCycle = false;

void buttonsInit() {}
void buttonsPoll() {}

#endif

#endif // BUTTONS_H
