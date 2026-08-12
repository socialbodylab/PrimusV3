import { lockMatrix } from "./data.js";

const LABELS = {
  open: "Open",
  locked: "Locked",
  na: "—",
};

export function initLockMatrix() {
  const root = document.getElementById("matrix-root");
  if (!root) return;

  const wrap = document.createElement("div");
  wrap.className = "matrix-wrap";

  const table = document.createElement("table");
  table.className = "matrix";

  const thead = document.createElement("thead");
  const hr = document.createElement("tr");
  hr.appendChild(document.createElement("th")).textContent = "Control";
  for (const col of lockMatrix.columns) {
    const th = document.createElement("th");
    th.textContent = col;
    hr.appendChild(th);
  }
  thead.appendChild(hr);
  table.appendChild(thead);

  const tbody = document.createElement("tbody");
  for (const row of lockMatrix.rows) {
    const [label, ...states] = row;
    const tr = document.createElement("tr");
    const th = document.createElement("th");
    th.scope = "row";
    th.textContent = label;
    tr.appendChild(th);
    for (const state of states) {
      const td = document.createElement("td");
      td.className = `cell-${state}`;
      td.textContent = LABELS[state] || state;
      tr.appendChild(td);
    }
    tbody.appendChild(tr);
  }
  table.appendChild(tbody);
  wrap.appendChild(table);
  root.appendChild(wrap);

  const legend = document.createElement("div");
  legend.className = "matrix-legend";
  legend.innerHTML =
    "<span><i class='lg-open'></i>Open</span>" +
    "<span><i class='lg-locked'></i>Locked</span>" +
    "<span><i class='lg-na'></i>N/A</span>";
  root.appendChild(legend);
}
