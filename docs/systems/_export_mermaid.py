#!/usr/bin/env python3
"""Export Mermaid mirrors from SYSTEMS_OUTLINE.md to png/ and svg/."""

from __future__ import annotations

import re
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUTLINE = ROOT / "SYSTEMS_OUTLINE.md"
PNG = ROOT / "png"
SVG = ROOT / "svg"

# Outline ```mermaid``` blocks in document order → export stems.
OUTLINE_STEMS = [
    "00-overview-map",
    "L0-context",
    "L2a-devicemanager-params",
    "L2b-prototype-production",
    "L2-management-sequence",
    "L2c-eos-control",
    "L3a-radius-prototyping",
    "L3b-radius-production",
    "L3c-naming-model",
    "D1-primus-device-block",
    "D2-primus-artdmx-path",
    "D4-radius-device-block",
    "D5-radius-audio-cue-path",
    "L4-protocol-ports",
    "L5-comparison",
]

EXTRA_SYNTH = {
    "L1-containers": """flowchart TB
  subgraph apps [ControlApps]
    PC[PrimusCentral]
    DM[DeviceManager]
    RC[RadiusCentral]
    EOS[ETC_Eos]
  end
  subgraph rx [Receivers]
    PRx[Primus_PV3CAP1]
    RRx[Radius_PVRAD1]
  end
  subgraph data [Persistence]
    PS[.primus_state_clips_looks]
    RS[.radius_state_audio_cues]
    SD[Device_SD_cues_json]
  end
  PC --> PRx
  DM --> PRx
  DM --> RRx
  RC --> RRx
  EOS --> PRx
  PC --- PS
  RC --- RS
  RRx --- SD
""",
    "D3-primus-management-path": """flowchart LR
  Client[Commissioner_DM_or_Central] --> Req[Req_0x8140]
  Req --> Gate{opMode_gate}
  Gate -->|prototype| NVS[NVS_CRC_commit]
  Gate -->|production| NACK[NACK_LOCKED]
  NVS --> Ack[Reply_0x8141]
  NACK --> Ack
  Ack --> Get[GET_CONFIG_authority]
""",
    "D6-device-comparison": """flowchart TB
  subgraph primus [PrimusNode]
    PTag[PV3CAP1]
    PPath[ArtDmx_to_NeoPixel]
    PStore[NVS_descriptors]
    PLock[opMode_lock]
  end
  subgraph radius [RadiusNode]
    RTag[PVRAD1]
    RPath[audioUpdate_to_VS1053]
    RStore[SD_WAVs_cues_json]
    RLock[Operational_workflow]
  end
  Shared[Shared_WiFi_discovery_identity_Hello_IP]
  Shared --> primus
  Shared --> radius
""",
}

EXPORT_ORDER = [
    "00-overview-map",
    "L0-context",
    "L1-containers",
    "L2a-devicemanager-params",
    "L2b-prototype-production",
    "L2c-eos-control",
    "L2-management-sequence",
    "L3a-radius-prototyping",
    "L3b-radius-production",
    "L3c-naming-model",
    "L4-protocol-ports",
    "L5-comparison",
    "D1-primus-device-block",
    "D2-primus-artdmx-path",
    "D3-primus-management-path",
    "D4-radius-device-block",
    "D5-radius-audio-cue-path",
    "D6-device-comparison",
]


def extract_mermaid_blocks(text: str) -> list[str]:
    return re.findall(r"```mermaid\n(.*?)```", text, flags=re.DOTALL)


def export_one(stem: str, source: str) -> None:
    PNG.mkdir(parents=True, exist_ok=True)
    SVG.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        mmd = Path(tmp) / f"{stem}.mmd"
        mmd.write_text(source.strip() + "\n", encoding="utf-8")
        for fmt, out_dir in (("svg", SVG), ("png", PNG)):
            out = out_dir / f"{stem}.{fmt}"
            cmd = [
                "npx",
                "--yes",
                "@mermaid-js/mermaid-cli",
                "-i",
                str(mmd),
                "-o",
                str(out),
                "-b",
                "transparent",
            ]
            if fmt == "png":
                cmd.extend(["-s", "2"])
            subprocess.run(cmd, check=True, capture_output=True)
            print(f"  wrote {out.relative_to(ROOT.parent.parent)}")


def main() -> None:
    blocks = extract_mermaid_blocks(OUTLINE.read_text(encoding="utf-8"))
    if len(blocks) != len(OUTLINE_STEMS):
        raise SystemExit(
            f"Expected {len(OUTLINE_STEMS)} mermaid blocks, found {len(blocks)}"
        )

    mapping = dict(zip(OUTLINE_STEMS, blocks))
    mapping.update(EXTRA_SYNTH)

    for stem in EXPORT_ORDER:
        print(f"export {stem}")
        export_one(stem, mapping[stem])

    print("done")


if __name__ == "__main__":
    main()
