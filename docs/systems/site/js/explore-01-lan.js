/**
 * Explore 01 — Show LAN drawn four ways.
 * Subject: who may talk to which receiver, on which port / plane / phase.
 */

const SOURCES = [
  { id: "eos", label: "Eos" },
  { id: "pc", label: "PrimusCentral" },
  { id: "dm", label: "DeviceManager" },
  { id: "rc", label: "RadiusCentral" },
];

const TARGETS = [
  { id: "prx", label: "Primus rx" },
  { id: "rrx", label: "Radius rx" },
];

/** plane: s show | u setup | w watch */
const EDGES = [
  { from: "eos", to: "prx", plane: "s", port: ":6454", payload: "ArtDmx pixels", optional: false },
  { from: "eos", to: "pc", plane: "s", port: "OSC", payload: "cue / blackout", optional: true, via: true },
  { from: "pc", to: "prx", plane: "s", port: ":6454", payload: "ArtDmx pixels", optional: false },
  { from: "pc", to: "prx", plane: "u", port: ":6457", payload: "mgmt 0x8140 · rename · IP", optional: false },
  { from: "pc", to: "prx", plane: "u", port: "HTTP", payload: "JSON facade", optional: false },
  { from: "dm", to: "prx", plane: "u", port: "HTTP", payload: "sync · Hello · commission", optional: false },
  { from: "dm", to: "prx", plane: "u", port: ":6457", payload: "mgmt (transient)", optional: true },
  { from: "dm", to: "rrx", plane: "u", port: "HTTP", payload: "identity · Hello · IP", optional: false },
  { from: "rc", to: "rrx", plane: "s", port: ":6456", payload: "ArtAudioCmd", optional: false },
  { from: "rc", to: "rrx", plane: "u", port: ":6457", payload: "ArtFtpCmd → TCP 21", optional: false },
  { from: "rc", to: "rrx", plane: "u", port: "HTTP", payload: "audio_sync · cue map", optional: false },
  { from: "prx", to: "dm", plane: "w", port: ":6455", payload: "PST (teleTarget only)", optional: false, reverse: true },
  { from: "rrx", to: "dm", plane: "w", port: ":6455", payload: "PTR / PFP", optional: false, reverse: true },
  { from: "prx", to: "pc", plane: "w", port: ":6455", payload: "PST if targeted", optional: true, reverse: true },
];

const PHASES = ["Flash", "Tech", "Half hour", "Show GO", "Strike"];

/** channel × phase → { apps, intensity: primary|soft|quiet } */
const CHANNELS = [
  {
    id: "artdmx",
    label: ":6454 ArtDmx",
    sub: "pixels → Primus",
    cells: {
      Flash: { apps: "—", intensity: "quiet" },
      Tech: { apps: "Eos / PC", intensity: "soft" },
      "Half hour": { apps: "Eos / PC", intensity: "soft" },
      "Show GO": { apps: "Eos · PC", intensity: "primary" },
      Strike: { apps: "park", intensity: "soft" },
    },
  },
  {
    id: "mgmt",
    label: ":6457 Setup",
    sub: "0x8140 / config",
    cells: {
      Flash: { apps: "PC / DM", intensity: "primary" },
      Tech: { apps: "PC / DM", intensity: "primary" },
      "Half hour": { apps: "Hello only", intensity: "soft" },
      "Show GO": { apps: "locked*", intensity: "quiet" },
      Strike: { apps: "notes", intensity: "quiet" },
    },
  },
  {
    id: "audio",
    label: ":6456 ArtAudio",
    sub: "play / cue → Radius",
    cells: {
      Flash: { apps: "—", intensity: "quiet" },
      Tech: { apps: "RC test", intensity: "soft" },
      "Half hour": { apps: "RC", intensity: "soft" },
      "Show GO": { apps: "RC · OSC", intensity: "primary" },
      Strike: { apps: "—", intensity: "quiet" },
    },
  },
  {
    id: "ftp",
    label: ":6457 FTP gate",
    sub: "SD content load",
    cells: {
      Flash: { apps: "RC Sync", intensity: "primary" },
      Tech: { apps: "RC Sync", intensity: "primary" },
      "Half hour": { apps: "avoid", intensity: "quiet" },
      "Show GO": { apps: "quiet", intensity: "quiet" },
      Strike: { apps: "pull notes", intensity: "soft" },
    },
  },
  {
    id: "tele",
    label: ":6455 PST/PTR",
    sub: "→ DeviceManager",
    cells: {
      Flash: { apps: "DM", intensity: "soft" },
      Tech: { apps: "DM", intensity: "primary" },
      "Half hour": { apps: "DM", intensity: "primary" },
      "Show GO": { apps: "DM watch", intensity: "primary" },
      Strike: { apps: "DM", intensity: "soft" },
    },
  },
  {
    id: "http",
    label: "HTTP API",
    sub: "local Centrals / DM",
    cells: {
      Flash: { apps: "all", intensity: "primary" },
      Tech: { apps: "all", intensity: "primary" },
      "Half hour": { apps: "DM / fire", intensity: "soft" },
      "Show GO": { apps: "fire only", intensity: "soft" },
      Strike: { apps: "DM", intensity: "soft" },
    },
  },
  {
    id: "osc",
    label: "OSC",
    sub: "cues into Centrals",
    cells: {
      Flash: { apps: "—", intensity: "quiet" },
      Tech: { apps: "patch", intensity: "soft" },
      "Half hour": { apps: "check", intensity: "soft" },
      "Show GO": { apps: "Eos → PC · fire", intensity: "primary" },
      Strike: { apps: "—", intensity: "quiet" },
    },
  },
];

const SCALE_ROWS = [
  {
    id: "light",
    cast: { label: "Light on body", meta: "Primus" },
    apps: { label: "Eos or PrimusCentral", meta: "show driver" },
    ports: { label: "UDP :6454", meta: "ArtDmx" },
    ops: {
      label: "0x5000 ArtDmx",
      meta: "universes",
      detail: [
        "Console or PrimusCentral streams RGB universes to Primus receivers.",
        "DeviceManager never owns this path (monitor_only skips connect_all).",
        "Production lock does not close ArtDmx.",
      ],
    },
  },
  {
    id: "sound",
    cast: { label: "Sound on body", meta: "Radius" },
    apps: { label: "RadiusCentral", meta: "show driver" },
    ports: { label: "UDP :6456", meta: "ArtAudioCmd" },
    ops: {
      label: "0x8300 cmds 0–7",
      meta: "play / cue",
      detail: [
        "Fire expands cue sheet to per-IP ArtAudioCmd.",
        "play_cue(N) can hit device /cues.json instead.",
        "Never shares Primus ArtDmx port.",
      ],
    },
  },
  {
    id: "commission",
    cast: { label: "Costume identity", meta: "shared triad" },
    apps: { label: "DeviceManager · Centrals", meta: "setup" },
    ports: { label: "HTTP + :6454/:6456", meta: "mgmt / show info" },
    ops: {
      label: "0x8140 · 0x8210 · rename",
      meta: "NVS",
      detail: [
        "Character · Performer · Device are independent fields.",
        "Primus production opMode NACKs commissioning writes.",
        "Radius has no firmware lock yet — operational discipline.",
      ],
    },
  },
  {
    id: "content",
    cast: { label: "SD library", meta: "Radius only" },
    apps: { label: "RadiusCentral", meta: "Sync All" },
    ports: { label: "ArtFtpCmd → TCP 21", meta: ":6456 gate" },
    ops: {
      label: "0x8301 ArtFtpCmd",
      meta: "sdBusy",
      detail: [
        "FTP and audio never share the SPI bus (sdBusy).",
        "Tech/flash phase — not Show GO.",
        "Cue map /cues.json is a separate write path.",
      ],
    },
  },
  {
    id: "watch",
    cast: { label: "Health on stage", meta: "SM board" },
    apps: { label: "DeviceManager", meta: "monitor_only" },
    ports: { label: "UDP :6455", meta: "PST / PTR" },
    ops: {
      label: "PST v1 · PTR · PFP",
      meta: "telemetry",
      detail: [
        "Primus PST only to explicit teleTarget — never learned from Eos ArtDmx.",
        "Mixed monitor: Primus + Radius cards; Radius never gets ArtDmx.",
        "Watch lane does not fire cues.",
      ],
    },
  },
];

function planeLetter(p) {
  return { s: "S", u: "U", w: "W" }[p] || p;
}

function labelOf(list, id) {
  return list.find((x) => x.id === id)?.label || id;
}

function edgesForCell(from, to) {
  return EDGES.filter((e) => {
    if (e.via) return false;
    if (e.reverse) return e.from === to && e.to === from;
    return e.from === from && e.to === to;
  });
}

function renderAdj() {
  const root = document.getElementById("adj-root");
  if (!root) return;
  const table = document.createElement("table");
  table.className = "adj";

  const thead = document.createElement("thead");
  const hr = document.createElement("tr");
  hr.appendChild(document.createElement("th")).textContent = "From \\ To";
  for (const t of TARGETS) {
    hr.appendChild(document.createElement("th")).textContent = t.label;
  }
  // special: Eos→PC optional OSC shown as note under Primus? Keep matrix receiver-only.
  thead.appendChild(hr);
  table.appendChild(thead);

  const tbody = document.createElement("tbody");
  for (const s of SOURCES) {
    const tr = document.createElement("tr");
    const th = document.createElement("th");
    th.scope = "row";
    th.textContent = s.label;
    tr.appendChild(th);
    for (const t of TARGETS) {
      const td = document.createElement("td");
      const edges = edgesForCell(s.id, t.id);
      if (!edges.length) {
        td.className = "empty";
        td.textContent = "—";
      } else {
        for (const e of edges) {
          const chip = document.createElement("div");
          chip.className = `edge-chip${e.optional ? " optional" : ""}`;
          chip.innerHTML = `
            <span class="plane ${e.plane}" title="${e.plane}">${planeLetter(e.plane)}</span>
            <span class="edge-meta">
              <span class="port">${e.port}</span>
              <span class="payload">${e.payload}</span>
            </span>`;
          td.appendChild(chip);
        }
      }
      tr.appendChild(td);
    }
    tbody.appendChild(tr);
  }
  table.appendChild(tbody);
  root.appendChild(table);

  // OSC footnote row
  const note = document.createElement("p");
  note.className = "note";
  note.style.padding = "0.65rem 0.85rem";
  note.style.margin = "0";
  note.style.borderTop = "1px solid var(--soft)";
  note.textContent =
    "Off-matrix: Eos → PrimusCentral via OSC (optional cue path). Not a receiver wire.";
  root.appendChild(note);
}

function renderPlanes() {
  const root = document.getElementById("planes-root");
  if (!root) return;

  const specs = [
    {
      key: "s",
      title: "Show",
      sub: "Drive media on the body",
      foot: "Fat path · owns the cue",
    },
    {
      key: "u",
      title: "Setup",
      sub: "Commission · sync · identity",
      foot: "Thin path · not during GO",
    },
    {
      key: "w",
      title: "Watch",
      sub: "Telemetry into DeviceManager",
      foot: "Read-only · never owns cue",
    },
  ];

  for (const spec of specs) {
    const panel = document.createElement("div");
    panel.className = "plane-panel";
    panel.innerHTML = `<h3>${spec.title}</h3><p class="sub">${spec.sub}</p>`;

    const edges = EDGES.filter((e) => e.plane === spec.key && !e.via);
    for (const e of edges) {
      const row = document.createElement("div");
      row.className = `plane-edge${e.optional ? " optional" : ""}`;
      const fromL = labelOf([...SOURCES, ...TARGETS], e.from);
      const toL = labelOf([...SOURCES, ...TARGETS], e.to);
      row.innerHTML = `
        <span class="from">${fromL}</span>
        <span class="mid">${e.port}</span>
        <span class="to">${toL}</span>`;
      panel.appendChild(row);
    }

    const foot = document.createElement("p");
    foot.className = "plane-foot";
    foot.textContent = spec.foot;
    panel.appendChild(foot);
    root.appendChild(panel);
  }
}

function renderScales() {
  const root = document.getElementById("scales-root");
  const detail = document.getElementById("scale-detail");
  if (!root) return;

  const cols = [
    { key: "cast", title: "1 · Cast" },
    { key: "apps", title: "2 · Apps" },
    { key: "ports", title: "3 · Ports" },
    { key: "ops", title: "4 · Opcodes" },
  ];

  let selected = SCALE_ROWS[0].id;

  const paint = () => {
    root.innerHTML = "";
    for (const col of cols) {
      const wrap = document.createElement("div");
      wrap.className = "scale-col";
      wrap.innerHTML = `<h3>${col.title}</h3>`;
      for (const row of SCALE_ROWS) {
        const cell = row[col.key];
        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = "scale-item";
        btn.dataset.id = row.id;
        if (row.id === selected) btn.setAttribute("aria-current", "true");
        btn.innerHTML = `<span class="label">${cell.label}</span><span class="meta">${cell.meta}</span>`;
        btn.addEventListener("click", () => {
          selected = row.id;
          paint();
        });
        wrap.appendChild(btn);
      }
      root.appendChild(wrap);
    }

    if (detail) {
      const row = SCALE_ROWS.find((r) => r.id === selected);
      detail.hidden = false;
      detail.innerHTML = `
        <h4>${row.cast.label} → ${row.ops.label}</h4>
        <ul>${row.ops.detail.map((d) => `<li>${d}</li>`).join("")}</ul>`;
    }
  };

  paint();
}

function renderChannels() {
  const root = document.getElementById("chan-root");
  if (!root) return;
  const table = document.createElement("table");
  table.className = "chan";

  const thead = document.createElement("thead");
  const hr = document.createElement("tr");
  hr.appendChild(document.createElement("th")).textContent = "Channel";
  for (const p of PHASES) hr.appendChild(document.createElement("th")).textContent = p;
  thead.appendChild(hr);
  table.appendChild(thead);

  const tbody = document.createElement("tbody");
  for (const ch of CHANNELS) {
    const tr = document.createElement("tr");
    const th = document.createElement("th");
    th.innerHTML = `${ch.label}<span class="sub">${ch.sub}</span>`;
    tr.appendChild(th);
    for (const p of PHASES) {
      const td = document.createElement("td");
      const cell = ch.cells[p];
      const span = document.createElement("span");
      if (cell.intensity === "quiet") {
        span.className = "mark quiet";
        span.textContent = cell.apps === "—" ? "·" : cell.apps;
      } else if (cell.intensity === "soft") {
        span.className = "mark soft";
        span.textContent = cell.apps;
      } else {
        span.className = "mark";
        span.textContent = cell.apps;
      }
      td.appendChild(span);
      tr.appendChild(td);
    }
    tbody.appendChild(tr);
  }
  table.appendChild(tbody);
  root.appendChild(table);
}

renderAdj();
renderPlanes();
renderScales();
renderChannels();
