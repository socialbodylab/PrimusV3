// ── Puck.js v2 ── Button + Accelerometer → BLE UART ──────────────────
// Sends serial lines over NUS that the Radius picks up and dispatches.
// Format:
//   "btn/press"          – on button down
//   "btn/release"        – on button up
//   "accel x y z"        – accelerometer data while button is held
//   "btn/sleep"          – triple-tap detected, device going to sleep
//
// Triple-tap to sleep: three complete press+release cycles within
// TAP_WINDOW ms puts the Puck into deep sleep. Press once to wake.
// ─────────────────────────────────────────────────────────────────────

var buttonHeld  = false;
var sleeping    = false;
var tapCount    = 0;
var tapTimer    = null;
var TAP_WINDOW  = 800;   // ms between releases to count as a tap sequence
var ACCEL_SCALE = 8192;  // LSM6DS3 ±2g: 1g ≈ 8192 counts

// Use a longer connection interval to save battery (100 ms is fine for buttons)
NRF.setConnectionInterval(100);

function goToSleep() {
  Bluetooth.println("btn/sleep");
  // Brief delay so BLE has time to transmit before radio shuts down
  setTimeout(function() { sleeping = true; NRF.sleep(); }, 100);
}

setWatch(function(e) {
  if (e.state) {
    // ── Button DOWN ──────────────────────────────────────────────────
    if (sleeping) {
      sleeping = false;
      NRF.wake();
      return;  // this press is just a wake — don't fire cue
    }
    buttonHeld = true;
    Bluetooth.println("btn/press");

    Puck.accelOn(12.5);
    Puck.on('accel', function(data) {
      if (!buttonHeld) return;
      var x = (data.acc.x / ACCEL_SCALE).toFixed(3);
      var y = (data.acc.y / ACCEL_SCALE).toFixed(3);
      var z = (data.acc.z / ACCEL_SCALE).toFixed(3);
      Bluetooth.println("accel " + x + " " + y + " " + z);
    });

  } else {
    // ── Button UP ────────────────────────────────────────────────────
    buttonHeld = false;
    Bluetooth.println("btn/release");
    Puck.accelOff();
    Puck.removeAllListeners('accel');

    // ── Triple-tap detection ─────────────────────────────────────────
    tapCount++;
    if (tapTimer) clearTimeout(tapTimer);
    if (tapCount >= 3) {
      tapCount = 0;
      goToSleep();
    } else {
      tapTimer = setTimeout(function() { tapCount = 0; }, TAP_WINDOW);
    }
  }
}, BTN, { repeat: true, edge: "both", debounce: 50 });
