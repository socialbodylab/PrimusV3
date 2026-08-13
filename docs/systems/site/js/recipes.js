import { recipes } from "./data.js";

function renderList(id, steps) {
  const ol = document.getElementById(id);
  if (!ol) return;
  ol.innerHTML = "";
  for (const step of steps) {
    const li = document.createElement("li");
    li.textContent = step;
    ol.appendChild(li);
  }
}

export function initRecipes() {
  renderList("recipe-light", recipes.light);
  renderList("recipe-sound", recipes.sound);
}
