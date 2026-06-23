// ── Puck.js v2 ── Button + Accelerometer → BLE UART ──────────────────
// Sends serial lines that the host bridge will convert to OSC messages.
// Format:
//   "btn/press"          – on button down
//   "btn/release"        – on button up
//   "accel x y z"        – accelerometer data while button is held
// ─────────────────────────────────────────────────────────────────────

var buttonHeld = false;

// Scale factor: LSM6DS3 at ±2g range returns raw counts where
// 1g ≈ 8192 counts. Divide to get float g values.
var ACCEL_SCALE = 8192;

// Start watching the button for both press and release
setWatch(function(e) {
  if (e.state) {
    // ── Button DOWN ──────────────────────────────────────────────────
    buttonHeld = true;
    Bluetooth.println("btn/press");

    // Turn on accelerometer at 12.5 Hz
    Puck.accelOn(12.5);

    // Stream accelerometer data while button is held
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

    // Stop accelerometer and remove listener
    Puck.accelOff();
    Puck.removeAllListeners('accel');
  }
}, BTN, { repeat: true, edge: "both", debounce: 50 });