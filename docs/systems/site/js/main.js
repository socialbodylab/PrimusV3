import { thesis } from "./data.js";
import { initSignalFlow } from "./signal-flow.js";
import { initBlueprint } from "./blueprint.js";
import { initLockMatrix } from "./lock-matrix.js";
import { initRecipes } from "./recipes.js";
import { initApiTable } from "./api-table.js";

function initNav() {
  const links = document.querySelectorAll(".nav-links a[href^='#']");
  const sections = [...document.querySelectorAll("main section[id]")];

  const onScroll = () => {
    const y = window.scrollY + 120;
    let current = sections[0]?.id;
    for (const s of sections) {
      if (s.offsetTop <= y) current = s.id;
    }
    links.forEach((a) => {
      const on = a.getAttribute("href") === `#${current}`;
      if (on) a.setAttribute("aria-current", "true");
      else a.removeAttribute("aria-current");
    });
  };

  window.addEventListener("scroll", onScroll, { passive: true });
  onScroll();
}

function initThesis() {
  const el = document.getElementById("hero-thesis");
  if (el) el.textContent = thesis;
}

document.addEventListener("DOMContentLoaded", () => {
  initThesis();
  initNav();
  initSignalFlow();
  initBlueprint();
  initLockMatrix();
  initRecipes();
  initApiTable();
});
