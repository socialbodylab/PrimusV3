#!/usr/bin/env python3
"""Generate Primus-Radius-Systems.drawio multi-page workbook (L0–L5 + device D*)."""

from __future__ import annotations

import uuid
from pathlib import Path
from xml.sax.saxutils import escape

OUT = Path(__file__).resolve().parent / "Primus-Radius-Systems.drawio"

# Visual language (avoid purple/indigo AI defaults)
C = {
    "bg": "#F7F5F2",
    "lan": "#E8F0E6",
    "primus": "#1F4E5F",
    "primus_fill": "#D6E8EE",
    "radius": "#8B4513",
    "radius_fill": "#F3E6D8",
    "eos": "#2C3E50",
    "eos_fill": "#E5E9ED",
    "shared": "#3D5A40",
    "shared_fill": "#DCE8DC",
    "warn": "#8B3A2A",
    "warn_fill": "#F5E0DA",
    "text": "#1A1A1A",
    "muted": "#5A5A5A",
    "white": "#FFFFFF",
    "line": "#333333",
}


def style_box(fill, stroke, bold=False, align="center", valign="middle", font_size=12):
    fw = "1" if bold else "0"
    return (
        f"rounded=1;whiteSpace=wrap;html=1;fillColor={fill};strokeColor={stroke};"
        f"fontColor={C['text']};fontSize={font_size};fontStyle={fw};"
        f"align={align};verticalAlign={valign};arcSize=8;"
    )


def style_edge(dashed=False, color=None):
    color = color or C["line"]
    d = "dashed=1;dashPattern=8 8;" if dashed else ""
    return (
        f"edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;jettySize=auto;"
        f"html=1;endArrow=block;endFill=1;strokeColor={color};fontColor={C['muted']};"
        f"fontSize=10;{d}"
    )


class Diagram:
    def __init__(self, name: str, page_w=1400, page_h=1000):
        self.name = name
        self.id = str(uuid.uuid4())
        self.page_w = page_w
        self.page_h = page_h
        self.cells: list[str] = []
        self._n = 2

    def _nid(self) -> str:
        i = self._n
        self._n += 1
        return str(i)

    def rect(self, x, y, w, h, label, fill, stroke, **kwargs):
        cid = self._nid()
        st = style_box(fill, stroke, **kwargs)
        self.cells.append(
            f'<mxCell id="{cid}" value="{escape(label)}" style="{st}" vertex="1" parent="1">'
            f'<mxGeometry x="{x}" y="{y}" width="{w}" height="{h}" as="geometry"/></mxCell>'
        )
        return cid

    def edge(self, source, target, label="", dashed=False, color=None):
        cid = self._nid()
        st = style_edge(dashed=dashed, color=color)
        val = escape(label) if label else ""
        self.cells.append(
            f'<mxCell id="{cid}" value="{val}" style="{st}" edge="1" parent="1" '
            f'source="{source}" target="{target}">'
            f'<mxGeometry relative="1" as="geometry"/></mxCell>'
        )
        return cid

    def title(self, text, sub=""):
        self.rect(40, 20, 900, 40, text, C["white"], C["primus"], bold=True, font_size=18, align="left")
        if sub:
            self.rect(40, 62, 1200, 28, sub, C["bg"], C["bg"], font_size=11, align="left")

    def to_xml(self) -> str:
        body = "\n".join(self.cells)
        return f"""  <diagram id="{self.id}" name="{escape(self.name)}">
    <mxGraphModel dx="1200" dy="800" grid="1" gridSize="10" guides="1" tooltips="1" connect="1" arrows="1" fold="1" page="1" pageScale="1" pageWidth="{self.page_w}" pageHeight="{self.page_h}" background="{C['bg']}" math="0" shadow="0">
      <root>
        <mxCell id="0"/>
        <mxCell id="1" parent="0"/>
{body}
      </root>
    </mxGraphModel>
  </diagram>"""


def page_00_index() -> Diagram:
    d = Diagram("00 Index", 1500, 1100)
    d.title(
        "00 — Linked diagram index (start here)",
        "Open a page below for focus · Full HTTP/Art-Net tables → docs/systems/API_CONTROLS.md",
    )

    hub = d.rect(560, 120, 280, 70, "SYSTEM OVERVIEW\n(this workbook)", C["shared_fill"], C["shared"], bold=True)

    l0 = d.rect(60, 240, 200, 70, "L0 Context\nLAN who→whom", C["lan"], C["shared"])
    l1 = d.rect(280, 240, 200, 70, "L1 Containers\nApps + stores", C["lan"], C["shared"])
    l4 = d.rect(500, 240, 200, 70, "L4 Ports\n6454/55/56", C["eos_fill"], C["eos"])
    l5 = d.rect(720, 240, 200, 70, "L5 Compare\nsystems", C["shared_fill"], C["shared"])
    api = d.rect(980, 240, 420, 70, "API_CONTROLS.md\nFull Primus + Radius tables", C["warn_fill"], C["warn"], bold=True)

    d.edge(hub, l0)
    d.edge(hub, l1)
    d.edge(hub, l4)
    d.edge(hub, l5)
    d.edge(hub, api, "reference", dashed=True, color=C["warn"])

    d.rect(60, 360, 1380, 28, "APPS & OPERATORS", C["primus_fill"], C["primus"], bold=True)
    dm = d.rect(60, 410, 220, 80, "L2a DeviceManager\nparams + monitor", C["primus_fill"], C["primus"])
    pp = d.rect(300, 410, 220, 80, "L2b Prototype\n→ Production", C["warn_fill"], C["warn"])
    eos = d.rect(540, 410, 220, 80, "L2c Eos paths\nArtDmx + OSC", C["eos_fill"], C["eos"])
    rp = d.rect(780, 410, 220, 80, "L3a Radius\nprototyping", C["radius_fill"], C["radius"])
    rprod = d.rect(1020, 410, 200, 80, "L3b Radius\nproduction", C["radius_fill"], C["radius"])
    name = d.rect(1240, 410, 200, 80, "L3c Naming\ntriad", C["shared_fill"], C["shared"])
    for n in (dm, pp, eos, rp, rprod, name):
        d.edge(hub, n, dashed=True)

    d.rect(60, 540, 1380, 28, "RECEIVERS (device level)", C["radius_fill"], C["radius"], bold=True)
    d1 = d.rect(60, 590, 220, 90, "D1 Primus block\nWiFi→NVS→LEDs", C["primus_fill"], C["primus"], bold=True)
    d2 = d.rect(300, 590, 220, 90, "D2 ArtDmx path\ndata plane", C["primus_fill"], C["primus"])
    d3 = d.rect(540, 590, 220, 90, "D3 Management\n0x8140 / lock", C["warn_fill"], C["warn"])
    d4 = d.rect(780, 590, 220, 90, "D4 Radius block\naudio-first loop", C["radius_fill"], C["radius"], bold=True)
    d5 = d.rect(1020, 590, 200, 90, "D5 Audio/cue\nSD + VS1053", C["radius_fill"], C["radius"])
    d6 = d.rect(1240, 590, 200, 90, "D6 Compare\none node each", C["shared_fill"], C["shared"])
    d.edge(d1, d2)
    d.edge(d1, d3)
    d.edge(d4, d5)
    d.edge(hub, d1, dashed=True)
    d.edge(hub, d4, dashed=True)
    d.edge(hub, d6, dashed=True)

    d.rect(
        60,
        740,
        1380,
        140,
        "How to use\n\n"
        "1. L0 / L1 — system shape\n"
        "2. API_CONTROLS.md — what each HTTP/Art-Net call does (and lock rules)\n"
        "3. L2* / L3* — operator workflows (DM, Eos, RadiusCentral)\n"
        "4. D1–D5 — inside one receiver\n"
        "Markdown hub with the same links: docs/systems/README.md",
        C["white"],
        C["line"],
        align="left",
        valign="top",
    )
    return d


def page_l0() -> Diagram:
    d = Diagram("L0 Context", 1400, 900)
    d.title(
        "L0 — Companion systems on one trusted show LAN",
        "Primus = LED ArtDmx · Radius = audio/FTP · DeviceManager monitors both · Eos drives Primus pixels · → API_CONTROLS.md",
    )
    # LAN frame
    d.rect(60, 110, 1280, 720, "", C["lan"], C["shared"])
    d.rect(80, 120, 260, 28, "Trusted show LAN", C["shared_fill"], C["shared"], bold=True, font_size=13)

    eos = d.rect(120, 200, 160, 80, "ETC Eos\n(console)", C["eos_fill"], C["eos"], bold=True)
    pc = d.rect(400, 180, 180, 70, "PrimusCentral\n(show control)", C["primus_fill"], C["primus"], bold=True)
    dm = d.rect(400, 280, 180, 70, "DeviceManager\n(monitor / setup)", C["primus_fill"], C["primus"], bold=True)
    rc = d.rect(400, 420, 180, 70, "RadiusCentral\n(audio production)", C["radius_fill"], C["radius"], bold=True)
    prx = d.rect(820, 200, 200, 100, "Primus receivers\nPV3CAP1\nv1 / v2 / v3", C["primus_fill"], C["primus"], bold=True)
    rrx = d.rect(820, 400, 200, 100, "Radius receivers\nPVRAD1\nrv1 / rv2", C["radius_fill"], C["radius"], bold=True)

    d.edge(eos, prx, "ArtDmx :6454")
    d.edge(eos, pc, "OSC cues (optional)", dashed=True, color=C["eos"])
    d.edge(pc, prx, "ArtDmx :6454")
    d.edge(pc, prx, "mgmt 0x8140", dashed=True, color=C["primus"])
    d.edge(dm, prx, "PST / sync / setup", color=C["primus"])
    d.edge(dm, rrx, "PTR / identity", color=C["radius"])
    d.edge(rc, rrx, "ArtAudio / FTP :6456", color=C["radius"])

    d.rect(
        80,
        700,
        1240,
        100,
        "Shared: discovery language · identity triad · IP tooling · DeviceManager mixed monitor\n"
        "Not shared: pixel vs audio transport · Radius never receives ArtDmx · commissioning lock is Primus-only (for now)",
        C["white"],
        C["shared"],
        align="left",
        font_size=12,
    )
    return d


def page_l1() -> Diagram:
    d = Diagram("L1 Containers", 1500, 1000)
    d.title(
        "L1 — Apps, receivers, and data stores",
        "One Primus-product backend can host PrimusCentral + DeviceManager; RadiusCentral is its own product runtime",
    )

    d.rect(60, 120, 420, 36, "Control / monitoring apps", C["shared_fill"], C["shared"], bold=True)
    d.rect(60, 170, 200, 90, "PrimusCentral\nLook Designer\nCue Controller\nArtDmx loop + OSC", C["primus_fill"], C["primus"])
    d.rect(280, 170, 200, 90, "DeviceManager\n/devices\nmonitor_only when\nowns backend", C["primus_fill"], C["primus"])
    d.rect(60, 280, 200, 90, "RadiusCentral\nAudio · Cues\nCue Map · Net Log", C["radius_fill"], C["radius"])
    d.rect(280, 280, 200, 70, "ETC Eos\nArtDmx (± OSC)", C["eos_fill"], C["eos"])

    d.rect(540, 120, 420, 36, "Receivers", C["shared_fill"], C["shared"], bold=True)
    d.rect(540, 170, 200, 110, "Primus ESP32\nNeoPixel A0/A1\nmgmt + PST\n:6454 / :6455", C["primus_fill"], C["primus"])
    d.rect(760, 170, 200, 110, "Radius ESP32\nMusic Maker + SD\nArtAudio + FTP\n:6456 / :6455", C["radius_fill"], C["radius"])

    d.rect(1040, 120, 400, 36, "Persistence", C["shared_fill"], C["shared"], bold=True)
    d.rect(
        1040,
        170,
        400,
        140,
        "PrimusV3/…/sender/\n  .primus_state.json\n  clips/ · looks/ · cues.json\n  output_presets.json",
        C["primus_fill"],
        C["primus"],
        align="left",
    )
    d.rect(
        1040,
        330,
        400,
        140,
        "RadiusV3/…/sender/\n  .radius_state.json\n  audio_cues.json\n  audio/ library\nDevice SD: /cues.json + WAVs",
        C["radius_fill"],
        C["radius"],
        align="left",
    )

    d.rect(
        60,
        420,
        920,
        200,
        "HTTP surfaces (unified server pattern)\n"
        "• /primus — PrimusCentral SPA\n"
        "• /devices — DeviceManager SPA (shared device-conn.js setup)\n"
        "• /radius — RadiusCentral SPA\n"
        "• JSON APIs: devices, management facade, audio/FTP, firmware, network\n\n"
        "Firmware: Primus V5 Arduino primusV3_receiver · Radius radius-central radius_receiver",
        C["white"],
        C["line"],
        align="left",
        font_size=12,
    )

    d.rect(
        60,
        660,
        1380,
        80,
        "Safety: DeviceManager monitor_only skips connect_all / standing ArtDmx — safe beside Eos.\n"
        "PST teleTarget is explicit; never learned from ArtDmx or Eos packet sources.",
        C["warn_fill"],
        C["warn"],
        align="left",
    )
    return d


def page_l2a() -> Diagram:
    d = Diagram("L2a DeviceManager Params", 1500, 1100)
    d.title(
        "L2a — DeviceManager controllable parameters",
        "Monitor-first board · see API_CONTROLS.md §1–2 for HTTP/Art-Net · Radius cards stay simplified",
    )

    d.rect(60, 120, 440, 36, "Always visible (monitor)", C["primus_fill"], C["primus"], bold=True)
    d.rect(
        60,
        170,
        440,
        280,
        "• Character name\n• Performer name\n• Device (technical) name\n"
        "• Status (Attention / Online / Offline)\n• FPS / PST health\n• Battery (profile-dependent)\n"
        "• IP + universe summary\n• Product tag + firmware\n• Hello (identify flash)\n"
        "• Mobile View: read-only + Hello",
        C["white"],
        C["primus"],
        align="left",
        valign="top",
    )

    d.rect(540, 120, 480, 36, "Expanded commissioning (Primus, prototype)", C["primus_fill"], C["primus"], bold=True)
    d.rect(
        540,
        170,
        480,
        360,
        "Outputs A0 / A1 (always present; Off valid)\n"
        "  – built-in · custom strip/grid · preset\n"
        "  – strip: phys 1–170, virtual send px\n"
        "  – grid: rows/cols, traversal, scan, corner, virtual px\n"
        "Receive mode: split | combined + base universe\n"
        "Static IP / DHCP\n"
        "Telemetry target (Use sender IP / clear)\n"
        "Enter production + recovery guidance\n"
        "Bulk rename / bulk apply (group-scoped)\n"
        "Firmware (scope=mixed) · Settings",
        C["white"],
        C["primus"],
        align="left",
        valign="top",
    )

    d.rect(1060, 120, 380, 36, "Production lock", C["warn_fill"], C["warn"], bold=True)
    d.rect(
        1060,
        170,
        380,
        220,
        "LOCKED\nnames · IP · descriptors\nreceive mode · teleTarget\n\nSTILL ACTIVE\nArtDmx · discovery\nPST · Hello\n\nRecover: V3 D1 long-press\nV1/V2 boot window 60s",
        C["white"],
        C["warn"],
        align="left",
        valign="top",
    )

    d.rect(1060, 420, 380, 36, "Radius cards in DM", C["radius_fill"], C["radius"], bold=True)
    d.rect(
        1060,
        470,
        380,
        200,
        "Identity · IP · status/FPS/track\nHello = test tone\nStatic IP when expanded\n\nNO universes / outputs\nNO management-v2 path",
        C["white"],
        C["radius"],
        align="left",
        valign="top",
    )

    d.rect(
        60,
        580,
        960,
        120,
        "Commissioning sequence: flash → discover → names → IP/universe → A0/A1 descriptors → PST target → verify Hello/ArtDmx/PST → enter production",
        C["shared_fill"],
        C["shared"],
        align="left",
    )
    return d


def page_l2b() -> Diagram:
    d = Diagram("L2b Prototype Production", 1400, 900)
    d.title(
        "L2b — Primus prototype → production → recovery",
        "opMode on receiver · production freezes commissioning, not ArtDmx ownership",
    )

    proto = d.rect(120, 200, 280, 160, "PROTOTYPE\n(default)\n\nFull management\n+ legacy mutations\neditable", C["primus_fill"], C["primus"], bold=True)
    prod = d.rect(560, 200, 280, 160, "PRODUCTION\n\nCommissioning\n→ NACK/LOCKED\nArtDmx still live", C["warn_fill"], C["warn"], bold=True)
    rec = d.rect(1000, 200, 280, 160, "RECOVERY\n\nV3: D1 long-press\nV1/V2: unlock in\nfirst 60s after boot", C["eos_fill"], C["eos"], bold=True)

    d.edge(proto, prod, "Enter production\n(guarded UI)")
    d.edge(prod, rec, "Physical / boot\nrecovery only", dashed=True)
    d.edge(rec, proto, "Back to editable", dashed=True)

    d.rect(
        120,
        450,
        1160,
        200,
        "Still available in production: ArtDmx (PrimusCentral and/or Eos) · ArtPoll discovery · PST (if teleTarget set) · Hello\n\n"
        "Not a multi-sender lease: use one commissioning authority, then lock. Do not infer ownership from last ArtDmx source.\n\n"
        "Management path: UI → HTTP facade → 0x8140 mutation → 0x8141 ACK/NACK → GET_CONFIG readback → /api/state",
        C["white"],
        C["line"],
        align="left",
        valign="top",
    )
    return d


def page_l2c() -> Diagram:
    d = Diagram("L2c Eos Control", 1400, 950)
    d.title(
        "L2c — Eos control paths (shipped vs future)",
        "Pixel path is primary for production looks; OSC cue bridge is optional and works today",
    )

    eos = d.rect(100, 180, 160, 80, "ETC Eos", C["eos_fill"], C["eos"], bold=True)
    prx = d.rect(700, 160, 220, 100, "Primus receivers\n(universes)", C["primus_fill"], C["primus"], bold=True)
    pc = d.rect(400, 360, 200, 90, "PrimusCentral\nOSC listener", C["primus_fill"], C["primus"], bold=True)
    dm = d.rect(100, 520, 200, 80, "DeviceManager\nmonitor_only", C["primus_fill"], C["primus"])

    d.edge(eos, prx, "① ArtDmx :6454\n(PRIMARY — shipped)")
    d.edge(eos, pc, "② OSC Tx\n/primus/cue/*\n(optional — shipped)", dashed=True, color=C["eos"])
    d.edge(pc, prx, "ArtDmx if Central\ndrives looks", dashed=True)
    d.edge(dm, prx, "PST monitor\n(no standing DMX)", color=C["shared"])

    d.rect(
        100,
        640,
        1200,
        160,
        "SHIPPED\n"
        "① Patch Primus as Art-Net fixtures in Eos; DM stays monitor_only (or Central not driving those IPs).\n"
        "② Eos Setup → OSC Tx → /primus/cue/goto · /primus/blackout (same as QLab path).\n\n"
        "FUTURE (not in these diagrams as shipped): Art-Net DMX-in to PrimusCentral · brightness busking · sACN bridges.",
        C["white"],
        C["eos"],
        align="left",
        valign="top",
    )
    return d


def page_l3a() -> Diagram:
    d = Diagram("L3a Radius Prototyping", 1400, 950)
    d.title(
        "L3a — RadiusCentral prototyping methods",
        "Source of truth: origin/radius-central (ignore V5 Radius bundle for this narrative)",
    )

    steps = [
        ("1 Discover", "Connect nodes\nRename · IP/DHCP"),
        ("2 Audio panel", "FTP SD browse\nUpload / mkdir\nPlay · loop · vol\nHello = tone"),
        ("3 Library", "Import WAVs\ninto sender audio/"),
        ("4 Cue Map", "Edit /cues.json\non device SD"),
        ("5 Net Log", "Art-Net / FTP\ntrace for tech"),
        ("6 Firmware", "Flash rv1 / rv2\nWiFi overrides"),
    ]
    x = 60
    prev = None
    for title, body in steps:
        cid = d.rect(x, 200, 200, 160, f"{title}\n\n{body}", C["radius_fill"], C["radius"], align="left", valign="top")
        if prev:
            d.edge(prev, cid)
        prev = cid
        x += 220

    d.rect(
        60,
        440,
        1280,
        160,
        "Identity (assumed Primus triad — partially implemented on branch):\n"
        "Character name · Performer name · Device (technical) name\n"
        "via ArtShowInfo 0x8210 + .radius_state.json / show-info store\n\n"
        "Transport note: radius-central Art-Net control on UDP 6456 so Primus/Eos can keep 6454.",
        C["white"],
        C["radius"],
        align="left",
        valign="top",
    )
    return d


def page_l3b() -> Diagram:
    d = Diagram("L3b Radius Production", 1400, 950)
    d.title(
        "L3b — Radius production workflow (operational, not firmware opMode)",
        "Show-ready path on radius-central — no Primus-style production lock yet",
    )

    a = d.rect(80, 180, 200, 100, "Project library\naudio/*.wav", C["radius_fill"], C["radius"], bold=True)
    b = d.rect(360, 180, 220, 100, "Audio Cues sheet\nper-device actions", C["radius_fill"], C["radius"], bold=True)
    c = d.rect(660, 180, 220, 100, "Sync All (push)\nFTP missing files", C["radius_fill"], C["radius"], bold=True)
    f = d.rect(960, 180, 220, 100, "Fire / OSC / cue#\nArtAudioCmd", C["warn_fill"], C["warn"], bold=True)
    d.edge(a, b)
    d.edge(b, c)
    d.edge(c, f)

    d.rect(
        80,
        360,
        500,
        220,
        "Production functions\n\n"
        "• Numbered cues (play/loop/stop, file, vol, duration)\n"
        "• Cue boards (named saved sets)\n"
        "• Device cue map play_cue / loop_cue\n"
        "• OSC fire + cue-map push/reload\n"
        "• PTR track telemetry confidence",
        C["white"],
        C["radius"],
        align="left",
        valign="top",
    )
    d.rect(
        620,
        360,
        560,
        220,
        "Contrast with Primus production\n\n"
        "Primus: receiver opMode locks commissioning fields.\n"
        "Radius: production = disciplined show workflow\n"
        "(library → sync → fire). Firmware lock is\n"
        "assumed future parallel if/when designed.",
        C["eos_fill"],
        C["eos"],
        align="left",
        valign="top",
    )
    return d


def page_l3c() -> Diagram:
    d = Diagram("L3c Naming Model", 1200, 700)
    d.title(
        "L3c — Shared naming model (Primus triad for both)",
        "Documented as the standard; Radius coverage may still be catching up on the branch",
    )
    d.rect(100, 160, 280, 120, "Character name\n(heading / cast role)", C["shared_fill"], C["shared"], bold=True)
    d.rect(450, 160, 280, 120, "Performer name\n(person wearing it)", C["shared_fill"], C["shared"], bold=True)
    d.rect(800, 160, 280, 120, "Device name\n(technical / NVS)", C["shared_fill"], C["shared"], bold=True)
    d.rect(
        100,
        340,
        980,
        160,
        "Wire: ArtShowInfo 0x8210 · feature flag S\n"
        "Sender: show_info_store → .primus_state.json or .radius_state.json\n"
        "UI: DeviceManager cards + Central sidebars — none of the three fields substitutes for another\n"
        "Hello: Primus = LED identify flash · Radius = test tone (+ volume)",
        C["white"],
        C["line"],
        align="left",
        valign="top",
    )
    return d


def page_l4() -> Diagram:
    d = Diagram("L4 Protocol Ports", 1500, 1000)
    d.title(
        "L4 — Ports, opcodes, and exclusivity",
        "Shared discovery language; exclusive payloads and (on radius-central) control port split",
    )

    rows = [
        (160, "UDP 6454", "Art-Net (Primus + Eos)\nArtPoll · ArtDmx · mgmt 0x8140/41\nlegacy 0x8100–0x8210", C["primus_fill"], C["primus"]),
        (320, "UDP 6456", "Art-Net (Radius branch)\nArtAudioCmd 0x8300\nArtFtpCmd 0x8301\nArtAudioStatus 0x8302", C["radius_fill"], C["radius"]),
        (480, "UDP 6455", "Telemetry\nPrimus PST · Radius PTR\n(+ PFP/battery variants)", C["shared_fill"], C["shared"]),
        (640, "HTTP", "Central / DeviceManager UIs\nJSON management + audio APIs", C["eos_fill"], C["eos"]),
        (800, "OSC / FTP", "OSC → PrimusCentral cues\nFTP → Radius SD (via ArtFtpCmd)", C["warn_fill"], C["warn"]),
    ]
    for y, title, body, fill, stroke in rows:
        d.rect(80, y, 200, 100, title, fill, stroke, bold=True)
        d.rect(320, y, 1100, 100, body, C["white"], stroke, align="left")

    d.rect(
        80,
        920,
        1340,
        40,
        "Capability tags: PV3CAP1|F:…|G:1P/1L  ·  PVRAD1|B:v1|F:RIHAS — Radius never on ArtDmx path",
        C["bg"],
        C["line"],
        font_size=11,
    )
    return d


def page_l5() -> Diagram:
    d = Diagram("L5 Comparison", 1500, 1000)
    d.title(
        "L5 — Side-by-side comparison board",
        "Shared spine · Primus-only · Radius-only",
    )

    d.rect(60, 120, 1380, 36, "SHARED SPINE", C["shared_fill"], C["shared"], bold=True, font_size=14)
    d.rect(
        60,
        170,
        1380,
        120,
        "Trusted LAN · Art-Net discovery · identity triad · IP config · Hello · DeviceManager mixed monitor ·\n"
        "packaged Central apps + firmware panels · commissioning/monitoring separated from show transport",
        C["white"],
        C["shared"],
        align="left",
    )

    d.rect(60, 330, 660, 36, "PRIMUS ONLY", C["primus_fill"], C["primus"], bold=True)
    d.rect(
        60,
        380,
        660,
        320,
        "• ArtDmx RGB pixels (:6454)\n"
        "• Clips → Looks → Cues (or Eos looks)\n"
        "• Management-v2 descriptors A0/A1\n"
        "• Firmware opMode prototype/production\n"
        "• PST explicit teleTarget\n"
        "• Eos pixel path + optional OSC cues\n"
        "• Output presets · virtual send resolution",
        C["white"],
        C["primus"],
        align="left",
        valign="top",
    )

    d.rect(780, 330, 660, 36, "RADIUS ONLY", C["radius_fill"], C["radius"], bold=True)
    d.rect(
        780,
        380,
        660,
        320,
        "• WAV / cue commands (:6456 on branch)\n"
        "• Library → Audio Cues → Sync All → Fire\n"
        "• SD cue map /cues.json\n"
        "• FTP file management\n"
        "• Operational production workflow\n"
        "• PTR track telemetry\n"
        "• OSC audio cue dispatch (branch)",
        C["white"],
        C["radius"],
        align="left",
        valign="top",
    )

    d.rect(
        60,
        740,
        1380,
        80,
        "They complement each other: same cast identity and stage network, different media. "
        "DeviceManager is the shared eyes; PrimusCentral/Eos and RadiusCentral are the hands for light and sound.",
        C["lan"],
        C["shared"],
        align="left",
    )
    return d


def page_d1_primus_block() -> Diagram:
    d = Diagram("D1 Primus Device Block", 1500, 1100)
    d.title(
        "D1 — Primus receiver device block (how one node works)",
        "ESP32 · WiFi Art-Net · two physical LED ports · NVS config · optional PST back-channel",
    )

    d.rect(60, 120, 200, 70, "WiFi STA\nArt-Net :6454", C["eos_fill"], C["eos"], bold=True)
    d.rect(300, 120, 220, 70, "Packet dispatch\n.ino loop", C["primus_fill"], C["primus"], bold=True)
    d.rect(560, 100, 200, 50, "ArtPollReply\nPV3CAP1|F:…|G:1P/L", C["shared_fill"], C["shared"])
    d.rect(560, 160, 200, 50, "ArtDmx → frame buf", C["primus_fill"], C["primus"])
    d.rect(560, 220, 200, 50, "mgmt 0x8140/41", C["warn_fill"], C["warn"])
    d.rect(560, 280, 200, 50, "legacy opcodes\n0x8100–0x8210", C["eos_fill"], C["eos"])

    d.rect(820, 120, 240, 100, "Receive mode\nsplit: A0=base A1=base+1\ncombined: A0‖A1 one univ", C["white"], C["primus"], align="left")
    d.rect(820, 240, 240, 100, "OutputDescriptor×2\nphys px · layout · virtual px\nNVS outDescAll + CRC", C["white"], C["primus"], align="left")
    d.rect(820, 360, 240, 80, "opMode\nprototype | production", C["warn_fill"], C["warn"], bold=True)
    d.rect(820, 460, 240, 80, "Identity NVS\ntech · character · performer", C["shared_fill"], C["shared"])
    d.rect(820, 560, 240, 70, "teleTarget IPv4\n(explicit only)", C["shared_fill"], C["shared"])

    d.rect(1120, 140, 300, 90, "A0 NeoPixel driver\n→ costume LEDs\n(phys wire order RGB)", C["primus_fill"], C["primus"], bold=True)
    d.rect(1120, 260, 300, 90, "A1 NeoPixel driver\n→ costume LEDs\n(Off = zero px slot)", C["primus_fill"], C["primus"], bold=True)
    d.rect(1120, 400, 300, 90, "PST v1 → :6455\n1 Hz if teleTarget set\nFPS · batt · lock · seq", C["lan"], C["shared"], bold=True)
    d.rect(1120, 520, 300, 110, "Hardware profiles\nv1 HUZZAH32 · v2 Feather\nv3 S3 TFT + A0/A1 PCB\n(+ battery / buttons / TFT)", C["white"], C["line"], align="left")

    d.rect(
        60,
        380,
        720,
        280,
        "Inside the critical path (show)\n\n"
        "1. ArtDmx arrives on configured universe(s)\n"
        "2. Bytes land in per-slot buffers in physical wire order\n"
        "3. Virtual send resolution: sender sent fewer RGB triplets;\n"
        "   receiver upscales to physical pixel count\n"
        "4. show() / NeoPixel write — latency-sensitive (~30 FPS)\n\n"
        "Grid rows/cols/serpentine are layout metadata for controllers;\n"
        "they do not reorder ArtDmx bytes on the wire.",
        C["white"],
        C["primus"],
        align="left",
        valign="top",
    )

    d.rect(
        60,
        700,
        1380,
        100,
        "Commissioning path is separate: management GET_CONFIG / SET_* persist to NVS, ACK/NACK, never selected by ArtDmx source.\n"
        "In production, commissioning mutations NACK/LOCKED; ArtDmx + discovery + PST + Hello stay live.",
        C["warn_fill"],
        C["warn"],
        align="left",
    )
    return d


def page_d2_primus_artdmx() -> Diagram:
    d = Diagram("D2 Primus ArtDmx Path", 1500, 1000)
    d.title(
        "D2 — Primus ArtDmx pixel path (device data plane)",
        "Eos or PrimusCentral → universes → slots → physical LEDs",
    )

    src = d.rect(60, 200, 180, 100, "ArtDmx source\nEos or\nPrimusCentral", C["eos_fill"], C["eos"], bold=True)
    univ = d.rect(300, 180, 200, 140, "Universe map\n\nSplit: U / U+1\nCombined: U only\n≤170 virt px total\nin combined", C["primus_fill"], C["primus"], align="left")
    buf = d.rect(560, 180, 220, 140, "Slot buffers\n\nA0 RGB…\nA1 RGB…\n(wire order)", C["white"], C["primus"], align="left")
    virt = d.rect(840, 180, 220, 140, "Virtual → physical\n\nUpscale each slot\nto descriptor\nphysical_pixels", C["shared_fill"], C["shared"], align="left")
    led = d.rect(1120, 180, 280, 140, "NeoPixel ports\n\nA0 costume strip/grid\nA1 costume strip/grid\nBrightness: sender-scaled RGB", C["primus_fill"], C["primus"], align="left")

    d.edge(src, univ, ":6454")
    d.edge(univ, buf)
    d.edge(buf, virt)
    d.edge(virt, led)

    d.rect(
        60,
        400,
        700,
        280,
        "Example — Badge (small_grid) + Collar (short_strip)\n\n"
        "• A0 descriptor: grid 8×4, serpentine, virt=1 (workshop)\n"
        "• A1 descriptor: strip 30 px, virt=30\n"
        "• Split base universe 100 → A0 on 100, A1 on 101\n"
        "• Eos patches two fixtures; DeviceManager only monitors PST\n\n"
        "Hello: management/legacy identify flash on LEDs\n"
        "(does not require standing ArtDmx connection)",
        C["white"],
        C["primus"],
        align="left",
        valign="top",
    )
    d.rect(
        800,
        400,
        600,
        280,
        "What the device does NOT do\n\n"
        "• No HTP/LTP merge of multiple ArtDmx sources\n"
        "• No learning teleTarget from packet source\n"
        "• No logical-coordinate ArtDmx reorder\n"
        "• No receiver brightness channel\n"
        "• Off slot still exists — zero physical pixels",
        C["eos_fill"],
        C["eos"],
        align="left",
        valign="top",
    )
    return d


def page_d3_primus_mgmt() -> Diagram:
    d = Diagram("D3 Primus Management Path", 1500, 1000)
    d.title(
        "D3 — Primus management / config plane (device control plane)",
        "0x8140 request → validate → NVS → 0x8141 ACK/NACK → GET_CONFIG authority",
    )

    client = d.rect(60, 180, 200, 90, "Commissioner\nDM / PrimusCentral\n(or direct Art-Net)", C["primus_fill"], C["primus"], bold=True)
    req = d.rect(320, 180, 200, 90, "0x8140 request\nop · reqId · payload", C["white"], C["primus"])
    gate = d.rect(580, 160, 220, 130, "Firmware gate\n\nopMode check\nvalidate payload\nreplay cache", C["warn_fill"], C["warn"], align="left")
    nvs = d.rect(860, 160, 240, 130, "NVS commit\n\noutDescAll CRC\nrecv · IP · identity\nopMode · teleTarget", C["shared_fill"], C["shared"], align="left")
    ack = d.rect(1160, 180, 240, 90, "0x8141 ACK/NACK\n(+ GET_CONFIG)", C["primus_fill"], C["primus"], bold=True)

    d.edge(client, req)
    d.edge(req, gate)
    d.edge(gate, nvs, "prototype OK")
    d.edge(gate, ack, "LOCKED / error", dashed=True, color=C["warn"])
    d.edge(nvs, ack)

    ops = [
        ("0x01 GET_CONFIG", "Full authoritative snapshot"),
        ("0x10 SET_OUTPUT_DESCRIPTORS", "Both A0/A1 atomically"),
        ("0x11 SET_TELEMETRY_TARGET", "Unicast or clear"),
        ("0x12 SET_OPERATING_MODE", "Enter production"),
        ("0x13 SET_RECEIVE_CONFIG", "Split/combined + base"),
        ("0x14 SET_IP_CONFIG", "DHCP / static"),
        ("0x15 SET_IDENTITY", "Tech + show names"),
        ("0x16 BOOT_WINDOW_UNLOCK", "V1/V2 recovery 60s"),
    ]
    x = 60
    for title, body in ops:
        d.rect(x, 380, 170, 100, f"{title}\n\n{body}", C["white"], C["primus"], font_size=10, align="left", valign="top")
        x += 180

    d.rect(
        60,
        520,
        1340,
        160,
        "Runtime after config\n\n"
        "• ArtPollReply advertises G:1P (prototype) or G:1L (locked); full descriptors only via GET_CONFIG\n"
        "• PST carries operating/lock state, unlock-window remaining, sequence, uptime, FPS×10, packet rate, RSSI, battery\n"
        "• Recovery: V3 D1 long-press · V1/V2 reboot + BOOT_WINDOW_UNLOCK within 60s — no casual remote unlock later",
        C["lan"],
        C["shared"],
        align="left",
        valign="top",
    )
    return d


def page_d4_radius_block() -> Diagram:
    d = Diagram("D4 Radius Device Block", 1500, 1100)
    d.title(
        "D4 — Radius receiver device block (how one node works)",
        "ESP32 · Music Maker (VS1053) · SD · Art-Net control :6456 (radius-central) · audio-first loop",
    )

    d.rect(60, 120, 200, 70, "WiFi STA\nArt-Net :6456", C["eos_fill"], C["eos"], bold=True)
    d.rect(300, 120, 220, 70, "Packet dispatch\nradius_receiver.ino", C["radius_fill"], C["radius"], bold=True)

    d.rect(560, 100, 220, 50, "ArtPollReply PVRAD1", C["shared_fill"], C["shared"])
    d.rect(560, 160, 220, 50, "ArtAudioCmd 0x8300", C["radius_fill"], C["radius"])
    d.rect(560, 220, 220, 50, "ArtFtpCmd 0x8301", C["radius_fill"], C["radius"])
    d.rect(560, 280, 220, 50, "ArtShowInfo 0x8210", C["shared_fill"], C["shared"])
    d.rect(560, 340, 220, 50, "ArtIPConfig / rename", C["eos_fill"], C["eos"])

    d.rect(820, 120, 260, 120, "audio.h\nVS1053 decode\nplay/loop/pause/vol\ntest_tone · cue#", C["radius_fill"], C["radius"], bold=True, align="left")
    d.rect(820, 260, 260, 100, "ftp.h\nFTP server on demand\nexclusive vs audio", C["white"], C["radius"], align="left")
    d.rect(820, 380, 260, 100, "cues.h\n/cues.json map\nloaded at boot (≤64)", C["white"], C["radius"], align="left")
    d.rect(820, 500, 260, 90, "telemetry.h\nPTR track · PFP rate\n(+ battery / status)", C["shared_fill"], C["shared"], align="left")

    d.rect(1120, 140, 300, 100, "SD card\nWAV files + /cues.json\nSPI bus (sdBusy)", C["radius_fill"], C["radius"], bold=True)
    d.rect(1120, 270, 300, 100, "VS1053 / amp\n→ costume speaker", C["radius_fill"], C["radius"], bold=True)
    d.rect(1120, 400, 300, 90, "UDP 6455 out\nPTR + PFP", C["lan"], C["shared"], bold=True)
    d.rect(1120, 520, 300, 110, "Hardware\nrv1 HUZZAH32 + MM\nrv2 S3 TFT + MM\n(+ display / buttons)", C["white"], C["line"], align="left")

    d.rect(
        60,
        420,
        720,
        240,
        "Loop priority (audio-first — not ArtDmx throughput)\n\n"
        "1. audioUpdate() — highest when playing\n"
        "2. ftpUpdate() — only when FTP active\n"
        "3. Art-Net UDP drain (bounded batch)\n"
        "4. WiFi check (throttled)\n"
        "5. Buttons / display\n"
        "6. PTR 1 Hz while playing · PFP 1 Hz\n\n"
        "Never receives ArtDmx. No LED pixel path.",
        C["white"],
        C["radius"],
        align="left",
        valign="top",
    )

    d.rect(
        60,
        700,
        1380,
        100,
        "SD / SPI contention: audio holds sdBusy → FTP refused while playing; play stops FTP first; FTP start stops audio first.\n"
        "Success metric = no audio dropouts, not frame latency.",
        C["warn_fill"],
        C["warn"],
        align="left",
    )
    return d


def page_d5_radius_audio() -> Diagram:
    d = Diagram("D5 Radius Audio Cue Path", 1500, 1050)
    d.title(
        "D5 — Radius audio & cue paths (device data plane)",
        "Filename play vs cue-number play · FTP content load · telemetry back",
    )

    rc = d.rect(60, 160, 180, 80, "RadiusCentral\nor OSC", C["radius_fill"], C["radius"], bold=True)
    cmd = d.rect(300, 140, 220, 120, "ArtAudioCmd\n\nplay/loop/stop/pause\nvolume · test_tone\nplay_cue / loop_cue", C["white"], C["radius"], align="left")
    lookup = d.rect(580, 140, 220, 120, "Cue lookup\n\ncmd 6/7 → cues.json\nelse filename in pkt", C["shared_fill"], C["shared"], align="left")
    sd = d.rect(860, 140, 200, 120, "SD open WAV\n(sdBusy)", C["radius_fill"], C["radius"], bold=True)
    vs = d.rect(1120, 140, 280, 120, "VS1053 stream\n→ speaker\noptional duration trim", C["radius_fill"], C["radius"], bold=True)

    d.edge(rc, cmd, ":6456")
    d.edge(cmd, lookup)
    d.edge(lookup, sd)
    d.edge(sd, vs)

    ftp_src = d.rect(60, 360, 180, 80, "Sync All /\nAudio panel", C["radius_fill"], C["radius"])
    ftp_cmd = d.rect(300, 360, 220, 80, "ArtFtpCmd start\n→ FTP session", C["white"], C["radius"])
    ftp_sd = d.rect(580, 360, 220, 80, "Write WAVs +\n/cues.json on SD", C["shared_fill"], C["shared"])
    d.edge(ftp_src, ftp_cmd)
    d.edge(ftp_cmd, ftp_sd)
    d.edge(ftp_sd, sd, "content ready", dashed=True)

    d.rect(
        860,
        320,
        540,
        200,
        "Telemetry while alive\n\n"
        "PTR → current track name + state\n"
        "PFP → packet-rate heartbeat\n"
        "ArtAudioStatus 0x8302 (branch)\n"
        "→ DeviceManager / RadiusCentral UI",
        C["lan"],
        C["shared"],
        align="left",
        valign="top",
    )

    d.rect(
        60,
        520,
        1340,
        200,
        "Two production trigger styles on-device\n\n"
        "A) Sender-authored Audio Cues: Central expands per-IP actions → ArtAudioCmd play/loop with filename\n"
        "B) Device cue map: Central/OSC sends play_cue(N) → firmware resolves N from /cues.json (reboot/reload to pick up map edits)\n\n"
        "Hello = cmd 5 test_tone at current volume (identify without LEDs).\n"
        "Identity triad via ArtShowInfo — same Character / Performer / Device model as Primus.",
        C["white"],
        C["radius"],
        align="left",
        valign="top",
    )
    return d


def page_d6_device_compare() -> Diagram:
    d = Diagram("D6 Device Comparison", 1500, 1000)
    d.title(
        "D6 — Device-level comparison (one Primus node vs one Radius node)",
        "Same LAN citizen · different critical path and storage",
    )

    d.rect(60, 120, 680, 36, "PRIMUS RECEIVER", C["primus_fill"], C["primus"], bold=True)
    d.rect(
        60,
        170,
        680,
        420,
        "Identity tag: PV3CAP1\n"
        "Control/data port: :6454\n"
        "Telemetry: PST → :6455 (opt-in target)\n\n"
        "Critical path: ArtDmx assemble → NeoPixel show()\n"
        "Storage: NVS (descriptors, IP, names, opMode, teleTarget)\n"
        "Outputs: A0 + A1 LED ports (Off valid)\n"
        "Show lock: firmware production mode\n"
        "Identify: LED flash\n\n"
        "Does not: play audio, open FTP, hold SD",
        C["white"],
        C["primus"],
        align="left",
        valign="top",
    )

    d.rect(800, 120, 640, 36, "RADIUS RECEIVER", C["radius_fill"], C["radius"], bold=True)
    d.rect(
        800,
        170,
        640,
        420,
        "Identity tag: PVRAD1\n"
        "Control port: :6456 (radius-central)\n"
        "Telemetry: PTR/PFP → :6455\n\n"
        "Critical path: audioUpdate → VS1053 + SD SPI\n"
        "Storage: SD WAVs + /cues.json (+ NVS net/identity)\n"
        "Outputs: speaker via Music Maker\n"
        "Show lock: operational (no opMode yet)\n"
        "Identify: test tone\n\n"
        "Does not: accept ArtDmx or drive LEDs",
        C["white"],
        C["radius"],
        align="left",
        valign="top",
    )

    d.rect(
        60,
        640,
        1380,
        120,
        "Shared device behaviors: WiFi STA · ArtPoll discovery · rename · IP config · show-info names · Hello · firmware flash from Centrals/DeviceManager.\n"
        "Cohabitation rule: Primus/Eos own :6454 pixels; Radius owns :6456 audio control; both may emit :6455 telemetry to an explicit monitor (often DeviceManager).",
        C["lan"],
        C["shared"],
        align="left",
    )
    return d


def main():
    pages = [
        page_00_index(),
        page_l0(),
        page_l1(),
        page_l2a(),
        page_l2b(),
        page_l2c(),
        page_l3a(),
        page_l3b(),
        page_l3c(),
        page_l4(),
        page_l5(),
        page_d1_primus_block(),
        page_d2_primus_artdmx(),
        page_d3_primus_mgmt(),
        page_d4_radius_block(),
        page_d5_radius_audio(),
        page_d6_device_compare(),
    ]
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<mxfile host="app.diagrams.net" agent="PrimusV3-docs" version="22.1.0" type="device" '
        f'pages="{len(pages)}">\n'
        + "\n".join(p.to_xml() for p in pages)
        + "\n</mxfile>\n"
    )
    OUT.write_text(xml, encoding="utf-8")
    print(f"Wrote {OUT} ({len(pages)} pages)")


if __name__ == "__main__":
    main()
