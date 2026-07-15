import errno
import os
import sys
import unittest
from unittest.mock import patch

SENDER_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SENDER_DIR not in sys.path:
    sys.path.insert(0, SENDER_DIR)

import artnet


class FakeUdpSocket:
    instances = []

    def __init__(self, *args, **kwargs):
        self.bound = None
        self.send_attempts = 0
        FakeUdpSocket.instances.append(self)

    def bind(self, addr):
        self.bound = addr

    def sendto(self, data, addr):
        self.send_attempts += 1
        if self.bound is not None:
            raise OSError(errno.EHOSTUNREACH, "No route to host")
        return len(data)

    def close(self):
        pass


class ArtNetUdpPacketTests(unittest.TestCase):
    def test_send_udp_packet_retries_without_source_bind_on_route_error(self):
        FakeUdpSocket.instances = []
        with patch("artnet.socket.socket", FakeUdpSocket):
            artnet._send_udp_packet("192.168.4.50", b"test-packet", source_ip="10.0.0.5")

        self.assertEqual(len(FakeUdpSocket.instances), 2)
        self.assertEqual(FakeUdpSocket.instances[0].bound, ("10.0.0.5", 0))
        self.assertIsNone(FakeUdpSocket.instances[1].bound)
        self.assertEqual(FakeUdpSocket.instances[1].send_attempts, 1)

    def test_artnet_sender_remembers_unbound_fallback(self):
        sender = artnet.ArtNetSender("192.168.4.50", source_ip="10.0.0.5")
        sender.connect()

        calls = []

        def fake_open(bind_source=True):
            calls.append(bind_source)
            sender.sock = FakeUdpSocket()
            if bind_source:
                sender.sock.bound = ("10.0.0.5", 0)

        def fake_sendto(pkt, addr):
            if sender.sock.bound is not None:
                raise OSError(errno.EHOSTUNREACH, "No route to host")

        sender._open_socket_unlocked = fake_open
        sender.sock = FakeUdpSocket()
        sender.sock.bound = ("10.0.0.5", 0)
        sender.sock.sendto = fake_sendto

        self.assertTrue(sender.send_output(0, b"\x00" * 6))
        self.assertTrue(sender._prefer_unbound_send)
        self.assertEqual(calls, [True, False])


if __name__ == "__main__":
    unittest.main()
