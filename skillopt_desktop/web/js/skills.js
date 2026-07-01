// Skill library: list / inspect / export / import / delete skill artifacts.
import { get, post, del, toast, escapeHtml } from "./api.js";
import { t } from "./i18n.js";
import { icon } from "./icons.js";

export async function render(root, ctx) {
  const [benchmarks, backends] = await Promise.all([
    get("/api/benchmarks"), get("/api/backends"),
  ]);
  async function load() {
    const skills = await get("/api/skills");
    root.innerHTML = `
      <div class="card">
        <div style="display:flex;justify-content:space-between;align-items:center">
          <h3 style="margin:0">${t("skills.title")} (${skills.length})</h3>
          <div class="btn-row" style="margin:0">
            <input id="importPath" placeholder="${t("skills.importPath")}" style="width:240px" />
            <button class="btn ghost" id="importBrowse" title="${t("common.browse")}">${icon("folder")}</button>
            <button class="btn" id="importBtn">${icon("upload")} ${t("common.import")}</button>
          </div>
        </div>
        ${skills.length === 0 ? `<div class="empty">${t("skills.empty")}</div>` : `
        <table style="margin-top:12px"><thead><tr>
          <th>${t("skills.colName")}</th><th>${t("skills.colSource")}</th><th>${t("common.benchmark")}</th><th>${t("skills.colScore")}</th><th>tokens</th><th></th>
        </tr></thead><tbody>
          ${skills.map((s) => `<tr class="click" data-id="${s.id}">
            <td><b>${escapeHtml(s.name)}</b></td>
            <td>${s.source === "run" ? t("skills.srcRun") : t("skills.srcImport")}</td>
            <td>${escapeHtml(s.benchmark || "—")}</td>
            <td>${s.score != null ? s.score.toFixed(3) : "—"}</td>
            <td>${s.tokens}</td>
            <td style="white-space:nowrap">
              <button class="btn ghost export" data-id="${s.id}" title="${t("common.export")}">${icon("download")}</button>
              <button class="btn ghost danger del" data-id="${s.id}" title="${t("common.delete")}">${icon("trash")}</button>
            </td>
          </tr>`).join("")}
        </tbody></table>`}
      </div>
      <div class="card" id="detail" style="display:none"></div>`;

    root.querySelector("#importBrowse").onclick = async () => {
      const p = await pickPath(false);
      if (p) root.querySelector("#importPath").value = p;
    };
    root.querySelector("#importBtn").onclick = async () => {
      const src = root.querySelector("#importPath").value.trim();
      if (!src) return;
      try { await post("/api/skills/import", { src }); toast(t("skills.imported"), "ok"); load(); }
      catch (e) { toast(e.message, "err"); }
    };
    root.querySelectorAll("tr.click").forEach((tr) => tr.onclick = (e) => {
      if (e.target.closest(".export") || e.target.closest(".del")) return;
      showDetail(tr.dataset.id);
    });
    root.querySelectorAll(".export").forEach((b) => b.onclick = (e) => {
      e.stopPropagation(); showDetail(b.dataset.id, true);
    });
    root.querySelectorAll(".del").forEach((b) => b.onclick = (e) => {
      e.stopPropagation(); doDelete(b.dataset.id);
    });
  }

  // Map a skill's recorded benchmark (which may be a preset id like
  // "docvqa_quickstart") to a real benchmark config name (e.g. "docvqa").
  function defaultBench(b) {
    if (!b) return benchmarks[0];
    if (benchmarks.includes(b)) return b;
    const hit = benchmarks.find((x) => b === x || b.startsWith(x) || b.includes(x));
    return hit || benchmarks[0];
  }

  function sparkline(curve) {
    if (!curve || curve.length < 2) return "";
    const w = 280, h = 48, pad = 4;
    const min = Math.min(...curve), max = Math.max(...curve);
    const span = max - min || 1;
    const pts = curve.map((v, i) => {
      const x = pad + (i / (curve.length - 1)) * (w - 2 * pad);
      const y = h - pad - ((v - min) / span) * (h - 2 * pad);
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    }).join(" ");
    return `<div style="margin-top:10px">
      <div class="hint">${t("skills.scoreCurve")} (${min.toFixed(3)} → ${max.toFixed(3)})</div>
      <svg width="${w}" height="${h}" viewBox="0 0 ${w} ${h}" style="overflow:visible">
        <polyline fill="none" stroke="var(--accent,#4f8cff)" stroke-width="2"
          stroke-linejoin="round" stroke-linecap="round" points="${pts}"/>
      </svg></div>`;
  }

  async function showDetail(id, focusExport = false) {
    const d = await get(`/api/skills/${id}`);
    const box = root.querySelector("#detail");
    box.style.display = "block";
    box.innerHTML = `
      <div style="display:flex;justify-content:space-between;align-items:center">
        <h3 style="margin:0">${escapeHtml(d.name)} <span class="pill">${d.tokens} tokens</span></h3>
        <div class="btn-row" style="margin:0">
          <button class="btn ghost danger" id="delDetail">${icon("trash")} ${t("common.delete")}</button>
        </div>
      </div>
      <p class="hint">${escapeHtml(d.path)}</p>
      ${sparkline(d.score_curve)}
      <div class="eval-panel" style="margin-top:12px">
        <div class="hint">${t("skills.evalTitle")}</div>
        <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-top:6px">
          <label class="field" style="margin:0"><span>${t("skills.evalBench")}</span>
            <select id="evalBench">${benchmarks.map((b) =>
              `<option${b === defaultBench(d.benchmark) ? " selected" : ""}>${escapeHtml(b)}</option>`).join("")}</select></label>
          <label class="field" style="margin:0"><span>${t("skills.evalBackend")}</span>
            <select id="evalBackend"><option value="">${t("pro.demoMock")}</option>
              ${backends.map((b) => `<option value="${b.id}">${escapeHtml(b.name)}${b.configured ? " \u2713" : ""}</option>`).join("")}</select></label>
          <button class="btn primary" id="evalGo">${icon("play")} ${t("skills.evalRun")}</button>
        </div>
      </div>
      <div class="export-panel" style="margin-top:12px;display:flex;gap:8px;align-items:center;flex-wrap:wrap">
        <input id="exportDest" placeholder="${t("skills.exportDest")}" value="./SKILL.md" style="flex:1;min-width:220px" />
        <button class="btn ghost" id="exportBrowse" title="${t("common.browse")}">${icon("folder")}</button>
        <button class="btn" id="exportGo">${icon("download")} ${t("common.export")}</button>
      </div>
      <div class="codeblock" style="margin-top:12px">${escapeHtml(d.content)}</div>`;
    box.querySelector("#exportBrowse").onclick = async () => {
      const p = await pickPath(true);
      if (p) box.querySelector("#exportDest").value = p;
    };
    box.querySelector("#exportGo").onclick = async () => {
      const dest = box.querySelector("#exportDest").value.trim();
      if (!dest) return;
      try { const r = await post(`/api/skills/${id}/export`, { dest }); toast(t("skills.exportedTo") + r.path, "ok"); }
      catch (e) { toast(e.message, "err"); }
    };
    box.querySelector("#evalGo").onclick = async () => {
      try {
        const backend = box.querySelector("#evalBackend").value;
        const r = await post("/api/eval/start", {
          config_path: `configs/${box.querySelector("#evalBench").value}/default.yaml`,
          backend,
          mock: !backend,
          skill_path: d.path,
        });
        ctx.currentRun = r.run_id; toast(t("skills.evalStarted"), "ok"); ctx.go("monitor");
      } catch (e) { toast(e.message, "err"); }
    };
    box.querySelector("#delDetail").onclick = () => doDelete(id);
    if (focusExport) box.querySelector("#exportDest").focus();
    box.scrollIntoView({ behavior: "smooth" });
  }

  async function doDelete(id) {
    if (!confirm(t("skills.confirmDelete"))) return;
    try {
      await del(`/api/skills/${id}`);
      toast(t("skills.deleted"), "ok");
      root.querySelector("#detail").style.display = "none";
      load();
    } catch (e) { toast(e.message, "err"); }
  }

  // Native folder/file picker via pywebview; falls back to manual entry.
  async function pickPath(folder) {
    try {
      const r = await get(folder ? "/api/dialog/folder" : "/api/dialog/file");
      if (r.path) return r.path;
      if (r.unsupported) toast(t("skills.dialogUnsupported"), "");
    } catch { /* ignore, manual entry */ }
    return "";
  }

  await load();
  // Deep-link from History "eval" button: open that run's skill detail.
  if (ctx.evalRun) {
    const all = await get("/api/skills");
    const hit = all.find((s) => s.id === ctx.evalRun || (s.run_id && s.run_id === ctx.evalRun));
    ctx.evalRun = null;
    if (hit) showDetail(hit.id);
  }
  return {};
}
