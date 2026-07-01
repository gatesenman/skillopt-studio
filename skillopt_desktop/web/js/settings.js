// Provider settings: configure & test every supported backend.
import { get, post, toast, escapeHtml } from "./api.js";
import { t } from "./i18n.js";

export async function render(root, ctx) {
  const backends = await get("/api/backends");
  root.innerHTML = `<div class="grid cols-2" id="grid"></div>`;
  const grid = root.querySelector("#grid");

  backends.forEach((b) => {
    const card = document.createElement("div");
    card.className = "card";
    card.innerHTML = `
      <div style="display:flex;justify-content:space-between;align-items:center">
        <h3 style="margin:0">${escapeHtml(b.name)}</h3>
        <span class="badge ${b.configured ? "ok" : "off"}">${b.configured ? t("common.configured") : (b.kind === "cli" ? "CLI" : t("settings.notConfigured"))}</span>
      </div>
      <p class="hint">${escapeHtml(b.note || "") || (b.kind === "cli" ? t("settings.cliNote") : t("settings.apiNote"))}</p>
      ${b.fields.map((f) => `
        <label class="field"><span>${escapeHtml(f.label)}${f.required ? " *" : ""} ${f.set ? `<span class="badge ok">${t("common.saved")}</span>` : ""}</span>
          <input data-key="${f.key}" type="${f.secret ? "password" : "text"}" placeholder="${escapeHtml(f.placeholder || "")}" /></label>`).join("")}
      <div class="btn-row">
        <button class="btn" data-act="test">${t("common.test")}</button>
        <button class="btn primary" data-act="save">${t("common.save")}</button>
      </div>`;
    const creds = () => Object.fromEntries([...card.querySelectorAll("input")]
      .map((i) => [i.dataset.key, i.value]).filter(([, v]) => v !== ""));
    card.querySelector('[data-act="test"]').onclick = async () => {
      try { const r = await post("/api/backends/test", { backend: b.id, creds: creds() });
        toast(r.message, r.ok ? "ok" : "err"); } catch (e) { toast(e.message, "err"); }
    };
    card.querySelector('[data-act="save"]').onclick = async () => {
      try { await post("/api/backends", { backend: b.id, creds: creds() });
        toast(t("common.saved") + " " + b.name, "ok"); card.querySelector(".badge").className = "badge ok";
        card.querySelector(".badge").textContent = t("common.configured"); } catch (e) { toast(e.message, "err"); }
    };
    grid.appendChild(card);
  });
  return {};
}
