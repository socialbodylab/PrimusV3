# User Guide : Primus Central + Firmware

> **Audience:** Show operators. Covers router and network setup, static IP configuration, and the Primus Central app UI. For developer shell commands (starting the sender, firmware upload, etc.), see [DEVELOPER_COMMANDS.md](DEVELOPER_COMMANDS.md).

## Router Setup
SSID: OPERADEV  
pw: torrentoflight

Router IP: 192.168.8.1
adminpw: r0b0tsr0b0ts

Device Starting IP: 192.168.8.100
Device Ending IP: 192.168.8.254
Subnet Mask: 255.255.255.0


### Laptop Setup
#### Suggested Connection Method
Laptop -> USB/Ethernet Adapter -> Ethernet Cable -> LAN Port
This allows you to connect with the devices and maintain an internet connection

#### Setting the Static IP for your laptop to 192.168.8.105
Because the router does not have internet, it doesn't have DHCP and you need to set a static IP for the device.

1. Go to the Settings tab in Primus Central
2. In the **Active Connections** section choose USB10/100/1000 LAN
3. In the **Sender IP on Show Router** section choose Static IP
4. Set **SENDER STATIC IP** to 192.168.8.105
5. Set **GATEWAY** to 192.168.8.1
6. Set **SUBNET** to 255.255.255.0
7. Hit **Apply to MacOS**
8. When prompted, enter your MacOS password
9. In the **Show Router Setup** panel at the top, choose **Use for Art-Net**

[V3_5/assets/appScreenshots/Settings.png]

Your computer is now configured to send color data to devices
You should see the assigned IP in the Info panel at the top of the app






## Primus Central
Primus Central provides functionality to:
- Set up devices on the network
- Create Cue-able looks that can be sent to devices
- Upload current firmware to all 3 types of hardware
- Set up Controller Network settings

### Device Panel
