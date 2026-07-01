// SkillOpt Studio frontend router + shared state.
import { get, toast } from "./api.js";
import { t, getLang, setLang } from "./i18n.js";
import { icon } from "./icons.js";
import * as wizard from "./wizard.js";
import * as pro from "./pro.js";
import * as monitor from "./monitor.js";
import * as history from "./history.js";
import * as skills from "./skills.js";
import * as sleep from "./sleep.js";
import * as acp from "./acp.js";
import * as settings from "./settings.js";

const VIEWS = {
  wizard: { mod: wizard },
  pro: { mod: pro },
  monitor: { mod: monitor },
  history: { mod: history },
  skills: { mod: skills },
  sleep: { mod: sleep },
  acp: { mod: acp },
  settings: { mod: settings },
};

// Shared, in-memory app context (current run id, last preset/config, health).
export const ctx = {
  health: null,
  currentRun: null,        // active training run id (for Monitor)
  selectedBackend: "",
  go,                      // programmatic navigation
};

const root = document.getElementById("view-root");
let currentView = "wizard";

// Render every element carrying a data-i18n key (labels, nav, status text).
function applyI18nText() {
  document.querySelectorAll("[data-i18n]").forEach((node) => {
    node.textContent = t(node.dataset.i18n);
  });
  // nav items also get a leading icon
  document.querySelectorAll(".nav-item[data-icon]").forEach((b) => {
    b.innerHTML = `${icon(b.dataset.icon, "nav-ic")}<span>${t(b.dataset.i18n)}</span>`;
  });
  document.documentElement.lang = getLang();
}

function setActiveNav(view) {
  document.querySelectorAll(".nav-item").forEach((b) =>
    b.classList.toggle("active", b.dataset.view === view));
  document.getElementById("view-title").textContent = t(`nav.${view}`);
  document.getElementById("view-subtitle").textContent = t(`sub.${view}`);
}

let current;
async function go(view) {
  if (!VIEWS[view]) view = "wizard";
  currentView = view;
  if (current?.dispose) current.dispose();
  setActiveNav(view);
  root.innerHTML = "";
  try {
    current = await VIEWS[view].mod.render(root, ctx) || {};
  } catch (e) {
    root.innerHTML = `<div class="card"><h3>${t("view.loadFail")}</h3><p class="hint">${e.message}</p></div>`;
  }
}

document.querySelectorAll(".nav-item").forEach((b) =>
  b.addEventListener("click", () => go(b.dataset.view)));

function syncLangButtons() {
  document.querySelectorAll("#lang-toggle button").forEach((b) =>
    b.classList.toggle("active", b.dataset.lang === getLang()));
}
document.querySelectorAll("#lang-toggle button").forEach((b) =>
  b.addEventListener("click", () => {
    setLang(b.dataset.lang);
    applyI18nText();
    syncLangButtons();
    refreshHealth();
    go(currentView);          // re-render current view in the new language
  }));

async function refreshHealth() {
  try {
    ctx.health = await get("/api/health");
    const card = document.getElementById("env-status");
    if (ctx.health.live) {
      card.className = "status-card live";
      card.innerHTML = `<div class="dot"></div><span>${t("status.live")}</span>`;
    } else {
      card.className = "status-card demo";
      card.innerHTML = `<div class="dot"></div><span>${t("status.demo")}</span>`;
    }
  } catch {
    toast(t("status.connFail"), "err");
  }
}

(async function main() {
  applyI18nText();
  syncLangButtons();
  await refreshHealth();
  go("wizard");
})();
