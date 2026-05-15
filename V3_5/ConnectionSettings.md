# Connection Settings

The common Primus setup is a sender computer wired by Ethernet to a dedicated show router, with ESP32 receivers joined to that router over WiFi. The router may have no internet connection, and DHCP may be unavailable or unreliable. Settings focuses on making the sender IP, subnet mask, gateway, and receiver IP range line up.

The Settings tab gives this its own operational surface to the right of Firmware.

## Show Router Setup

Settings recommends an active Ethernet or USB-Ethernet connection when one is available. The Show Router Setup section displays:

- Selected sender connection and macOS service.
- Sender IP, subnet, gateway, network CIDR, and usable host range.
- Actions to use that connection for Art-Net, return to automatic routing, and discover receivers.

Selecting a connection marks it as the preferred Art-Net route. Discovery, connect, rename, output config, and receiver IP config operations use that selected source IP when possible. Automatic Routing clears the preference and returns to all-interface discovery behavior.

## Sender IP On Show Router

Static sender IP is the recommended mode when the show router has no internet or no dependable DHCP. Settings can save and apply a static/DHCP profile for a wired service or WiFi SSID. For static profiles, the saved values are:

- Sender static IP
- Gateway
- Subnet

Settings validates that the subnet mask is contiguous, the sender IP is a usable host address, and the gateway is in the same subnet as the sender IP. It also shows the derived CIDR and usable range before applying the profile.

Save Sender Profile stores the profile in Primus Central. Apply to macOS changes the actual macOS network service with `networksetup` through an administrator prompt. No WiFi passwords, admin passwords, or tokens are stored by Primus Central.

## Receiver Network

The Receiver Network section compares saved receivers against the selected sender static range. It shows each receiver's current IP mode, pending reboot state, saved static IP when known, and range status:

- In Range
- Different Range
- Pending In Range
- Pending Different Range
- Unknown

Receiver DHCP/static controls remain available in the existing device controls. Static/DHCP receiver changes are sent over Art-Net, stored on the receiver, and applied after the receiver reboots.

## Active Connections

The tab lists active local IPv4 connections Primus can use on macOS:

- WiFi services, including the current SSID when macOS reports it.
- Ethernet or USB-Ethernet services.
- Current sender IP, subnet, broadcast address, gateway, and default-route status.

Inactive services are hidden from the connection list for visual clarity, though the backend still reports them for diagnostics.

## Advanced WiFi Router

Some setups put the sender computer on the show router WiFi instead of Ethernet. The Advanced WiFi Router section keeps the named controller SSID workflow for that case.

The Controller SSID can be typed directly or filled from the currently active WiFi network. This means the show-router WiFi can be named before it is active, and Primus will recognize it later when the computer joins that SSID.

If macOS reports a privacy placeholder such as `<redacted>` or `<data> 0x00` instead of the current SSID, Primus ignores that placeholder. A typed Controller SSID is still saved, and when it is saved against the active WiFi adapter Primus can keep using that adapter/source IP as the controller route. Fully automatic SSID switching still depends on macOS exposing the real current SSID.

When Primus Central sees the tagged SSID active, that connection becomes the selected Art-Net route even if the physical WiFi service is the same macOS network service used by the internet SSID. When the computer is back on a different WiFi SSID, the controller tag no longer matches, so Primus does not treat that internet connection as the show-controller route.

## Platform Scope

The first implementation applies host IP changes on macOS only. Other platforms report unsupported status for host network switching while keeping the rest of Primus Central available.