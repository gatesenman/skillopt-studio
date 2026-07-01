// ACP integration: show launch command + one-click register into editors.
import { get, post, toast, escapeHtml } from "./api.js";
import { t } from "./i18n.js";

export async function render(root, ctx) {
  const st = await get("/api/acp/status");
  const snippet = st.snippet || {};
  const zed = { command: snippet.command, args: snippet.args || [], env: {} };
  const generic = JSON.stringify({ agent_servers: { skillopt: zed } }, null, 2);

  root.innerHTML = `
    <div class="card">
      <h3>${t("acp.title")} ${st.installed ? `<span class="badge ok">${t("acp.installed")}</span>` : `<span class="badge demo">${t("acp.moduleMode")}</span>`}</h3>
      <p class="hint">${t("acp.hint")}</p>
      <div class="codeblock">${escapeHtml((snippet.command || "") + " " + (snippet.args || []).join(" "))}</div>
      <div class="btn-row">
        <button class="btn primary" id="zedBtn">${t("acp.registerZed")}</button>
        <button class="btn ghost" id="copyBtn">${t("acp.copyGeneric")}</button>
      </div>
    </div>
    <div class="card">
      <h3>${t("acp.snippetTitle")}</h3>
      <p class="hint">${t("acp.snippetHint")}</p>
      <div class="codeblock" id="snippet">${escapeHtml(generic)}</div>
    </div>
    <div class="card">
      <h3>${t("acp.cmdsTitle")}</h3>
      <table><thead><tr><th>${t("acp.colCmd")}</th><th>${t("acp.colDesc")}</th></tr></thead><tbody>
        <tr><td><code>optimize &lt;benchmark|config.yaml&gt; [k=v ...]</code></td><td>${t("acp.cmdOptimize")}</td></tr>
        <tr><td><code>sleep &lt;run|dry-run|adopt|status&gt;</code></td><td>${t("acp.cmdSleep")}</td></tr>
        <tr><td><code>skills [list]</code></td><td>${t("acp.cmdSkills")}</td></tr>
        <tr><td><code>help</code></td><td>${t("acp.cmdHelp")}</td></tr>
      </tbody></table>
    </div>`;

  root.querySelector("#zedBtn").onclick = async () => {
    try { const r = await post("/api/acp/register", { editor: "zed" });
      toast(r.message, r.ok ? "ok" : "err"); } catch (e) { toast(e.message, "err"); }
  };
  root.querySelector("#copyBtn").onclick = async () => {
    try { await navigator.clipboard.writeText(generic); toast(t("common.copied"), "ok"); }
    catch { toast(t("acp.copyFail"), "err"); }
  };
  return {};
}
