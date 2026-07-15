PrimusCentral 0.9 for Windows
===============================

PrimusCentral is the sender app for Primus V5/V3-compatible LED receiver nodes.
This Windows build is packaged from the same V5 unified sender as the macOS
0.9 release.

Getting started
---------------

1. Install with PrimusCentral-0.9-Windows-x64-Setup.exe, or extract the
   PrimusCentral-0.9-Windows-x64.zip folder before running PrimusCentral.exe.
2. Launch PrimusCentral from the Start menu, desktop shortcut, or extracted
   folder.
3. The browser UI opens on localhost. The HTTP UI is local to this computer.
4. Connect this Windows computer to the show router or receiver network.
5. If Windows Defender Firewall prompts, allow PrimusCentral on the private or
   show-network profile you are using.

Network access
--------------

PrimusCentral uses UDP network traffic for receiver control and show control:

- Art-Net discovery, output, and receiver control: UDP 6454
- Receiver FPS telemetry: UDP 6455 inbound
- External OSC cue input: UDP 53001 by default

Version 0.9 listens for OSC automatically on loopback and active LAN
interfaces. Only the OSC enable switch and port are configurable in the Cue
Controller. For QLab or another show-control computer, target one of the LAN
addresses shown in the Cue Controller's External Control panel, for example
192.168.1.50:53001.

If local testing works but another computer cannot trigger cues, check that:

- Both computers are on the same show network.
- The target address is the Windows computer's show-network IP, not 127.0.0.1.
- Windows Defender Firewall allows PrimusCentral on that network profile.
- The Cue Controller network log shows active sockets and packet receipts.

Security notes
--------------

The installer is user-local and does not run the full app as Administrator.
Network Settings changes that alter the Windows adapter may trigger a UAC
prompt for the specific system command. PrimusCentral does not store Windows
administrator credentials.

Use assets from the official GitHub release and verify checksums when possible.
SmartScreen warnings can still appear while Windows reputation builds for a new
release, even when the executable and installer are Authenticode signed.
