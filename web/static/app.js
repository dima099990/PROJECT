// Логика UI: логин, токен, переключение панелей, чат, модели, статус по WS.
let TOKEN = localStorage.getItem("token") || "";

const $ = (id) => document.getElementById(id);
async function api(path, opts = {}) {
  opts.headers = Object.assign({ "Content-Type": "application/json", Authorization: "Bearer " + TOKEN }, opts.headers || {});
  const r = await fetch(path, opts);
  if (r.status === 401) { logout(); throw new Error("unauthorized"); }
  return r.json();
}

// --- Авторизация ---
async function login() {
  const r = await fetch("/api/login", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ password: $("password").value }),
  });
  if (!r.ok) { $("login-err").textContent = t("bad_pass"); return; }
  const data = await r.json();
  TOKEN = data.token; localStorage.setItem("token", TOKEN);
  showApp();
}
function logout() { TOKEN = ""; localStorage.removeItem("token"); $("app").classList.add("hidden"); $("login").classList.remove("hidden"); }
function showApp() { $("login").classList.add("hidden"); $("app").classList.remove("hidden"); openTab("chat"); connectWS(); }

// --- Вкладки ---
function openTab(name) {
  document.querySelectorAll(".tab").forEach(t => t.classList.toggle("active", t.dataset.tab === name));
  document.querySelectorAll(".panel").forEach(p => p.classList.toggle("active", p.id === "panel-" + name));
  const loaders = { files: loadFiles, agents: loadAgents, models: loadModels, training: loadTraining, logs: loadLogs, status: loadStatus };
  if (loaders[name]) loaders[name]();
}

// --- Чат ---
async function sendChat() {
  const msg = $("chat-msg").value.trim(); if (!msg) return;
  $("chat-msg").value = "";
  addMsg(msg, "user");
  try {
    const r = await api("/api/chat", { method: "POST", body: JSON.stringify({ message: msg }) });
    addMsg(r.ok ? r.reply : "⚠ " + (r.reason || "error"), "bot");
  } catch (e) { addMsg("⚠ " + e.message, "bot"); }
}
function addMsg(text, who) {
  const d = document.createElement("div"); d.className = "msg " + who; d.textContent = text;
  $("chat-log").appendChild(d); $("chat-log").scrollTop = 1e9;
}

// --- Панели ---
async function loadModels() {
  const { models, active } = await api("/api/models");
  $("models-view").innerHTML = models.map(m => `
    <div class="card">
      <div><b>${m.name}</b> <span class="muted">${m.quant} · ${m.size_gb} ГБ</span><br>
        <span class="muted">${m.downloaded ? "✓" : "⬇ " + t("download")} ${m.id === active ? "· " + t("active") : ""}</span></div>
      <button onclick="loadModel('${m.id}')">${t("load")}</button>
    </div>`).join("");
}
async function loadModel(id) { await api("/api/models/load", { method: "POST", body: JSON.stringify({ model_id: id }) }); loadModels(); }

async function loadAgents() {
  const { agents } = await api("/api/agents");
  $("agents-view").innerHTML = agents.map(a => `<div class="card"><div><b>${a.name}</b><br><span class="muted">${a.role}</span></div><span class="muted">${(a.tools||[]).join(", ")}</span></div>`).join("");
}
async function loadFiles() {
  const r = await api("/api/files?path=.");
  $("files-view").innerHTML = `<div class="muted">${r.path} ${r.writable ? "✏" : "🔒"}</div>` +
    r.items.map(i => `<div>${i.dir ? "📁" : "📄"} ${i.name}</div>`).join("");
}
async function loadTraining() {
  const { models } = await api("/api/models");
  $("training-view").innerHTML = models.map(m => `<div class="card"><div><b>${m.name}</b><br><span class="muted">${m.trainable_local ? "локально" : "нужен GPU-сервер"}</span></div><button onclick="train('${m.id}')" ${m.trainable_local ? "" : "disabled"}>${t("train")}</button></div>`).join("");
}
async function train(id) { const r = await api("/api/training/start", { method: "POST", body: JSON.stringify({ model_id: id }) }); alert(JSON.stringify(r)); }
async function loadLogs() { const r = await api("/api/logs"); $("logs-view").textContent = r.lines.map(l => JSON.stringify(l)).join("\n") || "—"; }
async function loadStatus() { const r = await api("/api/status"); $("status-view").textContent = JSON.stringify(r, null, 2); }

// --- WebSocket статус ---
function connectWS() {
  const ws = new WebSocket((location.protocol === "https:" ? "wss://" : "ws://") + location.host + "/ws/status");
  ws.onmessage = (e) => { const d = JSON.parse(e.data); $("status-pill").textContent = (d.model || "нет модели") + (d.stop_flag ? " · ⏹" : ""); };
  ws.onclose = () => setTimeout(connectWS, 3000);
}

// --- Стоп / возобновление ---
async function toggleStop() {
  const s = await api("/api/safety");
  await api(s.stop_flag ? "/api/safety/resume" : "/api/safety/stop", { method: "POST" });
}

// --- Init ---
window.addEventListener("DOMContentLoaded", () => {
  applyI18n();
  $("login-btn").onclick = login;
  $("password").addEventListener("keydown", e => { if (e.key === "Enter") login(); });
  $("logout-btn").onclick = logout;
  $("lang-btn").onclick = () => { toggleLang(); };
  $("stop-btn").onclick = toggleStop;
  $("chat-send").onclick = sendChat;
  $("chat-msg").addEventListener("keydown", e => { if (e.key === "Enter") sendChat(); });
  document.querySelectorAll(".tab").forEach(tb => tb.onclick = () => openTab(tb.dataset.tab));
  if (TOKEN) showApp(); else $("login").classList.remove("hidden");
});
