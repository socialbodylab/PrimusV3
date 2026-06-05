#!/usr/bin/env python3
"""
tools/radius_test.py — Radius node diagnostic tool.

Usage:
  python3 tools/radius_test.py ftp              # list SD card files (raw)
  python3 tools/radius_test.py stop             # send stop command
  python3 tools/radius_test.py play FILE        # play a file
  python3 tools/radius_test.py tone             # play test tone
  python3 tools/radius_test.py vol 80           # set volume
  python3 tools/radius_test.py ping             # send ArtPoll and wait for reply

Options:
  --ip IP    Device IP (default: 192.168.8.150)
  --vol VOL  Volume 0-100 for play/tone (default: 80)
"""

import argparse
import ftplib
import socket
import struct
import time
import sys

DEVICE_IP      = "192.168.8.150"
FTP_PORT       = 21
FTP_USER       = "primus"
FTP_PASSWORD   = "primus"
ARTNET_PORT    = 6454
ARTNET_HEADER  = b"Art-Net\x00"
ARTNET_VERSION = 14

AUDIO_CMD_STOP   = 0
AUDIO_CMD_PLAY   = 1
AUDIO_CMD_LOOP   = 2
AUDIO_CMD_PAUSE  = 3
AUDIO_CMD_VOLUME = 4
AUDIO_CMD_TONE   = 5

ARTNET_OPCODE_AUDIO_CMD = 0x8200
ARTNET_OPCODE_POLL      = 0x2000
ARTNET_OPCODE_POLLREPLY = 0x2100


# ── Art-Net helpers ───────────────────────────────────────────────────────────

def send_audio_cmd(ip, cmd, filename="", volume=80):
    name_bytes = filename.encode("ascii", errors="replace")[:32] + b"\x00"
    pkt = bytearray(14 + len(name_bytes))
    pkt[0:8] = ARTNET_HEADER
    struct.pack_into("<H", pkt, 8, ARTNET_OPCODE_AUDIO_CMD)
    struct.pack_into(">H", pkt, 10, ARTNET_VERSION)
    pkt[12] = cmd & 0xFF
    pkt[13] = max(0, min(100, volume)) & 0xFF
    pkt[14:14 + len(name_bytes)] = name_bytes
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.sendto(bytes(pkt), (ip, ARTNET_PORT))
        cmd_names = {0:"stop", 1:"play", 2:"loop", 3:"pause", 4:"volume", 5:"tone"}
        print(f"[UDP] cmd={cmd_names.get(cmd, cmd)} vol={volume} file={filename!r} → {ip}:{ARTNET_PORT}")
    finally:
        sock.close()


def send_artpoll(ip):
    pkt = bytearray(14)
    pkt[0:8] = ARTNET_HEADER
    struct.pack_into("<H", pkt, 8, ARTNET_OPCODE_POLL)
    struct.pack_into(">H", pkt, 10, ARTNET_VERSION)
    pkt[12] = 0x02  # TalkToMe
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.settimeout(2.0)
    try:
        sock.sendto(bytes(pkt), (ip, ARTNET_PORT))
        print(f"[UDP] ArtPoll sent to {ip}")
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline:
            try:
                data, addr = sock.recvfrom(512)
            except socket.timeout:
                break
            if len(data) >= 10 and data[:8] == ARTNET_HEADER:
                opcode = data[8] | (data[9] << 8)
                if opcode == ARTNET_OPCODE_POLLREPLY:
                    short_name = data[26:44].split(b"\x00")[0].decode("ascii", errors="replace")
                    long_name  = data[44:108].split(b"\x00")[0].decode("ascii", errors="replace")
                    node_ip    = f"{data[10]}.{data[11]}.{data[12]}.{data[13]}"
                    print(f"[ArtPollReply] {addr[0]}  short={short_name!r}  long={long_name!r}  ip={node_ip}")
    finally:
        sock.close()


# ── FTP helpers ───────────────────────────────────────────────────────────────

def ftp_list_raw(ip, path="/"):
    print(f"[FTP] Connecting to {ip}:{FTP_PORT}...")
    ftp = ftplib.FTP()
    ftp.connect(ip, FTP_PORT, timeout=10)
    print(f"[FTP] Banner: {ftp.getwelcome()!r}")
    ftp.login(FTP_USER, FTP_PASSWORD)
    print(f"[FTP] Logged in as {FTP_USER!r}")

    lines = []
    try:
        ftp.retrlines(f"LIST {path}", lines.append)
    except Exception as e:
        print(f"[FTP] LIST failed: {e}")
        try:
            ftp.retrlines("NLST", lines.append)
            print(f"[FTP] NLST fallback:")
        except Exception as e2:
            print(f"[FTP] NLST also failed: {e2}")

    print(f"[FTP] {len(lines)} line(s) from LIST {path!r}:")
    for line in lines:
        print(f"  {line!r}")

    try:
        ftp.quit()
    except Exception:
        ftp.close()

    return lines


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Radius node diagnostic tool")
    parser.add_argument("action", nargs="?", default="ftp",
                        choices=["ftp", "stop", "play", "loop", "pause", "tone", "vol", "ping"],
                        help="Action to perform")
    parser.add_argument("arg", nargs="?", default="",
                        help="Filename for play/loop, or volume level for vol")
    parser.add_argument("--ip",  default=DEVICE_IP, help="Device IP address")
    parser.add_argument("--vol", type=int, default=80, help="Volume 0-100")
    args = parser.parse_args()

    ip = args.ip

    if args.action == "ftp":
        ftp_list_raw(ip)

    elif args.action == "ping":
        send_artpoll(ip)

    elif args.action == "stop":
        send_audio_cmd(ip, AUDIO_CMD_STOP)

    elif args.action == "play":
        filename = args.arg
        if not filename:
            print("Usage: radius_test.py play FILENAME")
            sys.exit(1)
        send_audio_cmd(ip, AUDIO_CMD_PLAY, filename, args.vol)

    elif args.action == "loop":
        filename = args.arg
        if not filename:
            print("Usage: radius_test.py loop FILENAME")
            sys.exit(1)
        send_audio_cmd(ip, AUDIO_CMD_LOOP, filename, args.vol)

    elif args.action == "pause":
        send_audio_cmd(ip, AUDIO_CMD_PAUSE)

    elif args.action == "tone":
        send_audio_cmd(ip, AUDIO_CMD_TONE, volume=args.vol)

    elif args.action == "vol":
        try:
            v = int(args.arg) if args.arg else args.vol
        except ValueError:
            print(f"Invalid volume: {args.arg!r}")
            sys.exit(1)
        send_audio_cmd(ip, AUDIO_CMD_VOLUME, volume=v)


if __name__ == "__main__":
    main()
