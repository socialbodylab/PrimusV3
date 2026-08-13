/** Structured content for Primus + Radius systems site (greyscale presentation). */

export const blueprint = {
  columns: ["Flash / prep", "Tech", "Half hour", "Show GO", "Strike"],
  rows: [
    {
      role: "Stage mgr",
      cells: [
        "DeviceManager online\nmonitor_only",
        "Identity triad set\nHello checks",
        "Confirm PST/PTR\nhealth",
        "Watch only\nno connect_all",
        "Note faults\nfor next day",
      ],
    },
    {
      role: "LD / Eos",
      cells: [
        "Patch Primus\nuniverses",
        "Focus looks\non bodies",
        "Cue stack\nready",
        "ArtDmx :6454\nprimary path",
        "Park / blackout",
      ],
    },
    {
      role: "Sound",
      cells: [
        "Import library\nRadiusCentral",
        "Build cues\nSync All",
        "Test fire\ncue map check",
        "Fire / OSC\n:6456",
        "Pull notes\nnot SD wipe",
      ],
    },
    {
      role: "Wardrobe",
      cells: [
        "Flash boards\nv1–v3 / rv*",
        "Names on\ncostume cards",
        "Enter Primus\nproduction lock",
        "Bodies on stage\nHello if lost",
        "Collect / charge",
      ],
    },
  ],
};

export const lockMatrix = {
  columns: [
    "Primus · Prototype",
    "Primus · Production",
    "Radius · Prep",
    "Radius · Show",
  ],
  rows: [
    ["Character / performer / device name", "open", "locked", "open", "open"],
    ["Static IP / DHCP", "open", "locked", "open", "open"],
    ["LED geometry A0/A1", "open", "locked", "na", "na"],
    ["Receive mode / universe", "open", "locked", "na", "na"],
    ["Telemetry target (PST)", "open", "locked", "na", "na"],
    ["ArtDmx pixel stream", "open", "open", "na", "na"],
    ["Hello identify", "open", "open", "open", "open"],
    ["Discovery / monitor", "open", "open", "open", "open"],
    ["Audio play / cue fire", "na", "na", "open", "open"],
    ["FTP / Sync All / cue map write", "na", "na", "open", "open"],
  ],
};

export const recipes = {
  light: [
    "Author look (PrimusCentral clips/looks) or patch look in Eos",
    "Commission receiver: names, IP, A0/A1, universe, teleTarget",
    "Verify Hello + ArtDmx + PST",
    "Enter production lock (Primus firmware)",
    "Drive show: Eos ArtDmx and/or PrimusCentral cues",
  ],
  sound: [
    "Import WAVs into RadiusCentral project library",
    "Author Audio Cues with per-device actions",
    "Sync All — push missing files to SD",
    "Optional: write /cues.json cue map on device",
    "Fire cues (Central / OSC / play_cue) on :6456",
  ],
};

export const apiRows = [
  {
    goal: "Discover / sync devices",
    product: "both",
    surface: "HTTP",
    path: "POST /api/discover · /api/devices/sync",
    mode: "any",
  },
  {
    goal: "Rename device",
    product: "both",
    surface: "HTTP",
    path: "POST /api/rename_node",
    mode: "prototype*",
  },
  {
    goal: "Character / performer names",
    product: "both",
    surface: "HTTP",
    path: "POST /api/device_show_info",
    mode: "prototype*",
  },
  {
    goal: "Identify (Hello)",
    product: "both",
    surface: "HTTP",
    path: "POST /api/hello_device",
    mode: "any",
  },
  {
    goal: "Static IP / DHCP",
    product: "both",
    surface: "HTTP",
    path: "POST /api/set_device_ip · /api/revert_device_dhcp",
    mode: "prototype*",
  },
  {
    goal: "LED geometry / virtual px",
    product: "primus",
    surface: "HTTP",
    path: "POST /api/apply_device_output_descriptor · set_device_output",
    mode: "prototype",
  },
  {
    goal: "Receive mode / universe",
    product: "primus",
    surface: "HTTP",
    path: "POST /api/set_device_receive_mode",
    mode: "prototype",
  },
  {
    goal: "PST telemetry target",
    product: "primus",
    surface: "HTTP",
    path: "POST /api/set_device_telemetry_target",
    mode: "prototype",
  },
  {
    goal: "Enter production lock",
    product: "primus",
    surface: "HTTP",
    path: "POST /api/enter_device_production_mode",
    mode: "commission",
  },
  {
    goal: "Boot-window unlock",
    product: "primus",
    surface: "HTTP",
    path: "POST /api/unlock_device_boot_window",
    mode: "recovery",
  },
  {
    goal: "Drive pixels",
    product: "primus",
    surface: "Art-Net",
    path: "ArtDmx 0x5000 :6454 (Eos or PrimusCentral)",
    mode: "show",
  },
  {
    goal: "Cue / blackout via OSC",
    product: "primus",
    surface: "OSC",
    path: "/primus/cue/* · /primus/blackout",
    mode: "show",
  },
  {
    goal: "Audio transport",
    product: "radius",
    surface: "HTTP",
    path: "POST /api/audio/cmd",
    mode: "any",
  },
  {
    goal: "Fire audio cue sheet",
    product: "radius",
    surface: "HTTP",
    path: "POST /api/audio_cues/fire",
    mode: "show",
  },
  {
    goal: "Sync library to SD",
    product: "radius",
    surface: "HTTP",
    path: "POST /api/audio_sync",
    mode: "prep",
  },
  {
    goal: "Read/write cue map",
    product: "radius",
    surface: "HTTP",
    path: "GET/POST /api/audio/cue_map",
    mode: "prep",
  },
  {
    goal: "ArtAudioCmd wire",
    product: "radius",
    surface: "Art-Net",
    path: "0x8300 cmds 0–7 :6456",
    mode: "show",
  },
  {
    goal: "FTP gate",
    product: "radius",
    surface: "Art-Net",
    path: "0x8301 ArtFtpCmd → TCP 21",
    mode: "prep",
  },
  {
    goal: "Firmware flash",
    product: "both",
    surface: "HTTP",
    path: "POST /api/firmware/jobs",
    mode: "prep",
  },
];

export const thesis =
  "One performer · two media · one LAN — show traffic and setup traffic must not be confused.";
