#include <ArduinoOSCWiFi.h>
#include <Adafruit_NeoPixel.h>
#include <Preferences.h>

Preferences preferences;

IPAddress ip;
IPAddress gateway;
IPAddress subnet;
const char* network;
const char* password;
const char* host;
int advt_Port, data_Port;

int DeviceID;
String DeviceType;

//data to send
int batteryLevel = 0;
int deviceID;

const String inAddress = "/rur/light";

//Neopixel setup
#define MATRIXPIN 32
#define STRIPPIN  12

const int matrixLeds = 32;
const int stripLeds = 72;

int matrixBrightness = 100;
int stripBrightness = 100;


Adafruit_NeoPixel matrix(matrixLeds, MATRIXPIN, NEO_GRB + NEO_KHZ800);
Adafruit_NeoPixel strip(stripLeds, STRIPPIN, NEO_GRB + NEO_KHZ800);
//Adafruit_NeoPixel strip(stripLeds, STRIPPIN, NEO_GRBW + NEO_KHZ800);

void(* resetFunc) (void) = 0; //declare reset function @ address 0


void connectWiFi() {
  // WiFi stuff (no timeout setting for WiFi)
#ifdef ESP_PLATFORM
  WiFi.disconnect(true, true);  // disable wifi, erase ap info
  delay(1000);
  WiFi.mode(WIFI_STA);
#endif
  WiFi.begin(network, password);
  WiFi.config(ip, gateway, subnet);
  while (WiFi.status() != WL_CONNECTED) {
    Serial.print(".");
    delay(500);
  }
  Serial.print("WiFi connected, IP = ");
  Serial.println(WiFi.localIP());
}
void setup() {

  //fetch preferences and store into variables
  preferences.begin("credentials", false);
  String ssid = preferences.getString("ssid", "");
  String pwd = preferences.getString("pwd", "");
  String ipAddress = preferences.getString("ipAddress", "");
  String gatewayAddress = preferences.getString("gatewayAddress", "");
  String subnetAddress = preferences.getString("subnetAddress", "");
  String hostAddress = preferences.getString("hostAddress", "");
  advt_Port = preferences.getString("advt_Port", "").toInt();
  data_Port = preferences.getString("data_Port", "").toInt();
  DeviceID = preferences.getString("deviceID", "").toInt();
  DeviceType = preferences.getString("deviceType", "");

  //convert strings to things that are usable lol
  network = ssid.c_str();
  password = pwd.c_str();
  ip.fromString(ipAddress);
  gateway.fromString(gatewayAddress);
  subnet.fromString(subnetAddress);
  host = hostAddress.c_str();


  pinMode(LED_BUILTIN, OUTPUT);
  digitalWrite(LED_BUILTIN, LOW);
  Serial.begin(115200);
  delay(1000);

  connectWiFi();

  //turn on led to show wifi connection
  digitalWrite(LED_BUILTIN, HIGH);

  //turn all pixels off
  matrix.begin();
  matrix.setBrightness(100);
  matrix.show();

  strip.begin();
  strip.setBrightness(100);
  strip.show();


  ///this subscribes to messages on a particular port/address
  //and defines the function that is called each time
  OscWiFi.subscribe(data_Port, inAddress,
  [](const OscMessage & m) {
        noInterrupts();
        //the data is packaged as , separated strings per pixel "R,G,B,R,G,B..."
        String recvString = m.arg<String>(0);
        //Serial.println(recvString);
        //Serial.println();

        //convert the string to a char array
        unsigned int str_len = recvString.length() + 1;
        char rgbCharArray[str_len];
        recvString.toCharArray(rgbCharArray,sizeof(rgbCharArray));


        int valuesReceived = strlen( rgbCharArray );
        //Serial.println( valuesReceived ); // should be values + values - 1 for commas



        //split the char and build pointer array to access values
        ///based on this https://forum.arduino.cc/t/separating-a-comma-delimited-string/682868/4

        int totalVals = ((matrixLeds+stripLeds)*3); // create an int array for r g b for each neopixel
        int index = 0;


        int colourVals[totalVals];
        // NOTE this might be a good place to test that str_len and totalVals are the same
        char *token = NULL;
        token = strtok(rgbCharArray, ",");  // get the first token in the string
        while (token != NULL)
        {

        //put the value into the array and constrain it to the proper range
         colourVals[index] = constrain(atoi( token ),0,255);


            token = strtok(NULL, ","); // get the next token until , and return NULL if can't find another
            index++;
        }
        //Serial.print("XX ");
        //Serial.println(index);
        //check if it received the correct number of values
        //using index instead of the length of the array because it is declared at the full size
        if(index==totalVals)
        {
            ///assign the RGB values to the neopixels
            //GRID -> Patch
            int pixelNumber = 0;
            for(int i=0;i<(matrixLeds*3);i+=3)
            {
                // NOTE suggest moving to this
                matrix.setPixelColor(pixelNumber,colourVals[i],colourVals[i+1],colourVals[i+2]);

                pixelNumber++;
            }
            //STRIP -> Collar
            pixelNumber=0;
            for(int i=(matrixLeds*3);i<totalVals;i+=3)
            {
                strip.setPixelColor(pixelNumber,colourVals[i],colourVals[i+1],colourVals[i+2]);
                pixelNumber++;
            }

            //show the data for both
            strip.show();
            matrix.show();
        }

        interrupts();

  });

  // Send batter level every 1 second
  OscWiFi.publish(host, advt_Port, "/publish/status", DeviceType, deviceID, batteryLevel)->setFrameRate(1.f);

}

void loop() {
  //this is needed to make the library work
  if (WiFi.status() != WL_CONNECTED)
    connectWiFi();
  OscWiFi.update();
  batteryLevel = map(constrain(analogRead(A13), 2000, 2550), 2000, 2550, 0, 100); //2000 translates to 3.4V and 2550 translates to 4.2V; Mapping them to a scale of 0 to 100 (%)
}
