"""Art-Net opcode registry contracts.

The vendor opcode allocation (0x8000+) has drifted into a collision exactly
once: audio/FTP originally sat on 0x8200/0x8201 and clashed with ArtIPConfig
(0x8200), forcing the remap to 0x8300/0x8301 (commit a39db7c). These tests make
that class of bug — plus firmware/sender drift — impossible to reintroduce
silently, including via a bad main/V5 merge that drops or renumbers the newer
0x83xx audio block.

They assert, data-driven so new opcodes are covered automatically:
  1. every sender ARTNET_OPCODE_* is pairwise-unique;
  2. vendor opcodes (>= 0x8000) stay inside the 0x8000-0x8FFF range;
  3. each firmware config.h define equals the sender's value (no drift);
  4. every firmware opcode is known to the sender (no orphan opcode);
  5. the two firmware families agree on opcodes they both define;
  6. the branch-new 0x83xx audio block survives (present in sender + Radius
     firmware at the expected numbers).

The registry table lives in V5/FIRMWARE_DEVELOPMENT.md.
"""

import os
import re
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import artnet
import primus_protocol

ARDUINO_DIR = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..", "Arduino")
)
FIRMWARE_CONFIGS = {
    "primusV3_receiver": os.path.join(ARDUINO_DIR, "primusV3_receiver", "config.h"),
    "radius_receiver": os.path.join(ARDUINO_DIR, "radius_receiver", "config.h"),
}

_DEFINE_RE = re.compile(
    r"#define\s+ARTNET_OPCODE_([A-Z0-9_]+)\s+(0x[0-9A-Fa-f]+)"
)


def sender_opcodes():
    """{short name: value} for every Art-Net opcode the sender knows.

    V5 keeps the core Art-Net opcodes as ARTNET_OPCODE_* in artnet.py, but the
    versioned Primus management pair lives in primus_protocol.py as
    MANAGEMENT_*_OPCODE. Both are folded in so the firmware<->sender contract
    covers the whole 0x8xxx allocation. Names are normalized to the firmware's
    config.h short-name convention (`#define ARTNET_OPCODE_<NAME>`).
    """
    out = {}
    for name in dir(artnet):
        if name.startswith("ARTNET_OPCODE_"):
            out[name[len("ARTNET_OPCODE_"):]] = getattr(artnet, name)
    for name in dir(primus_protocol):
        if name.endswith("_OPCODE"):
            out[name[: -len("_OPCODE")]] = getattr(primus_protocol, name)
    return out


def firmware_opcodes(path):
    """{short name: value} for every #define ARTNET_OPCODE_* in a config.h."""
    with open(path, encoding="utf-8") as f:
        src = f.read()
    return {m.group(1): int(m.group(2), 16) for m in _DEFINE_RE.finditer(src)}


class SenderOpcodeContracts(unittest.TestCase):
    def test_sender_opcodes_pairwise_unique(self):
        ops = sender_opcodes()
        seen = {}
        for name, value in ops.items():
            self.assertNotIn(
                value, seen,
                f"opcode collision: {name} and {seen.get(value)} both = "
                f"{value:#06x}",
            )
            seen[value] = name

    def test_vendor_opcodes_stay_in_reserved_range(self):
        for name, value in sender_opcodes().items():
            if value >= 0x8000:
                self.assertLessEqual(
                    value, 0x8FFF,
                    f"{name} ({value:#06x}) escapes the 0x8000-0x8FFF vendor range",
                )

    def test_audio_block_present_at_expected_numbers(self):
        # The 0x83xx block is new on radius-central; pin it so a merge cannot
        # drop or renumber it back toward the historical 0x82xx collision.
        self.assertEqual(artnet.ARTNET_OPCODE_AUDIO_CMD, 0x8300)
        self.assertEqual(artnet.ARTNET_OPCODE_FTP_CMD, 0x8301)
        self.assertEqual(artnet.ARTNET_OPCODE_AUDIO_STATUS, 0x8302)


class FirmwareSyncContracts(unittest.TestCase):
    def test_firmware_defines_are_unique(self):
        for family, path in FIRMWARE_CONFIGS.items():
            ops = firmware_opcodes(path)
            seen = {}
            for name, value in ops.items():
                with self.subTest(family=family, opcode=name):
                    self.assertNotIn(
                        value, seen,
                        f"{family}: {name} and {seen.get(value)} both = "
                        f"{value:#06x}",
                    )
                    seen[value] = name

    def test_firmware_matches_sender(self):
        sender = sender_opcodes()
        for family, path in FIRMWARE_CONFIGS.items():
            for name, value in firmware_opcodes(path).items():
                with self.subTest(family=family, opcode=name):
                    self.assertIn(
                        name, sender,
                        f"{family} defines ARTNET_OPCODE_{name} but the sender "
                        f"has no matching constant",
                    )
                    self.assertEqual(
                        value, sender[name],
                        f"{family} ARTNET_OPCODE_{name} = {value:#06x} but "
                        f"sender = {sender[name]:#06x}",
                    )

    def test_firmware_families_agree_on_shared_opcodes(self):
        led = firmware_opcodes(FIRMWARE_CONFIGS["primusV3_receiver"])
        radius = firmware_opcodes(FIRMWARE_CONFIGS["radius_receiver"])
        for name in sorted(set(led) & set(radius)):
            with self.subTest(opcode=name):
                self.assertEqual(
                    led[name], radius[name],
                    f"LED and Radius disagree on ARTNET_OPCODE_{name}: "
                    f"{led[name]:#06x} vs {radius[name]:#06x}",
                )

    def test_radius_firmware_defines_the_audio_block(self):
        radius = firmware_opcodes(FIRMWARE_CONFIGS["radius_receiver"])
        self.assertEqual(radius.get("AUDIO_CMD"), 0x8300)
        self.assertEqual(radius.get("FTP_CMD"), 0x8301)
        self.assertEqual(radius.get("AUDIO_STATUS"), 0x8302)


if __name__ == "__main__":
    unittest.main()
