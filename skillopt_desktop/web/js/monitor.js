// Live training monitor: pipeline stages, progress bar, coloured logs.
// Uses HTTP polling (robust in packaged builds where a WS lib may be absent).
import { get, post, toast, escapeHtml } from "./api.js";
import { t } from "./i18n.js";

const STAGES = ["rollout", "reflect", "aggregate", "select", "update", "gate"];

export async function render(root, ctx) {
  const runId = ctx.currentRun;
  root.innerHTML = `
    <div class="card">
      <div style="display:flex;justify-content:space-between;align-items:center">
        <h3 style="margin:0">${t("monitor.run")} ${runId ? escapeHtml(runId) : "(" + t("common.none") + ")"}</h3>
        <div class="btn-row" style="margin:0">
          <span class="badge" id="runMode" style="display:none"></span>
          <span class="badge off" id="runState">${t("monitor.idle")}</span>
          <button class="btn danger" id="stopBtn" ${runId ? "" : "disabled"}>${t("monitor.stop")}</button>
        </div>
      </div>
    </div>`;
  if (!runId) {
    root.insertAdjacentHTML("beforeend",
      `<div class="card"><div class="empty">${t("monitor.empty")}</div></div>`);
    return {};
  }

  root.insertAdjacentHTML("beforeend", `
    <div class="card">
      <div class="pipeline">${STAGES.map((s) => `<div class="stage" data-s="${s}">${s}</div>`).join("")}</div>
      <div class="grid cols-3" style="margin:8px 0 16px">
        <div><div class="metric" id="mEpoch">0/0<small>epoch</small></div></div>
        <div><div class="metric" id="mStep">0/0<small>step</small></div></div>
        <div><div class="metric" id="mScore">—<small>best held-out</small></div></div>
      </div>
      <div class="progress"><div id="bar"></div></div>
    </div>
    <div class="card"><h3>${t("monitor.logs")}</h3><div class="logbox" id="log"></div></div>`);

  const logBox = root.querySelector("#log");
  const stopBtn = root.querySelector("#stopBtn");
  stopBtn.onclick = async () => { try { await post(`/api/train/${runId}/stop`); toast(t("monitor.stopReq")); } catch (e) { toast(e.message, "err"); } };

  function applyStatus(st) {
    if (!st) return;
    root.querySelector("#mEpoch").innerHTML = `${st.epoch}/${st.total_epochs}<small>epoch</small>`;
    root.querySelector("#mStep").innerHTML = `${st.step}/${st.total_steps}<small>step</small>`;
    root.querySelector("#mScore").innerHTML = `${st.best_score != null ? st.best_score.toFixed(3) : "—"}<small>best held-out</small>`;
    root.querySelector("#bar").style.width = `${(st.progress || 0) * 100}%`;
    const active = STAGES.indexOf(st.stage);
    root.querySelectorAll(".stage").forEach((e, i) => {
      e.classList.toggle("active", i === active);
      e.classList.toggle("done", active >= 0 && i < active);
    });
    const mode = root.querySelector("#runMode");
    if (mode) {
      mode.style.display = "inline-block";
      mode.className = `badge ${st.mock ? "demo" : "ok"}`;
      mode.textContent = st.mock ? t("monitor.demo") : t("monitor.live");
    }
    const badge = root.querySelector("#runState");
    if (st.running) { badge.className = "badge demo"; badge.textContent = t("monitor.running"); }
    else { badge.className = "badge ok"; badge.textContent = st.returncode === 0 ? t("common.done") : `${t("monitor.exit")}(${st.returncode})`; stopBtn.disabled = true; }
  }

  function appendLog(line) {
    const cls = /\[(rollout|reflect|aggregate|select|update|gate)\]|^\s*\[/.test(line) ? "l-stage"
      : /score/i.test(line) ? "l-score" : /error|\[error\]/i.test(line) ? "l-err"
      : line.startsWith("$") ? "l-cmd" : /\[demo\]/.test(line) ? "l-demo" : "";
    const div = document.createElement("div");
    div.className = cls; div.textContent = line;
    logBox.appendChild(div);
    logBox.scrollTop = logBox.scrollHeight;
  }

  let offset = 0;
  let stopped = false;
  async function poll() {
    if (stopped) return;
    try {
      const r = await get(`/api/train/${runId}/log?offset=${offset}`);
      (r.lines || []).forEach(appendLog);
      offset = r.next_offset;
      applyStatus(r.status);
      if (r.status && !r.status.running) return; // run finished — stop polling
    } catch (e) { /* transient; keep polling */ }
    if (!stopped) timer = setTimeout(poll, 600);
  }
  let timer = setTimeout(poll, 0);

  return { dispose() { stopped = true; clearTimeout(timer); } };
}
