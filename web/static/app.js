// ===== Local AI — клиентская логика =====
let TOKEN = localStorage.getItem("token") || "";
let activeChatId = localStorage.getItem("activeChat") || "";
let modelLoaded = false;
let generating = false;
let abortCtrl = null;
let curPanel = "chat";

const $ = (id) => document.getElementById(id);

async function api(path, opts = {}) {
  opts.headers = Object.assign(
    { "Content-Type": "application/json", Authorization: "Bearer " + TOKEN },
    opts.headers || {}
  );
  const r = await fetch(path, opts);
  if (r.status === 401) { logout(); throw new Error("unauthorized"); }
  return r;
}
const apiJson = async (p, o) => (await api(p, o)).json();

// ===== АВТОРИЗАЦИЯ =====
async function login() {
  const r = await fetch("/api/login", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ password: $("password").value }),
  });
  if (!r.ok) { $("login-err").textContent = t("bad_pass"); return; }
  TOKEN = (await r.json()).token;
  localStorage.setItem("token", TOKEN);
  showApp();
}
function logout() {
  TOKEN = ""; localStorage.removeItem("token");
  $("app").classList.add("hidden"); $("login").classList.remove("hidden");
}
async function showApp() {
  $("login").classList.add("hidden"); $("app").classList.remove("hidden");
  await refreshStatus();
  await loadChats();
  setPanel("chat");
  startMetricsLoop();
}

// ===== СТАТУС / МОДЕЛЬ =====
async function refreshStatus() {
  try {
    const s = await apiJson("/api/status");
    modelLoaded = s.model_loaded;
    $("header-model").textContent = s.active_model || t("model_not_loaded");
    $("stop-btn").classList.toggle("active", !!s.stop_flag);
    updateBanner();
  } catch (e) {}
}
function updateBanner() {
  $("model-banner").classList.toggle("hidden", modelLoaded);
}

// ===== ПАНЕЛИ =====
function setPanel(name) {
  curPanel = name;
  document.querySelectorAll(".nav-btn").forEach(b => b.classList.toggle("active", b.dataset.panel === name));
  document.querySelectorAll(".panel").forEach(p => p.classList.toggle("active", p.id === "panel-" + name));
  const loaders = { models: loadModels, agents: loadAgents, training: loadTraining, logs: loadLogs, status: loadStatus, system: loadSystemOnce };
  if (loaders[name]) loaders[name]();
}

// ===== ЧАТЫ =====
async function loadChats() {
  const { chats } = await apiJson("/api/chats");
  if (!chats.length) {
    const c = await apiJson("/api/chats", { method: "POST" });
    activeChatId = c.id; localStorage.setItem("activeChat", activeChatId);
    return loadChats();
  }
  renderChatList(chats);
  if (!activeChatId || !chats.some(c => c.id === activeChatId)) {
    activeChatId = chats[0].id; localStorage.setItem("activeChat", activeChatId);
  }
  await openChat(activeChatId);
}
function renderChatList(chats) {
  const el = $("chat-list");
  if (!chats.length) { el.innerHTML = `<div class="chat-empty">${t("no_chats")}</div>`; return; }
  el.innerHTML = chats.map(c => `
    <div class="chat-item ${c.id === activeChatId ? "active" : ""}" data-id="${c.id}">
      <span class="chat-item-title">${escapeText(c.title)}</span>
      <span class="chat-item-actions">
        <button class="chat-action-btn" data-act="rename" title="${t("rename")}">✎</button>
        <button class="chat-action-btn" data-act="delete" title="${t("delete")}">🗑</button>
      </span>
    </div>`).join("");
}
async function openChat(id) {
  activeChatId = id; localStorage.setItem("activeChat", id);
  document.querySelectorAll(".chat-item").forEach(i => i.classList.toggle("active", i.dataset.id === id));
  const c = await apiJson("/api/chats/" + id);
  const log = $("chat-log"); log.innerHTML = "";
  if (!c.messages.length) {
    log.innerHTML = `<div class="chat-welcome"><div class="chat-welcome-icon">💬</div><div class="chat-welcome-text">${escapeText(t("model_load_hint"))}</div></div>`;
  } else {
    for (const m of c.messages) renderMessage(m.role, m.content, false);
  }
  scrollChat();
}
async function newChat() {
  const c = await apiJson("/api/chats", { method: "POST" });
  await loadChats(); await openChat(c.id);
}
async function renameChat(id) {
  const title = prompt(t("rename_title"));
  if (title) { await api("/api/chats/" + id, { method: "PATCH", body: JSON.stringify({ title }) }); await loadChats(); }
}
async function deleteChat(id) {
  await api("/api/chats/" + id, { method: "DELETE" });
  if (id === activeChatId) { activeChatId = ""; localStorage.removeItem("activeChat"); }
  await loadChats();
}

// ===== РЕНДЕР СООБЩЕНИЙ =====
function escapeText(s) { const d = document.createElement("div"); d.textContent = s; return d.innerHTML; }

function splitThink(raw) {
  // Возвращает {think, answer} с учётом частично пришедших тегов <think>.
  const open = raw.indexOf("<think>");
  if (open === -1) return { think: "", answer: raw };
  const after = raw.slice(open + 7);
  const close = after.indexOf("</think>");
  if (close === -1) return { think: after, answer: "" };
  return { think: after.slice(0, close), answer: after.slice(close + 8) };
}

function renderMessage(role, content, streaming) {
  const log = $("chat-log");
  const welcome = log.querySelector(".chat-welcome");
  if (welcome) welcome.remove();
  const row = document.createElement("div");
  row.className = "msg-row " + role;
  const bubble = document.createElement("div");
  bubble.className = "msg-bubble";
  row.appendChild(bubble);
  log.appendChild(row);
  if (role === "user") {
    bubble.textContent = content;
  } else {
    paintAssistant(bubble, content);
  }
  scrollChat();
  return bubble;
}

function paintAssistant(bubble, raw, cursor) {
  const { think, answer } = splitThink(raw);
  let html = "";
  if (think.trim()) {
    html += `<div class="think-block"><div class="think-header" onclick="this.parentElement.classList.toggle('open')">` +
            `<span class="think-chevron">▶</span> 💭 ${t("thinking")}</div>` +
            `<div class="think-body">${escapeText(think.trim())}</div></div>`;
  }
  html += `<div class="answer">${mdToHtml(answer)}${cursor ? '<span class="cursor-blink"></span>' : ""}</div>`;
  bubble.innerHTML = html;
}

function scrollChat() { const l = $("chat-log"); l.scrollTop = l.scrollHeight; }

// ===== ОТПРАВКА + СТРИМ =====
async function sendMessage() {
  if (generating) { return stopGen(); }
  const ta = $("chat-msg");
  const msg = ta.value.trim();
  if (!msg) return;
  if (!modelLoaded) { setPanel("models"); return; }
  ta.value = ""; ta.style.height = "auto";
  renderMessage("user", msg, false);

  const bubble = renderMessage("assistant", "", true);
  setGenerating(true);
  await api("/api/safety/resume", { method: "POST" }).catch(() => {});
  abortCtrl = new AbortController();
  let raw = "";
  try {
    const r = await fetch("/api/chats/" + activeChatId + "/message", {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: "Bearer " + TOKEN },
      body: JSON.stringify({ message: msg }),
      signal: abortCtrl.signal,
    });
    if (r.status === 409) { paintAssistant(bubble, "⚠️ " + t("model_not_loaded"), false); modelLoaded = false; updateBanner(); setGenerating(false); return; }
    const reader = r.body.getReader();
    const dec = new TextDecoder();
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      raw += dec.decode(value, { stream: true });
      paintAssistant(bubble, raw, true);
      scrollChat();
    }
  } catch (e) {
    if (e.name !== "AbortError") raw += "\n\n⚠️ " + t("error");
  } finally {
    paintAssistant(bubble, raw, false);
    // свернуть размышления после генерации
    const tb = bubble.querySelector(".think-block"); if (tb) tb.classList.remove("open");
    setGenerating(false);
    loadChats(); // обновить заголовок чата в сайдбаре
  }
}
function setGenerating(v) {
  generating = v;
  const b = $("chat-send");
  b.classList.toggle("stop-mode", v);
  b.textContent = v ? t("stop_gen") : t("send");
}
async function stopGen() {
  await api("/api/safety/stop", { method: "POST" }).catch(() => {});
  if (abortCtrl) abortCtrl.abort();
  setGenerating(false);
}

// ===== МОДЕЛИ =====
async function loadModels() {
  const { models, active } = await apiJson("/api/models");
  $("models-view").innerHTML = models.map(m => {
    let badge = m.id === active ? `<span class="card-badge badge-active">✓ ${t("active")}</span>`
              : m.downloaded ? `<span class="card-badge badge-downloaded">${t("downloaded")}</span>`
              : `<span class="card-badge badge-not-dl">⬇ ${t("not_downloaded")}</span>`;
    return `<div class="card">
      <div class="card-info">
        <div class="card-title">${escapeText(m.name)} ${badge}</div>
        <div class="card-sub">${m.quant} · ${m.size_gb} ГБ · ${escapeText(m.note || "")}</div>
      </div>
      <button class="btn-sm" onclick="doLoadModel('${m.id}', this)">${t("load")}</button>
    </div>`;
  }).join("");
}
async function doLoadModel(id, btn) {
  btn.disabled = true; btn.textContent = t("loading_model");
  try {
    await api("/api/models/load", { method: "POST", body: JSON.stringify({ model_id: id }) });
    await refreshStatus(); await loadModels();
  } catch (e) { btn.textContent = t("error"); }
}

// ===== АГЕНТЫ =====
async function loadAgents() {
  const { agents } = await apiJson("/api/agents");
  $("agents-view").innerHTML = agents.map(a => `
    <div class="card"><div class="card-info">
      <div class="card-title">${escapeText(a.name)}</div>
      <div class="card-sub">${escapeText(a.role)}</div>
      <div class="agent-tools">${(a.tools || []).map(x => `<span class="agent-tool-tag">${escapeText(x)}</span>`).join("")}</div>
    </div></div>`).join("") || `<div class="muted">${t("agents_empty")}</div>`;
}

// ===== ОБУЧЕНИЕ =====
async function loadTraining() {
  const { models } = await apiJson("/api/models");
  const intro = `<div class="card"><div class="card-info">
    <div class="card-title">🎓 ${t("train")}</div>
    <div class="card-sub">${t("train_help")}</div></div></div>`;
  const cards = models.map(m => `
    <div class="card"><div class="card-info">
      <div class="card-title">${escapeText(m.name)}</div>
      <div class="card-sub">${m.trainable_local ? "✅ " + t("local_train") : "🖥 " + t("need_gpu")}</div>
    </div>
    <button class="btn-sm" ${m.trainable_local ? "" : "disabled"} onclick="startTrain('${m.id}')">${t("train")}</button>
    </div>`).join("");
  $("training-view").innerHTML = intro + cards;
}
async function startTrain(id) {
  const r = await apiJson("/api/training/start", { method: "POST", body: JSON.stringify({ model_id: id }) });
  alert(r.ok ? t("training_start_ok") : (r.reason || t("training_start_err")));
}

// ===== ЛОГИ =====
async function loadLogs() {
  try {
    const { lines } = await apiJson("/api/logs?limit=200");
    if (!lines.length) { $("logs-view").innerHTML = `<div class="muted">${t("logs_empty")}</div>`; return; }
    const rows = lines.slice().reverse().map(l => {
      const { ts, action, ...rest } = l;
      return `<tr><td class="log-ts">${escapeText(ts || "")}</td>
        <td class="log-action">${escapeText(action || "")}</td>
        <td class="log-detail">${escapeText(JSON.stringify(rest))}</td></tr>`;
    }).join("");
    $("logs-view").innerHTML = `<table class="log-table"><thead><tr><th>time</th><th>action</th><th>detail</th></tr></thead><tbody>${rows}</tbody></table>`;
  } catch (e) { $("logs-view").innerHTML = `<div class="muted">${t("error")}</div>`; }
}

// ===== СТАТУС =====
async function loadStatus() {
  const s = await apiJson("/api/status");
  const row = (k, v) => `<div class="card"><div class="card-info"><div class="card-sub">${k}</div><div class="card-title">${v}</div></div></div>`;
  $("status-view").innerHTML =
    row(t("active_model"), s.active_model || t("none")) +
    row(t("adapter_label"), s.active_adapter || t("none")) +
    row(t("deploy_mode_label"), s.deploy_mode) +
    row(t("stop_flag_label"), s.stop_flag ? t("yes") : t("no")) +
    row(t("training_label"), (s.training && s.training.state) || "idle");
}

// ===== СИСТЕМА (метрики + графики) =====
const cpuHist = [], ramHist = [], MAXP = 60;
let metricsTimer = null;
function startMetricsLoop() {
  if (metricsTimer) return;
  metricsTimer = setInterval(pollMetrics, 1500);
  pollMetrics();
}
async function pollMetrics() {
  try {
    const m = await apiJson("/api/metrics");
    if (m.error) return;
    cpuHist.push(m.cpu); ramHist.push(m.ram);
    if (cpuHist.length > MAXP) cpuHist.shift();
    if (ramHist.length > MAXP) ramHist.shift();
    if (curPanel === "system") renderMetrics(m);
  } catch (e) {}
}
function loadSystemOnce() { pollMetrics(); }
function renderMetrics(m) {
  $("metrics-grid").innerHTML = [
    [t("cpu"), m.cpu + "%", m.cores + " " + t("cores")],
    [t("ram"), m.ram + "%", m.ram_used_mb + " / " + m.ram_total_mb + " MB"],
    [t("disk"), m.disk + "%", m.disk_used_gb + " / " + m.disk_total_gb + " GB"],
  ].map(([l, v, s]) => `<div class="metric-card"><div class="metric-label">${l}</div><div class="metric-value">${v}</div><div class="metric-sub">${s}</div></div>`).join("");
  drawChart($("chart-cpu"), cpuHist, "#7c8cf8");
  drawChart($("chart-ram"), ramHist, "#4ade80");
}
function drawChart(cv, data, color) {
  if (!cv) return;
  const ctx = cv.getContext("2d");
  const W = cv.width, H = cv.height;
  ctx.clearRect(0, 0, W, H);
  // сетка
  ctx.strokeStyle = "#1e2230"; ctx.lineWidth = 1;
  for (let i = 0; i <= 4; i++) { const y = (H / 4) * i; ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(W, y); ctx.stroke(); }
  if (data.length < 2) return;
  const step = W / (MAXP - 1);
  ctx.strokeStyle = color; ctx.lineWidth = 2; ctx.beginPath();
  data.forEach((v, i) => {
    const x = i * step, y = H - (v / 100) * H;
    i ? ctx.lineTo(x, y) : ctx.moveTo(x, y);
  });
  ctx.stroke();
  // заливка
  ctx.lineTo((data.length - 1) * step, H); ctx.lineTo(0, H); ctx.closePath();
  ctx.fillStyle = color + "22"; ctx.fill();
}

// ===== СТОП-ФЛАГ (хедер) =====
async function toggleStopFlag() {
  const s = await apiJson("/api/safety");
  await api(s.stop_flag ? "/api/safety/resume" : "/api/safety/stop", { method: "POST" });
  refreshStatus();
}

// ===== INIT =====
function onLangChange() { setPanel(curPanel); }
window.addEventListener("DOMContentLoaded", () => {
  applyI18n();
  $("login-btn").onclick = login;
  $("password").addEventListener("keydown", e => { if (e.key === "Enter") login(); });
  $("logout-btn").onclick = logout;
  $("lang-btn").onclick = toggleLang;
  $("stop-btn").onclick = toggleStopFlag;
  $("sidebar-toggle").onclick = () => $("sidebar").classList.toggle("collapsed");
  $("new-chat").onclick = newChat;
  $("banner-load").onclick = () => setPanel("models");
  $("chat-send").onclick = sendMessage;

  const ta = $("chat-msg");
  ta.addEventListener("keydown", e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendMessage(); } });
  ta.addEventListener("input", () => { ta.style.height = "auto"; ta.style.height = Math.min(ta.scrollHeight, 180) + "px"; });

  document.querySelectorAll(".nav-btn").forEach(b => b.onclick = () => setPanel(b.dataset.panel));
  $("chat-list").addEventListener("click", e => {
    const item = e.target.closest(".chat-item"); if (!item) return;
    const id = item.dataset.id, act = e.target.dataset.act;
    if (act === "rename") return renameChat(id);
    if (act === "delete") return deleteChat(id);
    openChat(id);
  });

  if (TOKEN) showApp(); else $("login").classList.remove("hidden");
});
