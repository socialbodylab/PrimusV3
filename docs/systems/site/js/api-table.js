import { apiRows } from "./data.js";

export function initApiTable() {
  const tbody = document.querySelector("#api-table tbody");
  const filterProduct = document.getElementById("api-product");
  const filterSurface = document.getElementById("api-surface");
  const search = document.getElementById("api-search");
  if (!tbody) return;

  const paint = () => {
    const product = filterProduct?.value || "all";
    const surface = filterSurface?.value || "all";
    const q = (search?.value || "").trim().toLowerCase();

    tbody.innerHTML = "";
    for (const row of apiRows) {
      if (product !== "all" && row.product !== product && row.product !== "both") continue;
      if (surface !== "all" && row.surface !== surface) continue;
      const hay = `${row.goal} ${row.path} ${row.mode} ${row.product}`.toLowerCase();
      if (q && !hay.includes(q)) continue;

      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td>${row.goal}</td>
        <td><span class="tag tag-${row.product}">${row.product}</span></td>
        <td>${row.surface}</td>
        <td><code>${row.path}</code></td>
        <td>${row.mode}</td>`;
      tbody.appendChild(tr);
    }
  };

  filterProduct?.addEventListener("change", paint);
  filterSurface?.addEventListener("change", paint);
  search?.addEventListener("input", paint);
  paint();
}
