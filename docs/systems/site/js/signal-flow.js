/** Interactive cue-moment signal flow (SVG). */

const FLOWS = {
  light: {
    title: "Light cue",
    nodes: [
      { id: "eos", label: "Eos / console", x: 40, y: 120, tone: "" },
      { id: "pc", label: "PrimusCentral\n(optional)", x: 220, y: 40, tone: "dim" },
      { id: "udp", label: "UDP :6454\nArtDmx", x: 220, y: 200, tone: "" },
      { id: "rx", label: "Primus\nreceiver", x: 420, y: 120, tone: "" },
      { id: "led", label: "Costume\nLEDs", x: 600, y: 120, tone: "" },
      { id: "pst", label: "PST →\nDeviceManager", x: 420, y: 260, tone: "monitor" },
    ],
    edges: [
      ["eos", "udp", ""],
      ["pc", "udp", "thin"],
      ["udp", "rx", ""],
      ["rx", "led", ""],
      ["rx", "pst", "thin"],
    ],
    note: "Show path is ArtDmx. DeviceManager watches PST; it does not own the cue.",
  },
  sound: {
    title: "Sound cue",
    nodes: [
      { id: "rc", label: "RadiusCentral\n/ OSC", x: 60, y: 100, tone: "" },
      { id: "udp", label: "UDP :6456\nArtAudioCmd", x: 260, y: 100, tone: "" },
      { id: "rx", label: "Radius\nreceiver", x: 460, y: 100, tone: "" },
      { id: "spk", label: "Costume\naudio", x: 640, y: 100, tone: "" },
      { id: "ptr", label: "PTR track\ntelemetry", x: 460, y: 240, tone: "monitor" },
    ],
    edges: [
      ["rc", "udp", ""],
      ["udp", "rx", ""],
      ["rx", "spk", ""],
      ["rx", "ptr", "thin"],
    ],
    note: "Audio never shares Primus ArtDmx port. Prep (FTP/Sync) is a different phase.",
  },
  together: {
    title: "Same cue · both media",
    nodes: [
      { id: "sm", label: "Stage mgr\ncue call", x: 40, y: 140, tone: "" },
      { id: "eos", label: "Eos\nArtDmx", x: 220, y: 40, tone: "" },
      { id: "rc", label: "Radius\nfire", x: 220, y: 240, tone: "" },
      { id: "body", label: "Performer\nbody", x: 460, y: 140, tone: "" },
      { id: "dm", label: "DeviceManager\nwatch", x: 640, y: 140, tone: "monitor" },
    ],
    edges: [
      ["sm", "eos", ""],
      ["sm", "rc", ""],
      ["eos", "body", ""],
      ["rc", "body", ""],
      ["body", "dm", "thin"],
    ],
    note: "Parallel show streams. Monitoring is read-only on the show network.",
  },
};

function nodePos(n) {
  return { x: n.x + 70, y: n.y + 28 };
}

function renderFlow(svg, key) {
  const flow = FLOWS[key];
  const byId = Object.fromEntries(flow.nodes.map((n) => [n.id, n]));
  svg.innerHTML = "";
  svg.setAttribute("viewBox", "0 0 760 320");

  const defs = document.createElementNS("http://www.w3.org/2000/svg", "defs");
  defs.innerHTML = `
    <marker id="arrow" markerWidth="8" markerHeight="8" refX="7" refY="3" orient="auto">
      <path d="M0,0 L8,3 L0,6 Z"/>
    </marker>`;
  svg.appendChild(defs);

  for (const [a, b, kind] of flow.edges) {
    const pa = nodePos(byId[a]);
    const pb = nodePos(byId[b]);
    const line = document.createElementNS("http://www.w3.org/2000/svg", "line");
    line.setAttribute("x1", pa.x);
    line.setAttribute("y1", pa.y);
    line.setAttribute("x2", pb.x);
    line.setAttribute("y2", pb.y);
    line.setAttribute("class", `arrow${kind ? ` ${kind}` : ""}`);
    line.setAttribute("marker-end", "url(#arrow)");
    svg.appendChild(line);
  }

  for (const n of flow.nodes) {
    const g = document.createElementNS("http://www.w3.org/2000/svg", "g");
    g.setAttribute("transform", `translate(${n.x},${n.y})`);
    const rect = document.createElementNS("http://www.w3.org/2000/svg", "rect");
    rect.setAttribute("width", "140");
    rect.setAttribute("height", "56");
    rect.setAttribute("rx", "2");
    rect.setAttribute("class", `node-box${n.tone ? ` ${n.tone}` : ""}`);
    g.appendChild(rect);
    const lines = n.label.split("\n");
    lines.forEach((line, i) => {
      const t = document.createElementNS("http://www.w3.org/2000/svg", "text");
      t.setAttribute("x", "70");
      t.setAttribute("y", String(22 + i * 14));
      t.setAttribute("text-anchor", "middle");
      if (n.tone === "monitor") t.setAttribute("class", "label-mute");
      t.textContent = line;
      g.appendChild(t);
    });
    svg.appendChild(g);
  }

  const note = document.getElementById("signal-note");
  if (note) note.textContent = flow.note;
  const title = document.getElementById("signal-title");
  if (title) title.textContent = flow.title;
}

export function initSignalFlow() {
  const svg = document.getElementById("signal-svg");
  const tabs = document.querySelectorAll("[data-flow]");
  if (!svg || !tabs.length) return;

  const set = (key) => {
    tabs.forEach((t) => {
      const on = t.dataset.flow === key;
      t.setAttribute("aria-selected", on ? "true" : "false");
    });
    renderFlow(svg, key);
  };

  tabs.forEach((t) => t.addEventListener("click", () => set(t.dataset.flow)));
  set("light");
}
