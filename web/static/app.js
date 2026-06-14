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
  // остановить таймеры предыдущей панели
  if (curPanel === "logs" && name !== "logs" && _logsTimer) {
    clearInterval(_logsTimer); _logsTimer = null;
  }
  if (curPanel === "status" && name !== "status" && _statusMetricsTimer) {
    clearInterval(_statusMetricsTimer); _statusMetricsTimer = null;
    _statusCpuHist = []; _statusRamHist = [];
  }
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
  const cards = models.map(m => {
    const isActive = m.id === active;
    let badge, actionBtn;
    if (isActive) {
      badge = `<span class="card-badge badge-active">${t("models_active_btn")}</span>`;
      actionBtn = `<button class="btn-sm" disabled>${t("models_active_btn")}</button>`;
    } else if (m.downloaded) {
      badge = `<span class="card-badge model-badge-installed">${t("models_status_installed")}</span>`;
      actionBtn = `<button class="btn-sm" onclick="doLoadModel('${m.id}', this)">${t("models_run_btn")}</button>`;
    } else {
      badge = `<span class="card-badge model-badge-not-installed">${t("models_status_not_installed")}</span>`;
      actionBtn = `<button class="btn-sm" onclick="doLoadModel('${m.id}', this)">${t("models_download_run_btn")}</button>`;
    }
    const del = m.source === "custom"
      ? `<button class="chat-action-btn" title="${t("delete")}" onclick="removeModel('${m.id}')">🗑</button>` : "";
    return `<div class="card">
      <div class="card-info">
        <div class="card-title">${escapeText(m.name)} ${badge}</div>
        <div class="card-sub">${escapeText(m.quant || "")} · ${m.size_gb || "?"} ГБ · ${escapeText(m.note || "")}</div>
      </div>
      ${del}${actionBtn}
    </div>`;
  }).join("");
  $("models-view").innerHTML = scratchFormHtml() + addModelFormHtml() + cards;
  _bindScratchInputs();
}

function addModelFormHtml() {
  return `<div class="card" style="display:block">
    <div class="card-title" style="cursor:pointer" onclick="document.getElementById('add-model-body').classList.toggle('hidden')">➕ ${t("add_model")}</div>
    <div id="add-model-body" class="hidden" style="margin-top:10px;display:flex;flex-direction:column;gap:8px">
      <div class="card-sub">${t("add_model_hint")}</div>
      <div style="display:flex;gap:8px">
        <input id="am-repo" class="am-input" placeholder="${t("repo_ph")}" style="flex:1"/>
        <button class="btn-sm" onclick="fetchRepoFiles()">${t("fetch_files")}</button>
      </div>
      <select id="am-file" class="am-input"><option value="">${t("filename_ph")}</option></select>
      <input id="am-name" class="am-input" placeholder="${t("name_ph")}"/>
      <div id="am-err" class="err"></div>
      <button class="btn-sm" onclick="submitAddModel(this)">${t("add_btn")}</button>
    </div>
  </div>`;
}
async function fetchRepoFiles() {
  const repo = $("am-repo").value.trim(); if (!repo) return;
  $("am-err").textContent = t("loading");
  try {
    const r = await apiJson("/api/models/repo_files?repo=" + encodeURIComponent(repo));
    if (r.error || !r.files.length) { $("am-err").textContent = r.error || t("error"); return; }
    $("am-file").innerHTML = r.files.map(f => `<option value="${escapeText(f)}">${escapeText(f)}</option>`).join("");
    $("am-err").textContent = "";
  } catch (e) { $("am-err").textContent = t("error"); }
}
async function submitAddModel(btn) {
  const repo = $("am-repo").value.trim();
  const filename = $("am-file").value;
  const name = $("am-name").value.trim() || filename.replace(".gguf", "");
  if (!repo || !filename) { $("am-err").textContent = t("add_model_need"); return; }
  btn.disabled = true;
  const r = await apiJson("/api/models/add", { method: "POST", body: JSON.stringify({ name, repo, filename }) });
  btn.disabled = false;
  if (r.ok) { loadModels(); } else { $("am-err").textContent = r.reason || t("error"); }
}
async function removeModel(id) {
  if (!confirm(t("delete") + "?")) return;
  await api("/api/models/" + id, { method: "DELETE" });
  loadModels();
}
async function doLoadModel(id, btn) {
  btn.disabled = true; btn.textContent = t("loading_model");
  try {
    await api("/api/models/load", { method: "POST", body: JSON.stringify({ model_id: id }) });
    await refreshStatus(); await loadModels();
  } catch (e) { btn.textContent = t("error"); }
}

// ===== SCRATCH (модель с нуля) =====
function scratchFormHtml() {
  return `<div class="scratch-form">
    <div class="scratch-form-title" onclick="$('scratch-body').classList.toggle('hidden')">
      ➕ ${t("models_scratch_title")}
    </div>
    <div id="scratch-body" class="hidden">
      <div class="scratch-name-row">
        <input id="sc-name" class="scratch-input" placeholder="${t("models_scratch_name_ph")}"/>
      </div>
      <div class="scratch-fields">
        <div class="scratch-field"><label>${t("models_scratch_layers")}</label><input id="sc-layers" class="scratch-input" type="number" value="12" min="1"/></div>
        <div class="scratch-field"><label>${t("models_scratch_embd")}</label><input id="sc-embd" class="scratch-input" type="number" value="768" min="64"/></div>
        <div class="scratch-field"><label>${t("models_scratch_heads")}</label><input id="sc-heads" class="scratch-input" type="number" value="12" min="1"/></div>
        <div class="scratch-field"><label>${t("models_scratch_ctx")}</label><input id="sc-ctx" class="scratch-input" type="number" value="1024" min="128"/></div>
        <div class="scratch-field" style="grid-column:1/-1"><label>${t("models_scratch_vocab")}</label><input id="sc-vocab" class="scratch-input" type="number" value="32000" min="1000"/></div>
      </div>
      <div class="scratch-params-preview" id="sc-preview"></div>
      <div class="scratch-err" id="sc-err"></div>
      <button class="btn-sm" onclick="submitScratch(this)">${t("models_scratch_create")}</button>
      <div class="training-note-text">${t("models_scratch_note")}</div>
    </div>
  </div>`;
}
function _calcScratchParams() {
  const layers = parseInt($("sc-layers").value) || 0;
  const embd   = parseInt($("sc-embd").value)   || 0;
  const vocab  = parseInt($("sc-vocab").value)   || 0;
  const p = layers * 12 * embd * embd + vocab * embd;
  const m = Math.round(p / 1e6 * 10) / 10;
  const prev = $("sc-preview");
  if (prev) prev.textContent = t("models_scratch_params").replace("{n}", m);
}
function _bindScratchInputs() {
  ["sc-layers","sc-embd","sc-heads","sc-ctx","sc-vocab"].forEach(id => {
    const el = $(id); if (el) el.addEventListener("input", _calcScratchParams);
  });
  _calcScratchParams();
}
async function submitScratch(btn) {
  const name = $("sc-name").value.trim();
  if (!name) { $("sc-err").textContent = t("models_scratch_name_ph"); return; }
  const body = {
    name,
    n_layers: parseInt($("sc-layers").value) || 12,
    n_embd:   parseInt($("sc-embd").value)   || 768,
    n_heads:  parseInt($("sc-heads").value)   || 12,
    n_ctx:    parseInt($("sc-ctx").value)     || 1024,
    vocab:    parseInt($("sc-vocab").value)   || 32000,
  };
  btn.disabled = true;
  const r = await apiJson("/api/models/scratch", { method: "POST", body: JSON.stringify(body) });
  btn.disabled = false;
  if (r.ok) { $("sc-err").textContent = ""; loadModels(); }
  else { $("sc-err").textContent = r.reason || t("error"); }
}

// ===== АГЕНТЫ (CRUD) =====
let _agentFormMode = null; // null | "add" | {id}

async function loadAgents() {
  const { agents } = await apiJson("/api/agents");
  const av = $("agents-view");
  const formHtml = _agentFormHtml();
  const cards = agents.length
    ? agents.map(a => `
        <div class="card" id="agent-card-${escapeText(a.id)}">
          <div class="card-info">
            <div class="card-title">${escapeText(a.name)}<span class="agent-card-model">${escapeText(a.model || "sonnet")}</span></div>
            <div class="card-sub">${escapeText(a.description || t("agents_no_desc"))}</div>
          </div>
          <button class="chat-action-btn" title="${t("agents_edit")}" onclick="editAgent(${JSON.stringify(a)})">✎</button>
          <button class="chat-action-btn" title="${t("delete")}" onclick="deleteAgent('${escapeText(a.id)}')">🗑</button>
        </div>`).join("")
    : `<div class="muted">${t("agents_empty")}</div>`;
  av.innerHTML = formHtml + cards;
}

function _agentFormHtml(prefill) {
  const p = prefill || {};
  return `<div class="agents-add-bar">
    <button class="btn-sm" onclick="showAgentForm()">${t("agents_add")}</button>
  </div>
  <div id="agent-form" class="agent-form hidden">
    <div class="agent-form-row">
      <span class="agent-form-label" style="min-width:0;flex:0 0 auto">${t("agents_name_ph")}</span>
      <input id="af-name" class="agent-input" placeholder="${t("agents_name_ph")}" value="${escapeText(p.name||"")}"/>
    </div>
    <div class="agent-form-row">
      <span class="agent-form-label" style="min-width:0;flex:0 0 auto">${t("agents_model_label")}</span>
      <select id="af-model" class="agent-model-select">
        ${["sonnet","opus","haiku"].map(m => `<option value="${m}"${(p.model||"sonnet")===m?" selected":""}>${m}</option>`).join("")}
      </select>
    </div>
    <div class="agent-form-row">
      <textarea id="af-desc" class="agent-textarea" style="min-height:48px" placeholder="${t("agents_desc_ph")}">${escapeText(p.description||"")}</textarea>
    </div>
    <div class="agent-form-row">
      <textarea id="af-prompt" class="agent-textarea" placeholder="${t("agents_prompt_ph")}">${escapeText(p.prompt||"")}</textarea>
    </div>
    <input type="hidden" id="af-id" value="${escapeText(p.id||"")}"/>
    <div class="agent-form-btns">
      <button class="btn-ghost" onclick="hideAgentForm()">${t("agents_cancel")}</button>
      <button class="btn-sm" onclick="saveAgent()">${t("agents_save")}</button>
    </div>
    <div id="af-err" class="err"></div>
  </div>`;
}

function showAgentForm(prefill) {
  const form = $("agent-form");
  if (!form) { loadAgents().then(() => showAgentForm(prefill)); return; }
  if (prefill) {
    $("af-name").value = prefill.name || "";
    $("af-model").value = prefill.model || "sonnet";
    $("af-desc").value = prefill.description || "";
    $("af-prompt").value = prefill.prompt || "";
    $("af-id").value = prefill.id || "";
  } else {
    $("af-name").value = ""; $("af-model").value = "sonnet";
    $("af-desc").value = ""; $("af-prompt").value = ""; $("af-id").value = "";
  }
  form.classList.remove("hidden");
}
function hideAgentForm() { const f = $("agent-form"); if (f) f.classList.add("hidden"); }

function editAgent(a) {
  if (typeof a === "string") a = JSON.parse(a);
  showAgentForm(a);
}

async function saveAgent() {
  const name = $("af-name").value.trim();
  if (!name) { $("af-err").textContent = t("agents_name_ph"); return; }
  const body = {
    name,
    description: $("af-desc").value.trim(),
    prompt: $("af-prompt").value.trim(),
    model: $("af-model").value,
    id: $("af-id").value || undefined,
  };
  const r = await apiJson("/api/agents", { method: "POST", body: JSON.stringify(body) });
  if (r.ok) { hideAgentForm(); loadAgents(); }
  else { $("af-err").textContent = r.reason || t("error"); }
}

async function deleteAgent(id) {
  if (!confirm(t("delete") + "?")) return;
  await api("/api/agents/" + id, { method: "DELETE" });
  loadAgents();
}

// ===== ОБУЧЕНИЕ =====
async function loadTraining() {
  const [{ models }, corpus] = await Promise.all([
    apiJson("/api/models"),
    apiJson("/api/data/corpus").catch(() => ({ files: 0, chars: 0, approx_tokens: 0 })),
  ]);
  const trainable = models.filter(m => m.trainable || m.trainable_local);
  const modelOpts = trainable.length
    ? trainable.map(m => `<option value="${escapeText(m.id)}">${escapeText(m.name)}</option>`).join("")
    : `<option value="">${t("error")}</option>`;

  $("training-view").innerHTML = `
    <div class="training-section">
      <div class="training-section-title">1. ${t("training_urls_label")}</div>
      <textarea id="tr-urls" class="training-textarea" placeholder="${t("training_urls_ph")}"></textarea>
      <div style="margin-top:10px;display:flex;gap:8px;align-items:center">
        <button class="btn-sm" onclick="doParse()">${t("training_parse_btn")}</button>
        <div id="tr-parse-msg" style="font-size:12px;color:#6b7280"></div>
      </div>
      <div id="tr-parse-result" class="training-parse-result hidden"></div>
    </div>
    <div class="training-section">
      <div class="training-section-title">${t("training_corpus_title")}</div>
      <div class="training-corpus-row" id="tr-corpus">
        <span class="training-corpus-item">${t("training_corpus_files")}: <strong>${corpus.files||0}</strong></span>
        <span class="training-corpus-item">${t("training_corpus_chars")}: <strong>${(corpus.chars||0).toLocaleString()}</strong></span>
        <span class="training-corpus-item">${t("training_corpus_tokens")}: <strong>${(corpus.approx_tokens||0).toLocaleString()}</strong></span>
      </div>
    </div>
    <div class="training-section">
      <div class="training-section-title">2. ${t("training_model_select")}</div>
      <select id="tr-model" class="training-select">${modelOpts}</select>
      <button class="btn-sm" onclick="doTrain()">${t("training_start_btn")}</button>
      <div id="tr-train-msg" style="font-size:12px;color:#6b7280;margin-top:6px"></div>
      <div class="training-note-text">${t("training_stage_note")}</div>
    </div>`;
}

async function doParse() {
  const raw = $("tr-urls").value.trim();
  if (!raw) return;
  const urls = raw.split("\n").map(s => s.trim()).filter(Boolean);
  const msg = $("tr-parse-msg"); const res = $("tr-parse-result");
  msg.textContent = t("training_parsing"); res.classList.add("hidden");
  try {
    const r = await apiJson("/api/data/parse", { method: "POST", body: JSON.stringify({ urls }) });
    const summary = t("training_parse_summary")
      .replace("{total}", r.urls || urls.length)
      .replace("{ok}", (r.results || []).filter(x => x.ok).length)
      .replace("{chars}", (r.chars || 0).toLocaleString())
      .replace("{tokens}", (r.approx_tokens || 0).toLocaleString());
    msg.textContent = summary;
    const lines = (r.results || []).map(x =>
      `<div class="${x.ok ? "ok" : "err-line"}">${x.ok ? "✓" : "✗"} ${escapeText(x.url)}: ${x.ok ? x.chars + " chars" : escapeText(x.error || "err")}</div>`
    ).join("");
    res.innerHTML = `<strong>${t("training_parse_result")}:</strong>${lines}`;
    res.classList.remove("hidden");
    // обновить corpus
    const c = await apiJson("/api/data/corpus").catch(() => null);
    if (c && $("tr-corpus")) {
      $("tr-corpus").innerHTML = `
        <span class="training-corpus-item">${t("training_corpus_files")}: <strong>${c.files||0}</strong></span>
        <span class="training-corpus-item">${t("training_corpus_chars")}: <strong>${(c.chars||0).toLocaleString()}</strong></span>
        <span class="training-corpus-item">${t("training_corpus_tokens")}: <strong>${(c.approx_tokens||0).toLocaleString()}</strong></span>`;
    }
  } catch (e) { msg.textContent = t("error"); }
}

async function doTrain() {
  const model_id = $("tr-model").value; if (!model_id) return;
  const msg = $("tr-train-msg");
  msg.textContent = t("loading");
  const r = await apiJson("/api/training/start", { method: "POST", body: JSON.stringify({ model_id }) });
  msg.textContent = r.ok ? t("training_start_ok") : (r.reason || t("training_start_err"));
}

// ===== ЛОГИ =====
let _logsTab = "actions"; // "actions" | "console"
let _logsFilter = "";
let _logsTimer = null;
let _logsPaused = false;
let _logsData = { lines: [], app: [] };

function _initLogsUI() {
  $("logs-view").innerHTML = `
    <div class="logs-toolbar">
      <div class="logs-tab-btns">
        <button class="logs-tab-btn ${_logsTab==="actions"?"active":""}" onclick="setLogsTab('actions')">${t("logs_tab_actions")}</button>
        <button class="logs-tab-btn ${_logsTab==="console"?"active":""}" onclick="setLogsTab('console')">${t("logs_tab_console")}</button>
      </div>
      <input class="logs-filter" id="logs-filter" placeholder="${t("logs_filter_ph")}" value="${escapeText(_logsFilter)}" oninput="_logsFilter=this.value;_renderLogs()"/>
      <button class="btn-ghost" id="logs-pause-btn" onclick="toggleLogsPause()">${_logsPaused ? t("logs_resume_poll") : t("logs_pause")}</button>
    </div>
    <div id="logs-pane-actions" class="logs-pane ${_logsTab==="actions"?"active":""}"></div>
    <div id="logs-pane-console" class="logs-pane ${_logsTab==="console"?"active":""}"></div>`;
}
function setLogsTab(tab) {
  _logsTab = tab;
  document.querySelectorAll(".logs-tab-btn").forEach(b => b.classList.toggle("active", b.textContent.trim() === t("logs_tab_" + tab)));
  document.querySelectorAll(".logs-pane").forEach(p => {
    p.classList.toggle("active", p.id === "logs-pane-" + tab);
  });
  _renderLogs();
}
function toggleLogsPause() {
  _logsPaused = !_logsPaused;
  const b = $("logs-pause-btn");
  if (b) b.textContent = _logsPaused ? t("logs_resume_poll") : t("logs_pause");
}
function _renderLogs() {
  const flt = _logsFilter.toLowerCase();
  // actions
  const ap = $("logs-pane-actions"); if (!ap) return;
  let lines = _logsData.lines || [];
  if (flt) lines = lines.filter(l => JSON.stringify(l).toLowerCase().includes(flt));
  if (!lines.length) { ap.innerHTML = `<div class="muted">${t("logs_empty")}</div>`; }
  else {
    const rows = lines.slice().reverse().map(l => {
      const { ts, action, ...rest } = l;
      const detail = Object.keys(rest).length ? JSON.stringify(rest) : "";
      return `<tr><td class="log-ts">${escapeText(ts || "")}</td>
        <td class="log-action">${escapeText(action || "")}</td>
        <td class="log-detail">${escapeText(detail)}</td></tr>`;
    }).join("");
    ap.innerHTML = `<table class="log-table"><thead><tr><th>${t("logs_time")}</th><th>${t("logs_action")}</th><th>${t("logs_detail")}</th></tr></thead><tbody>${rows}</tbody></table>`;
  }
  // console
  const cp = $("logs-pane-console"); if (!cp) return;
  let appLines = _logsData.app || [];
  if (flt) appLines = appLines.filter(l => l.toLowerCase().includes(flt));
  if (!appLines.length) { cp.innerHTML = `<div class="muted">${t("logs_no_app")}</div>`; }
  else {
    const prev = cp.querySelector(".logs-console");
    const wasAtBottom = !prev || prev.scrollHeight - prev.scrollTop - prev.clientHeight < 40;
    cp.innerHTML = `<div class="logs-console" id="logs-console-box">${appLines.map(l => escapeText(l)).join("\n")}</div>`;
    if (wasAtBottom) { const box = $("logs-console-box"); if (box) box.scrollTop = box.scrollHeight; }
  }
}
async function _fetchLogs() {
  if (_logsPaused) return;
  try {
    const d = await apiJson("/api/logs?limit=300");
    _logsData = d;
    _renderLogs();
  } catch (e) {}
}
async function loadLogs() {
  if (!$("logs-view").querySelector(".logs-toolbar")) _initLogsUI();
  await _fetchLogs();
  if (!_logsTimer) _logsTimer = setInterval(_fetchLogs, 3000);
}

// ===== СТАТУС =====
let _statusMetricsTimer = null;
let _statusCpuHist = [], _statusRamHist = [];

async function loadStatus() {
  const [s, stats] = await Promise.all([
    apiJson("/api/status"),
    apiJson("/api/stats").catch(() => ({})),
  ]);

  const card = (label, val, cls) =>
    `<div class="status-card2"><div class="sk">${label}</div><div class="sv ${cls||""}">${val}</div></div>`;

  const byDay = stats.by_day || {};
  const dayKeys = Object.keys(byDay).sort().slice(-14);
  const maxVal = dayKeys.reduce((m, k) => Math.max(m, byDay[k] || 0), 1);
  const barChart = dayKeys.length
    ? `<div class="status-bar-chart">
        <div class="status-bar-chart-title">${t("status_by_day")}</div>
        <div class="day-bars">
          ${dayKeys.map(k => {
            const pct = Math.round(((byDay[k]||0) / maxVal) * 100);
            const label = k.slice(5); // MM-DD
            return `<div class="day-bar-wrap">
              <div style="flex:1;display:flex;align-items:flex-end;width:100%">
                <div class="day-bar" style="height:${pct}%" title="${k}: ${byDay[k]}"></div>
              </div>
              <div class="day-bar-label">${label}</div>
            </div>`;
          }).join("")}
        </div>
      </div>` : "";

  $("status-view").innerHTML = `
    <div class="status-cards-row">
      ${card(t("active_model"), s.active_model || t("none"), "")}
      ${card(t("status_backend"), (s.features && s.features.device_backend) || "cpu", "")}
      ${card(t("status_model_loaded"), s.model_loaded ? t("status_yes") : t("status_no"), s.model_loaded ? "ok" : "bad")}
      ${card(t("adapter_label"), s.active_adapter || t("none"), "")}
      ${card(t("status_requests_total"), stats.total || 0, "")}
      ${card(t("status_requests_today"), stats.today || 0, "")}
      ${card(t("status_tokens"), (stats.tokens || 0).toLocaleString(), "")}
      ${card(t("status_tok_s"), stats.avg_tok_s ? stats.avg_tok_s.toFixed(1) : "—", "")}
    </div>
    <div class="chart-container" id="status-cpu-chart">
      <div class="chart-title">${t("cpu")} %</div>
      <canvas id="status-chart-cpu" width="800" height="100"></canvas>
    </div>
    <div class="chart-container" id="status-ram-chart">
      <div class="chart-title">${t("ram")} %</div>
      <canvas id="status-chart-ram" width="800" height="100"></canvas>
    </div>
    ${barChart}`;

  // запустить поллинг метрик для статус-панели
  if (!_statusMetricsTimer) {
    _statusMetricsTimer = setInterval(_pollStatusMetrics, 1500);
    _pollStatusMetrics();
  }
}

async function _pollStatusMetrics() {
  if (curPanel !== "status") return;
  try {
    const m = await apiJson("/api/metrics");
    if (m.error) return;
    _statusCpuHist.push(m.cpu); _statusRamHist.push(m.ram);
    if (_statusCpuHist.length > MAXP) _statusCpuHist.shift();
    if (_statusRamHist.length > MAXP) _statusRamHist.shift();
    drawChart($("status-chart-cpu"), _statusCpuHist, "#7c8cf8");
    drawChart($("status-chart-ram"), _statusRamHist, "#4ade80");
  } catch (e) {}
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
