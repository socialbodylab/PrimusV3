# Overview
Primus v2 was a simplified version of v1 that was designed as a DIY board. 
the full details can be found in the local github repo: primus-makeEdition

# Microcontroller
This used the updated version of the ESP32 Feather: https://learn.adafruit.com/adafruit-esp32-feather-v2
This feather also doesn't have a TFT screen

# Firmware
This firmware move to using Artnet, but in a much more simple format that requires manually setting IP addresses etc
the full code can be found in primus_v2.ino

# Neopixel Types
30 LED Neopixel strip (the same as the current short strip type)
4X8 Neopixel Featherwing Grid - https://learn.adafruit.com/adafruit-neopixel-featherwing?view=all

# Physical Setup
- Connected to an Adafruit Doubler
- System was powered via LiPo battery
- Neopixels were connected directly to the pins , No NEOPXL8 board
- There was 1 distinct types of the boards
- - Type 1 : Neopixel Grid + Neopixel Strip. 
- - - Neopixel Grid is connected through a doubler via pin 32
- - - Neopixel strip is connected via detachable connector via pin 12