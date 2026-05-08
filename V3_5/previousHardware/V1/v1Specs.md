# General Description
The V1 of Primus had a few key characteristics that distinguish it from the current version. 

# Microcontroller
The original version was based on the older ESP32 Huzzah board
https://learn.adafruit.com/adafruit-huzzah32-esp32-feather?view=all

- The key difference to the current version is a lack of screen

# Firmware
This firmware used OSC messages instead of ArtNet and was much more basic. It required setting the IP addresses manually for each board. it also required setting the number of pixels in the Neopixel strip manually.

see the details in primus_v1.ino

# Neopixel Types
72 LED Neoixel strip
144 LED Neopixel strip
4X8 Neopixel Featherwing Grid - https://learn.adafruit.com/adafruit-neopixel-featherwing?view=all

# Physical Setup
This setup had key differences to V3
- Connected to an Adafruit Doubler
- System was powered via LiPo battery
- Neopixels were connected directly to the pins , No NEOPXL8 board
- There were 3 distinct types of the boards
- - Type 1 : Neopixel Grid + Neopixel Strip. 
- - - Neopixel Grid is connected through a doubler via pin 32
- - - Neopixel strip is connected via detachable connector via pin 12
- - Type 2 : Neopixel Strip only
- - - Neopixel strip is connected via detachable connector via pin 12
- - Type 3 : Neopixel Grid only
- - - Neopixel Grid is connected through a doubler via pin 32