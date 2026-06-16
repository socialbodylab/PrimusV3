/*
 * WiFi and Network Settings
 *
 * This file contains all the network configuration for the LED controller.
 * Modify these settings to match your network before uploading the code.
 */



// WiFi network credentials
// Change these to match your WiFi network
const char* WIFI_SSID = "myHomeNetwork";           // The name of your WiFi network
const char* WIFI_PASSWORD = "blinkylights";        // Your WiFi password

// Fixed IP address configuration
// Change these if they conflict with your network setup
IPAddress LOCAL_IP(192, 168, 1, 100);   // Static IP address for the ESP32
IPAddress GATEWAY(192, 168, 1, 1);     // Gateway (usually your router's IP)
IPAddress SUBNET(255, 255, 255, 0);      // Subnet mask

// Art-Net specific settings
const int UNIVERSE = 0;                  // Art-Net universe to listen on
