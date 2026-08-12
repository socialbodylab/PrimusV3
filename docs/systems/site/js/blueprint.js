import { blueprint } from "./data.js";

export function initBlueprint() {
  const root = document.getElementById("blueprint-root");
  if (!root) return;

  const table = document.createElement("table");
  table.className = "blueprint";

  const thead = document.createElement("thead");
  const hr = document.createElement("tr");
  hr.appendChild(document.createElement("th")).textContent = "Role";
  for (const col of blueprint.columns) {
    const th = document.createElement("th");
    th.textContent = col;
    hr.appendChild(th);
  }
  thead.appendChild(hr);
  table.appendChild(thead);

  const tbody = document.createElement("tbody");
  for (const row of blueprint.rows) {
    const tr = document.createElement("tr");
    const role = document.createElement("th");
    role.scope = "row";
    role.textContent = row.role;
    tr.appendChild(role);
    for (const cell of row.cells) {
      const td = document.createElement("td");
      td.innerHTML = cell.replace(/\n/g, "<br>");
      tr.appendChild(td);
    }
    tbody.appendChild(tr);
  }
  table.appendChild(tbody);
  root.appendChild(table);
}
