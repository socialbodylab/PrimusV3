/*
 * LED Costume Controller for ESP32 Feather v2
 * ------------------------------------------
 *
 * This code receives Art-Net data over WiFi and controls two NeoPixel LED strips:
 * 1. A badge (8x4 grid, 32 LEDs)
 * 2. A collar (30 LEDs)
 *
 * The first byte of incoming Art-Net data controls the brightness (0-255).
 * The remaining bytes contain RGB values for each LED.
 *
 * Hardware Requirements:
 * - Adafruit ESP32 Feather V2
 * - NeoPixel strips (one for badge, one for collar)
 * - USB power or LiPo battery
 *
 * Libraries Required:
 * - ArtnetWifi: https://github.com/rstephan/ArtnetWifi
 * - Adafruit_NeoPixel: Available in Arduino Library Manager
 *
 * Settings To Change:
 * - Edit WiFiSettings.h to match your WiFi network
 * - Adjust LED pin numbers and counts if your hardware differs
 *
 */

#include <ArtnetWifi.h>        // Library for receiving Art-Net data over WiFi
#include <Adafruit_NeoPixel.h> // Library for controlling NeoPixel LEDs
#include "WiFiSettings.h"      // Contains WiFi credentials and network settings

// ==== PIN DEFINITIONS ====
// NeoPixel data pins - change these to match your wiring
const byte BADGE_DATA_PIN = 32;  // Data pin for the badge LEDs
const byte COLLAR_DATA_PIN = 12; // Data pin for the collar LEDs

// Onboard NeoPixel on ESP32 Feather V2
const byte ONBOARD_NEOPIXEL_PIN = 0;      // Pin for the onboard NeoPixel
const byte NEOPIXEL_POWER_PIN = 2;        // Pin that powers the NeoPixel

// ==== LED CONFIGURATION ====
// Number of LEDs in each strip
const int BADGE_LED_COUNT = 32;           // 8x4 grid of LEDs for the badge
const int COLLAR_LED_COUNT = 30;          // Number of LEDs in the collar

// Default brightness if not specified in Art-Net data
const int DEFAULT_BRIGHTNESS = 50;        // Default brightness (0-255)
int currentBrightness = DEFAULT_BRIGHTNESS; // Current brightness value

// ==== NEOPIXEL OBJECTS ====
// Initialize NeoPixel objects for each LED strip
Adafruit_NeoPixel badge = Adafruit_NeoPixel(BADGE_LED_COUNT, BADGE_DATA_PIN, NEO_GRB + NEO_KHZ800);
Adafruit_NeoPixel collar = Adafruit_NeoPixel(COLLAR_LED_COUNT, COLLAR_DATA_PIN, NEO_GRB + NEO_KHZ800);
Adafruit_NeoPixel statusPixel = Adafruit_NeoPixel(1, ONBOARD_NEOPIXEL_PIN, NEO_GRB + NEO_KHZ800);

// ==== ART-NET CONFIGURATION ====
// Initialize Art-Net object
ArtnetWifi artnet;

// ==== DATA BUFFERS ====
// Buffers for storing LED color data before updating the strips
uint8_t badgeBuffer[BADGE_LED_COUNT * 3];   // 3 bytes per LED (R,G,B)
uint8_t collarBuffer[COLLAR_LED_COUNT * 3]; // 3 bytes per LED (R,G,B)
bool dataReady = false;                     // Flag indicating new data is ready
bool brightnessChanged = false;             // Flag indicating brightness change

// Timing control for LED updates
const unsigned long MIN_UPDATE_INTERVAL = 16;  // Minimum time between LED updates (approx 60fps max)
unsigned long lastLEDUpdateTime = 0;           // Last time LEDs were updated

// ==== BATTERY MONITORING ====
#define VBATPIN A13                         // Pin for battery voltage monitoring
const unsigned long BATTERY_CHECK_INTERVAL = 10000; // Check battery every 10 seconds
unsigned long lastBatteryCheck = 0;         // Last time battery was checked

// ==== FPS CALCULATION ====
unsigned long frameCount = 0;               // Count of LED frame updates
unsigned long packetCount = 0;              // Count of Art-Net packets received
unsigned long lastFpsTime = 0;              // Last time FPS was calculated
const unsigned long FPS_INTERVAL = 1000;    // Update FPS every second

// ==== WIFI CONNECTION MONITORING ====
unsigned long lastPacketTime = 0;           // Last time a packet was received
const unsigned long CONNECTION_TIMEOUT = 10000; // 10 seconds without packets triggers reconnection
const unsigned long RECONNECT_INTERVAL = 5000;  // Try to reconnect every 5 seconds
unsigned long lastReconnectAttempt = 0;     // Last reconnection attempt time
bool wifiConnected = false;                 // WiFi connection status

// ==== STATUS LED SETTINGS ====
const unsigned long CONNECTION_LED_DURATION = 30000; // Show green for 30 seconds after connecting
unsigned long connectionSuccessTime = 0;    // When the connection was successful
bool connectionLedActive = false;           // Whether the connection LED is active
const int CONNECTION_BLINK_INTERVAL = 500;  // Blink interval for disconnected state
unsigned long lastBlinkTime = 0;            // Last time the LED was blinked

// ==== FUNCTION PROTOTYPES ====
void onDmxFrame(uint16_t universe, uint16_t length, uint8_t sequence, uint8_t* data);
bool connectWifi(void);
void checkWifiConnection();
float checkBatteryLevel();
void updateStatusLED();

/*
 * setup() - Initializes the hardware and network connection
 * This function runs once when the device starts up
 */
void setup() {
  // Initialize serial communication for debugging
  Serial.begin(115200);
  Serial.println("\n\n=== LED Costume Controller ===");

  // Initialize the onboard NeoPixel power pin
  pinMode(NEOPIXEL_POWER_PIN, OUTPUT);
  digitalWrite(NEOPIXEL_POWER_PIN, HIGH);  // Turn on NeoPixel power

  // For better performance, set the ESP32 CPU frequency to maximum
  setCpuFrequencyMhz(240);

  // Initialize all NeoPixels
  badge.begin();
  collar.begin();
  statusPixel.begin();

  // Set initial brightness for LED strips
  badge.setBrightness(currentBrightness);
  collar.setBrightness(currentBrightness);
  statusPixel.setBrightness(50);  // Set status LED to moderate brightness

  // Initialize NeoPixel to show starting up (blue)
  statusPixel.setPixelColor(0, statusPixel.Color(0, 0, 50));
  statusPixel.show();

  // Set WiFi to high power mode for better connection reliability
  WiFi.setSleep(false);

  // Connect to WiFi
  Serial.println("Connecting to WiFi...");
  wifiConnected = connectWifi();

  // Initialize Art-Net
  Serial.println("Initializing Art-Net...");
  artnet.begin();

  // Set the callback function for receiving Art-Net data
  artnet.setArtDmxCallback(onDmxFrame);

  // Initialize timing variables
  lastFpsTime = millis();
  lastPacketTime = millis();
  lastBatteryCheck = millis();
  lastBlinkTime = millis();
  lastLEDUpdateTime = millis();

  // Initial battery level check
  float batteryLevel = checkBatteryLevel();
  Serial.print("Initial Battery Level: ");
  Serial.print(batteryLevel);
  Serial.println(" V");

  // Setup is complete
  Serial.println("Setup complete. Waiting for Art-Net data...");
}

/*
 * loop() - Main program loop that runs continuously
 * Handles network communication, LED updates, and system monitoring
 */
void loop() {
  // Get current time
  unsigned long currentTime = millis();

  // Check WiFi connection and attempt to reconnect if necessary
  checkWifiConnection();

  // Update status LED based on connection state
  updateStatusLED();

  // Process incoming Art-Net data
  artnet.read();

  // Check battery level periodically
  if (currentTime - lastBatteryCheck >= BATTERY_CHECK_INTERVAL) {
    float batteryLevel = checkBatteryLevel();
    Serial.print("Battery Level: ");
    Serial.print(batteryLevel);
    Serial.println(" V");
    lastBatteryCheck = currentTime;
  }

  // Calculate and display FPS every second
  if (currentTime - lastFpsTime >= FPS_INTERVAL) {
    float framesFps = frameCount * 1000.0 / (currentTime - lastFpsTime);
    float packetsFps = packetCount * 1000.0 / (currentTime - lastFpsTime);

    Serial.print("FPS - LED Updates: ");
    Serial.print(framesFps, 1);
    Serial.print(", Art-Net Packets: ");
    Serial.print(packetsFps, 1);

    // Add more system info
    Serial.print(", Free Heap: ");
    Serial.print(ESP.getFreeHeap());
    Serial.print(" bytes, WiFi RSSI: ");
    Serial.print(WiFi.RSSI());
    Serial.print(" dBm, Brightness: ");
    Serial.println(currentBrightness);

    // Reset counters
    frameCount = 0;
    packetCount = 0;
    lastFpsTime = currentTime;
  }

  // If new data has arrived, update the LEDs
  if (dataReady) {
    // If brightness has changed, update it before setting pixel colors
    if (brightnessChanged) {
      badge.setBrightness(currentBrightness);
      collar.setBrightness(currentBrightness);
      brightnessChanged = false;
    }

    // Only update LEDs that have changed from their previous state
    // This reduces SPI traffic and can help with flickering
    static uint32_t lastBadgeColors[BADGE_LED_COUNT] = {0};
    static uint32_t lastCollarColors[COLLAR_LED_COUNT] = {0};

    // Begin with NeoPixel updates without showing immediately
    bool badgeUpdated = false;
    bool collarUpdated = false;

    // Update badge LEDs from buffer, but only if colors have changed
    for (int i = 0; i < BADGE_LED_COUNT; i++) {
      uint32_t newColor = badge.Color(
        badgeBuffer[i * 3],      // Red
        badgeBuffer[i * 3 + 1],  // Green
        badgeBuffer[i * 3 + 2]   // Blue
      );

      // Only update if the color has changed to reduce SPI traffic
      if (newColor != lastBadgeColors[i]) {
        badge.setPixelColor(i, newColor);
        lastBadgeColors[i] = newColor;
        badgeUpdated = true;
      }
    }

    // Update collar LEDs from buffer, but only if colors have changed
    for (int i = 0; i < COLLAR_LED_COUNT; i++) {
      uint32_t newColor = collar.Color(
        collarBuffer[i * 3],      // Red
        collarBuffer[i * 3 + 1],  // Green
        collarBuffer[i * 3 + 2]   // Blue
      );

      // Only update if the color has changed
      if (newColor != lastCollarColors[i]) {
        collar.setPixelColor(i, newColor);
        lastCollarColors[i] = newColor;
        collarUpdated = true;
      }
    }

    // Only call show() if we actually updated pixel values
    // This reduces unnecessary SPI traffic that might cause flickering
    if (badgeUpdated) {
      badge.show();
    }

    if (collarUpdated) {
      collar.show();
    }

    // Increment frame counter for FPS calculation
    frameCount++;

    // Reset the data flag
    dataReady = false;
  }
}

/*
 * updateStatusLED() - Updates the onboard NeoPixel based on connection status
 * Green: Connected to WiFi (shown for 30 seconds after connection)
 * Blinking Red: Connection lost or reconnecting
 */
void updateStatusLED() {
  unsigned long currentTime = millis();

  // If connected and within the 30 second window
  if (wifiConnected && (currentTime - connectionSuccessTime < CONNECTION_LED_DURATION)) {
    // Solid green indicates successful connection
    if (!connectionLedActive) {
      statusPixel.setPixelColor(0, statusPixel.Color(0, 50, 0)); // Green
      statusPixel.show();
      connectionLedActive = true;
    }
  }
  // If disconnected or connection timed out, blink red
  else if (!wifiConnected) {
    // Blink red to indicate connection issue
    if (currentTime - lastBlinkTime >= CONNECTION_BLINK_INTERVAL) {
      lastBlinkTime = currentTime;

      // Toggle the LED state
      if (connectionLedActive) {
        statusPixel.setPixelColor(0, statusPixel.Color(0, 0, 0)); // Off
      } else {
        statusPixel.setPixelColor(0, statusPixel.Color(50, 0, 0)); // Red
      }
      statusPixel.show();
      connectionLedActive = !connectionLedActive;
    }
  }
  // If connected but outside the 30 second window
  else {
    // Turn off the status LED to save power
    if (connectionLedActive) {
      statusPixel.setPixelColor(0, statusPixel.Color(0, 0, 0)); // Off
      statusPixel.show();
      connectionLedActive = false;
    }
  }
}

/*
 * checkBatteryLevel() - Reads the battery voltage
 * Returns: Battery voltage in volts
 */
float checkBatteryLevel() {
  float measuredvbat = analogReadMilliVolts(VBATPIN);
  measuredvbat *= 2;    // We divided by 2 with a voltage divider, so multiply back
  measuredvbat /= 1000; // Convert to volts
  return measuredvbat;
}

/*
 * checkWifiConnection() - Monitors WiFi connection and attempts to reconnect if needed
 * Checks if packets have been received recently and reconnects if the connection is lost
 */
void checkWifiConnection() {
  unsigned long currentTime = millis();

  // Check if we've received packets recently
  if (currentTime - lastPacketTime > CONNECTION_TIMEOUT) {
    // No packets received for a while, check WiFi status
    if (WiFi.status() != WL_CONNECTED) {
      wifiConnected = false;

      // Only attempt to reconnect at the specified interval
      if (currentTime - lastReconnectAttempt > RECONNECT_INTERVAL) {
        Serial.println("Connection lost. Attempting to reconnect...");
        lastReconnectAttempt = currentTime;
        wifiConnected = connectWifi();

        // Reinitialize ArtNet if WiFi reconnection was successful
        if (wifiConnected) {
          artnet.begin();
          Serial.println("Art-Net reinitialized after reconnection.");

          // Set the time of successful reconnection
          connectionSuccessTime = currentTime;
        }
      }
    }
  }
}

/*
 * connectWifi() - Attempts to connect to the WiFi network
 * Returns: true if connected successfully, false if connection failed
 */
bool connectWifi() {
  bool state = true;
  int attemptCount = 0;
  const int MAX_ATTEMPTS = 20;

  // Begin WiFi connection
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  WiFi.config(LOCAL_IP, GATEWAY, SUBNET);
  Serial.println("");
  Serial.println("Connecting to WiFi");

  // Wait for connection with timeout
  Serial.print("Connecting");
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
    if (attemptCount > MAX_ATTEMPTS) {
      state = false;
      break;
    }
    attemptCount++;
  }

  // Report connection result
  if (state) {
    Serial.println("");
    Serial.print("Connected to ");
    Serial.println(WIFI_SSID);
    Serial.print("IP address: ");
    Serial.println(WiFi.localIP());

    // Turn on built-in LED when connected
    pinMode(LED_BUILTIN, OUTPUT);
    digitalWrite(LED_BUILTIN, HIGH);

    // Set the time of successful connection
    connectionSuccessTime = millis();
  } else {
    Serial.println("");
    Serial.println("Connection failed.");
    digitalWrite(LED_BUILTIN, LOW); // Turn off LED when disconnected
  }

  return state;
}

/*
 * onDmxFrame() - Callback function called when Art-Net data is received
 *
 * Parameters:
 * - universe: Art-Net universe (should match our configured universe)
 * - length: Length of the data packet in bytes
 * - sequence: Sequence number of the packet
 * - data: Pointer to the received data
 */
void onDmxFrame(uint16_t universe, uint16_t length, uint8_t sequence, uint8_t* data) {
  unsigned long currentTime = millis();

  // Update last packet time
  lastPacketTime = currentTime;

  // Rate limit updates to prevent flickering
  // Only process packets if minimum interval has passed since last update
  if (currentTime - lastLEDUpdateTime < MIN_UPDATE_INTERVAL) {
    // Skip this update but still count the packet for stats
    packetCount++;
    return;
  }

  // Check if we have at least one byte (for brightness)
  if (length > 0) {
    // First byte is used for brightness control
    int newBrightness = data[0]; // Get brightness from first byte

    // Check if brightness has changed - use a threshold to reduce unnecessary updates
    // Only update brightness if it has changed by more than 2 (reduces jitter)
    if (abs(newBrightness - currentBrightness) > 2) {
      currentBrightness = newBrightness;
      brightnessChanged = true;
    }

    // Process badge data (offset by 1 for the brightness byte)
    int badgeDataStart = 1; // Start after brightness byte
    int maxBadgeBytes = min((int)length - 1, BADGE_LED_COUNT * 3);
    for (int i = 0; i < maxBadgeBytes; i++) {
      badgeBuffer[i] = data[badgeDataStart + i];
    }

    // Process collar data
    if (length > badgeDataStart + maxBadgeBytes) {
      int collarDataStart = badgeDataStart + BADGE_LED_COUNT * 3;
      int maxCollarBytes = min((int)length - collarDataStart, COLLAR_LED_COUNT * 3);

      for (int i = 0; i < maxCollarBytes; i++) {
        collarBuffer[i] = data[collarDataStart + i];
      }
    }
  }

  // Increment packet counter for FPS calculation
  packetCount++;

  // Set the data ready flag and update the timestamp
  dataReady = true;
  lastLEDUpdateTime = currentTime;
}