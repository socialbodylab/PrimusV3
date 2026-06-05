/*
 * ftp_sd_test — Step 1: SimpleFTPServer + SD only, no VS1053
 *
 * Target: Adafruit Feather HUZZAH32
 * SD CS:  GPIO14 (Music Maker FeatherWing)
 *
 * Test with: python3 tools/radius_test.py ftp
 */

#define DEFAULT_FTP_SERVER_NETWORK_TYPE_ESP32 NETWORK_ESP32
#define DEFAULT_STORAGE_TYPE_ESP32 STORAGE_SD
#define FTP_SERVER_DEBUG

#include <WiFi.h>
#include <SPI.h>
#include <SD.h>
#include <SimpleFTPServer.h>

#define WIFI_SSID     "RUR"
#define WIFI_PASSWORD "rurrurrur"
#define FTP_USER      "primus"
#define FTP_PASS      "primus"
#define SD_CS_PIN     14   // GPIO14 — Music Maker FeatherWing SD CS

FtpServer ftpSrv;

void setup() {
  Serial.begin(115200);
  delay(500);
  Serial.println("\n=== ftp_sd_test step 1 ===");

  // Static IP on Mango subnet
  IPAddress ip(192, 168, 8, 150);
  IPAddress gw(192, 168, 8, 1);
  IPAddress sn(255, 255, 255, 0);
  WiFi.config(ip, gw, sn);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  Serial.print("WiFi connecting");
  uint32_t t = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - t < 15000) {
    delay(500); Serial.print('.');
  }
  Serial.println();
  if (WiFi.status() == WL_CONNECTED)
    Serial.print("Connected, IP: "), Serial.println(WiFi.localIP());
  else
    Serial.println("WiFi failed");

  Serial.print("SD init (CS="); Serial.print(SD_CS_PIN); Serial.print(")... ");
  if (!SD.begin(SD_CS_PIN)) {
    Serial.println("FAILED");
    return;
  }
  Serial.println("OK");
  Serial.print("STORAGE_TYPE="); Serial.println(STORAGE_TYPE);

  ftpSrv.begin(FTP_USER, FTP_PASS);
  Serial.println("FTP server started. Connect with: python3 tools/radius_test.py ftp");
}

void loop() {
  ftpSrv.handleFTP();

  // Every 10s, independently verify SD is still readable
  static unsigned long lastCheck = 0;
  if (millis() - lastCheck > 10000) {
    lastCheck = millis();
    File root = SD.open("/");
    int n = 0;
    while (true) {
      File e = root.openNextFile();
      if (!e) break;
      n++;
      e.close();
    }
    root.close();
    Serial.print("[SD check] files in root: "); Serial.println(n);
  }
}
