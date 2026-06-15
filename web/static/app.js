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
  loadSettings();
  await loadChats();
  const saved = localStorage.getItem("curPanel");
  setPanel(saved && saved !== "login" ? saved : "chat");
  startMetricsLoop();
  loadSavedModel();
}

async function loadSavedModel() {
  if (modelLoaded) return;
  try {
    const { active } = await apiJson("/api/models/active");
    if (active) {
      await apiJson("/api/models/load", { method: "POST", body: JSON.stringify({ model_id: active }) });
      await refreshStatus();
    }
  } catch (e) {}
}

async function loadSettings() {
  try {
    const s = await apiJson("/api/settings");
    const mt = $("max-tokens"), nc = $("n-ctx");
    if (nc && s.n_ctx) nc.value = s.n_ctx;
    if (mt && s.max_tokens) { mt.value = s.max_tokens; mt.max = s.n_ctx || 131072; }
  } catch (e) {}
}
async function saveSettings() {
  const mt = $("max-tokens"), nc = $("n-ctx");
  const body = {
    max_tokens: parseInt(mt && mt.value) || 1024,
    n_ctx: parseInt(nc && nc.value) || 8192,
  };
  const r = await apiJson("/api/settings", { method: "POST", body: JSON.stringify(body) });
  if (mt && r.max_tokens) { mt.value = r.max_tokens; mt.max = r.n_ctx || 131072; }
  if (nc && r.n_ctx) nc.value = r.n_ctx;
  const s = $("max-tokens-saved");
  if (s) { s.textContent = "✓"; setTimeout(() => { s.textContent = ""; }, 1500); }
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
  curPanel = name;
  localStorage.setItem("curPanel", name);
  document.querySelectorAll(".nav-btn").forEach(b => b.classList.toggle("active", b.dataset.panel === name));
  document.querySelectorAll(".panel").forEach(p => p.classList.toggle("active", p.id === "panel-" + name));
  const loaders = {
    chat: () => { if (activeChatId && !generating) openChat(activeChatId); },
    models: loadModels, agents: loadAgents, training: loadTraining, logs: loadLogs,
    status: loadStatus, system: loadSystemOnce, files: loadFiles, terminal: loadTerminal, selfmod: loadSelfmod,
  };
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
  const autoCb = $("auto-mode-cb");
  if (autoCb && autoCb.checked) { ta.value = ""; ta.style.height = "auto"; return runAgent(msg); }
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

// ===== МОДЕЛИ (CRUD: полный) =====
async function loadModels() {
  const { models, active } = await apiJson("/api/models");
  const addBtn = `<button class="btn-sm" onclick="toggleAddModel()" style="margin-bottom:12px">${t("models_add_btn")}</button>`;
  const addForm = addModelFormHtml();
  const cards = models.map(m => {
    const isActive = m.id === active;
    let badge, actionBtn;
    if (isActive) {
      badge = `<span class="card-badge badge-active">${t("models_active_btn")}</span>`;
      actionBtn = `<button class="btn-sm" disabled>${t("models_active_btn")}</button>`;
    } else if (m.downloaded) {
      badge = `<span class="card-badge model-badge-installed">${t("models_status_installed")}</span>`;
      actionBtn = `<button class="btn-sm" onclick="doLoadModel('${m.id}', this)">${t("models_run_btn")}</button>`;
    } else if (m.type === "scratch") {
      badge = `<span class="card-badge model-badge-scratch">${t("models_status_not_trained")}</span>`;
      actionBtn = `<button class="btn-sm" disabled style="opacity:0.5">${t("models_status_not_trained")}</button>`;
    } else {
      badge = `<span class="card-badge model-badge-not-installed">${t("models_status_not_installed")}</span>`;
      actionBtn = `<button class="btn-sm" onclick="doLoadModel('${m.id}', this)">${t("models_download_run_btn")}</button>`;
    }
    const editBtn = `<button class="chat-action-btn" title="${t("models_edit_btn")}" onclick="toggleEditModel('${m.id}')">✎</button>`;
    const delBtn = m.source === "custom"
      ? `<button class="chat-action-btn" title="${t("delete")}" onclick="removeModel('${m.id}')">🗑</button>` : "";
    const editForm = `<div class="model-edit-form hidden" id="me-${escapeText(m.id)}">
      <input class="am-input me-name" value="${escapeText(m.name)}" placeholder="${t("models_field_name")}"/>
      <input class="am-input me-note" value="${escapeText(m.note || "")}" placeholder="${t("models_field_note")}"/>
      <input class="am-input me-quant" value="${escapeText(m.quant || "")}" placeholder="${t("models_field_quant")}"/>
      <input class="am-input me-size" type="number" step="0.1" value="${m.size_gb || 0}" placeholder="${t("models_field_size")}"/>
      <label class="muted" style="font-size:12px"><input type="checkbox" class="me-trainable" ${m.trainable ? "checked" : ""}/> ${t("models_field_trainable")}</label>
      <button class="btn-sm" onclick="saveEditModel('${m.id}')">${t("models_save_btn")}</button>
      ${m.source !== "custom" ? `<span class="muted" style="font-size:11px">${t("models_not_editable")}</span>` : ""}
    </div>`;
    return `<div class="card model-card" data-id="${m.id}">
      <div class="card-info">
        <div class="card-title">${escapeText(m.name)} ${badge}</div>
        <div class="card-sub">${escapeText(m.quant || "")} · ${m.size_gb || "?"} ГБ · ${escapeText(m.note || "")}</div>
      </div>
      <div class="model-actions">${editBtn}${delBtn}</div>
      ${actionBtn}
      ${editForm}
    </div>`;
  }).join("");
  $("models-view").innerHTML = `${addBtn}${addForm}<div class="models-list">${cards}</div>`;
}

function toggleEditModel(id) {
  const form = document.getElementById("me-" + id);
  if (form) form.classList.toggle("hidden");
}

async function saveEditModel(id) {
  const card = document.querySelector(`.model-card[data-id="${id}"]`);
  if (!card) return;
  const name = card.querySelector(".me-name").value.trim();
  const note = card.querySelector(".me-note").value.trim();
  const quant = card.querySelector(".me-quant").value.trim();
  const size_gb = parseFloat(card.querySelector(".me-size").value) || 0;
  const trainable = card.querySelector(".me-trainable").checked;
  const updates = { name, note, quant, size_gb, trainable };
  const r = await apiJson("/api/models/" + id, { method: "PUT", body: JSON.stringify(updates) });
  if (r.ok) loadModels();
  else alert(r.reason || t("error"));
}

function addModelFormHtml() {
  return `<div id="add-model-form" class="hidden add-model-form">
    <div class="add-model-tabs" id="amt-tabs">
      <span class="add-model-tab active" data-tab="hf" onclick="switchAddTab('hf')">${t("models_add_tab_hf")}</span>
      <span class="add-model-tab" data-tab="gguf" onclick="switchAddTab('gguf')">${t("models_add_tab_gguf")}</span>
      <span class="add-model-tab" data-tab="ov" onclick="switchAddTab('ov')">${t("models_add_tab_ov")}</span>
      <span class="add-model-tab" data-tab="scratch" onclick="switchAddTab('scratch')">${t("models_add_tab_scratch")}</span>
    </div>
    <div id="amt-repo" class="amt-group">
      <input id="am-repo" class="am-input" placeholder="${t("models_add_repo_ph")}"/>
    </div>
    <div id="amt-file" class="amt-group hidden">
      <div class="add-model-row" id="am-file-row"><input id="am-file" class="am-input" placeholder="${t("models_add_file_ph")}"/><button class="btn-sm" onclick="fetchRepoFiles()">${t("fetch_files")}</button></div>
    </div>
    <input id="am-name" class="am-input" placeholder="${t("models_add_name_ph")}"/>
    <div id="amt-scratch" class="amt-group hidden">
      <div class="scratch-fields">
        <div class="scratch-field"><label>${t("models_scratch_layers")}</label><input id="am-layers" class="scratch-input" type="number" value="12" min="1"/></div>
        <div class="scratch-field"><label>${t("models_scratch_embd")}</label><input id="am-embd" class="scratch-input" type="number" value="768" min="64"/></div>
        <div class="scratch-field"><label>${t("models_scratch_heads")}</label><input id="am-heads" class="scratch-input" type="number" value="12" min="1"/></div>
        <div class="scratch-field"><label>${t("models_scratch_ctx")}</label><input id="am-ctx" class="scratch-input" type="number" value="1024" min="128"/></div>
        <div class="scratch-field" style="grid-column:1/-1"><label>${t("models_scratch_vocab")}</label><input id="am-vocab" class="scratch-input" type="number" value="32000" min="1000"/></div>
      </div>
      <div class="scratch-params-preview" id="am-sc-preview">${t("models_scratch_params").replace("{n}", "?")}</div>
    </div>
    <div id="am-err" class="err"></div>
    <button class="btn-sm" onclick="submitAddModel()">${t("models_add_create")}</button>
  </div>`;
}
let _addModelTab = "hf";
function toggleAddModel() {
  const f = $("add-model-form");
  if (!f) return;
  f.classList.toggle("hidden");
  if (!f.classList.contains("hidden")) switchAddTab("hf");
}
function switchAddTab(tab) {
  _addModelTab = tab;
  document.querySelectorAll("#amt-tabs .add-model-tab").forEach(t => t.classList.toggle("active", t.dataset.tab === tab));
  document.getElementById("amt-repo").classList.toggle("hidden", tab === "scratch");
  document.getElementById("amt-file").classList.toggle("hidden", tab !== "gguf");
  document.getElementById("amt-scratch").classList.toggle("hidden", tab !== "scratch");
  _bindAddModelParams();
}
function _bindAddModelParams() {
  const el = $("am-embd");
  if (el) {
    const update = () => {
      const layers = parseInt($("am-layers")?.value) || 0;
      const embd = parseInt($("am-embd")?.value) || 0;
      const vocab = parseInt($("am-vocab")?.value) || 0;
      const p = layers * 12 * embd * embd + vocab * embd;
      const prev = $("am-sc-preview");
      if (prev) prev.textContent = t("models_scratch_params").replace("{n}", Math.round(p / 1e6 * 10) / 10);
    };
    ["am-layers","am-embd","am-heads","am-ctx","am-vocab"].forEach(id => {
      const e = $(id);
      if (e) e.addEventListener("input", update);
    });
    update();
  }
}

async function fetchRepoFiles() {
  const repo = $("am-repo")?.value?.trim();
  if (!repo) return;
  $("am-err").textContent = t("loading");
  try {
    const r = await apiJson("/api/models/repo_files?repo=" + encodeURIComponent(repo));
    if (r.error || !r.files.length) { $("am-err").textContent = r.error || t("error"); return; }
    const fileRow = $("am-file-row");
    if (fileRow) {
      fileRow.innerHTML = `<select id="am-file" class="am-input">${r.files.map(f => `<option value="${escapeText(f)}">${escapeText(f)}</option>`).join("")}</select>`;
    }
    $("am-err").textContent = "";
  } catch (e) { $("am-err").textContent = t("error"); }
}
async function submitAddModel() {
  const source = _addModelTab;
  if (source === "scratch") {
    const name = $("am-name")?.value?.trim();
    if (!name) { $("am-err").textContent = t("models_add_name_ph"); return; }
    const n_embd = parseInt($("am-embd")?.value) || 768;
    const n_heads = parseInt($("am-heads")?.value) || 12;
    if (n_embd % n_heads !== 0) {
      $("am-err").textContent = `Размерность ${n_embd} не кратна числу голов ${n_heads}. Исправьте.`;
      return;
    }
    const body = {
      name, n_layers: parseInt($("am-layers")?.value) || 12, n_embd, n_heads,
      n_ctx: parseInt($("am-ctx")?.value) || 1024, vocab: parseInt($("am-vocab")?.value) || 32000,
    };
    $("am-err").textContent = "";
    const r = await apiJson("/api/models/scratch", { method: "POST", body: JSON.stringify(body) });
    if (r.ok) { toggleAddModel(); loadModels(); }
    else { $("am-err").textContent = r.reason || t("error"); }
    return;
  }
  const repo = $("am-repo")?.value?.trim();
  const filename = $("am-file")?.value?.trim() || "";
  const name = $("am-name")?.value?.trim() || filename.replace(".gguf", "") || repo.split("/").pop() || "model";
  if (!repo) { $("am-err").textContent = "Укажите репозиторий"; return; }
  const body = { name, repo, filename,
    type: source === "ov" ? "ov" : "hf",
    note: source === "gguf" ? "GGUF" : source === "ov" ? "OpenVINO" : "safetensors",
  };
  $("am-err").textContent = "";
  const r = await apiJson("/api/models/add", { method: "POST", body: JSON.stringify(body) });
  if (r.ok) { toggleAddModel(); loadModels(); }
  else { $("am-err").textContent = r.reason || t("error"); }
}
async function removeModel(id) {
  if (!confirm(t("delete") + "?")) return;
  await api("/api/models/" + id, { method: "DELETE" });
  loadModels();
}
async function doLoadModel(id, btn) {
  btn.disabled = true; btn.textContent = t("loading_model");
  try {
    const r = await apiJson("/api/models/load", { method: "POST", body: JSON.stringify({ model_id: id }) });
    if (r && r.ok === false) alert(r.reason || t("error"));
    await refreshStatus(); await loadModels();
  } catch (e) { btn.disabled = false; btn.textContent = t("error"); }
}

// ===== АГЕНТЫ (CRUD) =====
let _agentFormMode = null; // null | "add" | {id}

let _agentsCache = {};
async function loadAgents() {
  const { agents } = await apiJson("/api/agents");
  _agentsCache = {};
  agents.forEach(a => { _agentsCache[a.id] = a; });
  const av = $("agents-view");
  const formHtml = _agentFormHtml();
  const cards = agents.length
    ? agents.map(a => `
        <div class="card" id="agent-card-${escapeText(a.id)}">
          <div class="card-info">
            <div class="card-title">${escapeText(a.name)}<span class="agent-card-model">${escapeText(a.model || "sonnet")}</span></div>
            <div class="card-sub">${escapeText(a.description || t("agents_no_desc"))}</div>
          </div>
          <button class="chat-action-btn" title="${t("agents_edit")}" onclick="editAgent('${escapeText(a.id)}')">✎</button>
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

function editAgent(id) {
  const a = _agentsCache[id];
  if (a) showAgentForm(a);
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

// ===== ОБУЧЕНИЕ (полный редизайн) =====
let _trainTimer = null;
let _trainLossHist = [];
let _trainPplHist = [];

async function loadTraining() {
  const [{ models, active }, corpus] = await Promise.all([
    apiJson("/api/models"),
    apiJson("/api/data/corpus").catch(() => ({ files: 0, chars: 0, approx_tokens: 0 })),
  ]);
  const allOpts = models.map(m => `<option value="${escapeText(m.id)}"${m.id === active ? " selected" : ""}>${escapeText(m.name)}${m.type === "scratch" ? " (своя)" : ""}</option>`).join("");
  const modelOpts = allOpts || `<option value="">—</option>`;

  $("training-view").innerHTML = `
    <div class="training-section">
      <div class="training-section-title">📊 ${t("train_dataset")}</div>
      <div class="train-dataset-row" id="tr-corpus">
        <span>${t("train_corpus_files")}: <strong>${corpus.files||0}</strong></span>
        <span>${t("train_corpus_chars")}: <strong>${(corpus.chars||0).toLocaleString()}</strong></span>
        <span>${t("train_corpus_tokens")}: <strong>${(corpus.approx_tokens||0).toLocaleString()}</strong></span>
        <button class="btn-ghost" onclick="showDataPanel()">📥 Сбор данных</button>
        <button class="btn-ghost" onclick="toggleDatasetView()">${t("dataset_view_btn")}</button>
      </div>
      <div id="tr-dataset-view" class="hidden train-data-panel" style="margin-top:10px"></div>
    </div>
    <div class="training-section">
      <div class="training-section-title">⚙️ ${t("training_model_select")}</div>
      <div class="train-grid">
        <div class="train-field"><label>${t("train_mode")}</label>
          <select id="tr-mode" class="train-select" onchange="onTrainModeChange()">
            <option value="scratch">${t("train_mode_scratch")}</option>
            <option value="distill">${t("train_mode_distill")}</option>
          </select></div>
        <div class="train-field"><label>${t("train_target")}</label>
          <select id="tr-model" class="train-select">${modelOpts}</select></div>
        <div class="train-field hidden" id="tr-teacher-field"><label>${t("train_teacher")}</label>
          <select id="tr-teacher" class="train-select">${modelOpts}</select></div>
        <div class="train-field"><label>${t("train_epochs")}</label>
          <input id="tr-epochs" class="train-num" type="number" value="1" min="1" max="100"/></div>
        <div class="train-field"><label>${t("train_lr")}</label>
          <input id="tr-lr" class="train-num" type="number" value="0.0002" step="0.0001" min="1e-6" max="0.1"/></div>
        <div class="train-field buttons-row">
          <button class="btn-sm" id="tr-start-btn" onclick="doTrain()">${t("train_start")}</button>
          <button class="btn-sm" id="tr-stop-btn" style="display:none;background:#7f1d1d;border:1px solid #ef4444;color:#fca5a5" onclick="stopTrain()">${t("train_stop")}</button>
        </div>
      </div>
      <div id="tr-train-status" class="hidden train-status">
        <div class="train-progress-wrap"><div class="train-progress-bar" id="tr-progress" style="width:0%"></div></div>
        <div class="train-metrics" id="tr-metrics"></div>
        <canvas id="tr-loss-chart" width="600" height="140" class="train-loss-chart hidden"></canvas>
      </div>
      <div class="training-note-text">${t("train_modes_note")}</div>
    </div>
    <div class="training-section">
      <div class="training-section-title">📜 ${t("train_history_title")}</div>
      <div id="tr-history"></div>
    </div>`;
  loadTrainHistory();
  _trainLossHist = [];
  _trainPplHist = [];
}

function onTrainModeChange() {
  const v = $("tr-mode")?.value;
  $("tr-teacher-field").classList.toggle("hidden", v !== "distill");
}

function showDataPanel() {
  const p = $("tr-corpus");
  if (!p) return;
  // inline expand для сбора данных
  let dataDiv = $("tr-data-panel");
  if (dataDiv) { dataDiv.classList.toggle("hidden"); return; }
  const html = `<div id="tr-data-panel" class="train-data-panel">
    <div class="train-data-row">
      <textarea id="tr-urls" class="training-textarea" placeholder="${t("training_urls_ph")}" style="min-height:60px;flex:1"></textarea>
      <div class="train-data-actions">
        <button class="btn-sm" onclick="doParse()">${t("training_parse_btn")}</button>
        <button class="btn-sm" id="cr-start-btn" onclick="startCrawl()">${t("crawl_start_btn")}</button>
        <button class="btn-sm" style="display:none" id="cr-stop-btn2" onclick="stopCrawl()">${t("crawl_stop_btn")}</button>
      </div>
    </div>
    <div id="tr-parse-msg" style="font-size:12px;color:#6b7280"></div>
    <div id="tr-parse-result" class="training-parse-result hidden"></div>
    <div class="crawl-row">
      <input id="cr-url" class="am-input crawl-url-input" placeholder="${t("crawl_url_ph")}" value="https://"/>
      <label class="crawl-label">${t("crawl_depth")}: <input id="cr-depth" class="crawl-num-input" type="number" value="2" min="1" max="10"/></label>
      <label class="crawl-label">${t("crawl_max")}: <input id="cr-max" class="crawl-num-input" type="number" value="50" min="1" max="1000"/></label>
    </div>
    <div id="cr-status" class="crawl-status hidden">
      <div class="crawl-stats">
        <span>${t("crawl_pages")}: <strong id="cr-pages">0</strong></span>
        <span>${t("crawl_chars")}: <strong id="cr-chars">0</strong></span>
        <span>${t("crawl_errors")}: <strong id="cr-errors">0</strong></span>
        <span id="cr-state" class="crawl-state"></span>
      </div>
      <div class="crawl-progress-wrap"><div class="crawl-progress-bar" id="cr-progress" style="width:0%"></div></div>
      <div class="crawl-chart-wrap hidden"><canvas id="cr-chart" width="600" height="120"></canvas></div>
    </div>
    <div id="cr-log" class="crawl-log"></div>
  </div>`;
  p.parentElement.insertAdjacentHTML("afterend", html);
}

async function doParse() {
  const raw = $("tr-urls")?.value?.trim();
  if (!raw) return;
  const urls = raw.split("\n").map(s => s.trim()).filter(Boolean);
  const msg = $("tr-parse-msg"); const res = $("tr-parse-result");
  if (!msg || !res) return;
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
    updateTrainingCorpus();
  } catch (e) { msg.textContent = t("error"); }
}

async function updateTrainingCorpus() {
  const c = await apiJson("/api/data/corpus").catch(() => null);
  if (c && $("tr-corpus")) {
    $("tr-corpus").innerHTML = `
      <span>${t("train_corpus_files")}: <strong>${c.files||0}</strong></span>
      <span>${t("train_corpus_chars")}: <strong>${(c.chars||0).toLocaleString()}</strong></span>
      <span>${t("train_corpus_tokens")}: <strong>${(c.approx_tokens||0).toLocaleString()}</strong></span>
      <button class="btn-ghost" onclick="showDataPanel()">📥 Сбор данных</button>
      <button class="btn-ghost" onclick="toggleDatasetView()">${t("dataset_view_btn")}</button>`;
  }
}

// ===== DATASET VIEWER =====
let _datasetPage = 1;

async function toggleDatasetView() {
  const el = $("tr-dataset-view");
  if (!el) return;
  el.classList.toggle("hidden");
  if (!el.classList.contains("hidden")) {
    _datasetPage = 1;
    await loadDatasetPage();
  }
}

async function loadDatasetPage() {
  const el = $("tr-dataset-view");
  if (!el) return;
  const r = await apiJson(`/api/data/corpus/content?page=${_datasetPage}&per_page=10`).catch(() => null);
  if (!r) { el.innerHTML = `<div class="muted">${t("error")}</div>`; return; }
  if (!r.items || !r.items.length) {
    el.innerHTML = `<div class="muted">${t("dataset_empty")}</div>`;
    return;
  }
  const totalPages = Math.ceil(r.total / r.per_page);
  const items = r.items.map((item, idx) => {
    const preview = item.text.length > 200 ? item.text.slice(0, 200) + "…" : item.text;
    return `<div class="dataset-block" data-id="${escapeText(item.id)}">
      <div class="dataset-block-header">
        <span class="dataset-block-file">📄 ${escapeText(item.file)}</span>
        <span class="dataset-block-chars">${item.chars.toLocaleString()} ${t("train_corpus_chars")}</span>
      </div>
      <pre class="dataset-block-text">${escapeText(preview)}</pre>
      <div class="dataset-block-actions">
        <button class="btn-ghost btn-xs" onclick="deleteDatasetBlock('${escapeText(item.id)}', this)">${t("dataset_block_delete")}</button>
        ${item.text.length > 200 ? `<button class="btn-ghost btn-xs" onclick="toggleBlockFull(this)">${t("show_more") || "Показать все"}</button>` : ""}
      </div>
    </div>`;
  }).join("");
  el.innerHTML = `
    <div class="dataset-toolbar">
      <span class="dataset-page-info">${t("dataset_page_of").replace("{page}", _datasetPage).replace("{total}", totalPages)}</span>
      <div class="dataset-toolbar-actions">
        <button class="btn-ghost btn-xs" onclick="clearDataset()">${t("dataset_clear_btn")}</button>
        <button class="btn-ghost btn-xs" onclick="setDatasetPage(${_datasetPage - 1})" ${_datasetPage <= 1 ? "disabled" : ""}>${t("dataset_page_prev")}</button>
        <button class="btn-ghost btn-xs" onclick="setDatasetPage(${_datasetPage + 1})" ${_datasetPage >= totalPages ? "disabled" : ""}>${t("dataset_page_next")}</button>
      </div>
    </div>
    ${items}`;
}

function setDatasetPage(p) {
  _datasetPage = p;
  loadDatasetPage();
}

async function deleteDatasetBlock(id, btn) {
  btn.disabled = true;
  btn.textContent = "…";
  const r = await apiJson(`/api/data/corpus/content/${encodeURIComponent(id)}`, { method: "DELETE" }).catch(() => null);
  if (r && r.ok) {
    const block = btn.closest(".dataset-block");
    if (block) block.remove();
    btn.textContent = t("dataset_block_deleted");
    updateTrainingCorpus();
  } else {
    btn.disabled = false;
    btn.textContent = t("error");
  }
}

async function clearDataset() {
  if (!confirm(t("dataset_clear_confirm"))) return;
  await apiJson("/api/data/corpus/clear", { method: "POST" });
  const el = $("tr-dataset-view");
  if (el) el.innerHTML = `<div class="muted">${t("dataset_cleared")}</div>`;
  updateTrainingCorpus();
}

function toggleBlockFull(btn) {
  const block = btn.closest(".dataset-block");
  if (!block) return;
  const pre = block.querySelector(".dataset-block-text");
  if (!pre) return;
  const isFull = pre.classList.toggle("dataset-block-full");
  btn.textContent = isFull ? (t("show_less") || "Скрыть") : (t("show_more") || "Показать все");
}

// ===== CRAWL (встроен в панель данных) =====
let _crawlTimer = null;
let _crawlPagesHist = [];
let _crawlCharsHist = [];

async function startCrawl() {
  const url = $("cr-url")?.value?.trim();
  if (!url) return;
  const depth = parseInt($("cr-depth")?.value) || 2;
  const max_pages = parseInt($("cr-max")?.value) || 50;
  $("cr-start-btn").style.display = "none";
  const stopBtn2 = $("cr-stop-btn2");
  if (stopBtn2) stopBtn2.style.display = "";
  $("cr-status").classList.remove("hidden");
  $("cr-log").innerHTML = "";
  _crawlPagesHist = [];
  _crawlCharsHist = [];
  const canvasWrap = document.querySelector(".crawl-chart-wrap");
  if (canvasWrap) canvasWrap.classList.remove("hidden");
  const r = await apiJson("/api/data/parse/crawl", { method: "POST", body: JSON.stringify({ url, depth, max_pages }) });
  if (!r.ok) { $("cr-start-btn").style.display = ""; if (stopBtn2) stopBtn2.style.display = "none"; return; }
  if (_crawlTimer) clearInterval(_crawlTimer);
  _crawlTimer = setInterval(pollCrawl, 1000);
  pollCrawl();
}

async function stopCrawl() {
  await apiJson("/api/data/parse/crawl/stop", { method: "POST" });
  $("cr-start-btn").style.display = "";
  const stopBtn2 = $("cr-stop-btn2");
  if (stopBtn2) stopBtn2.style.display = "none";
}

async function pollCrawl() {
  const s = await apiJson("/api/data/parse/crawl").catch(() => null);
  if (!s) return;
  const pagesEl = $("cr-pages"); if (pagesEl) pagesEl.textContent = s.ok;
  const charsEl = $("cr-chars"); if (charsEl) charsEl.textContent = (s.chars || 0).toLocaleString();
  const errEl = $("cr-errors"); if (errEl) errEl.textContent = s.errors;
  const stEl = $("cr-state");
  if (stEl) {
    if (s.state === "running") { stEl.textContent = "⏳ " + t("crawl_state_running"); stEl.className = "crawl-state running"; }
    else if (s.state === "done") {
      stEl.textContent = "✅ " + t("crawl_state_done"); stEl.className = "crawl-state done";
      $("cr-start-btn").style.display = "";
      const stopBtn2 = $("cr-stop-btn2"); if (stopBtn2) stopBtn2.style.display = "none";
      if (_crawlTimer) { clearInterval(_crawlTimer); _crawlTimer = null; }
      updateTrainingCorpus();
    } else if (s.state === "stopped") {
      stEl.textContent = "⏹ " + t("crawl_state_stopped"); stEl.className = "crawl-state stopped";
      $("cr-start-btn").style.display = "";
      const stopBtn2 = $("cr-stop-btn2"); if (stopBtn2) stopBtn2.style.display = "none";
      if (_crawlTimer) { clearInterval(_crawlTimer); _crawlTimer = null; }
      updateTrainingCorpus();
    } else { stEl.textContent = t("crawl_state_idle"); stEl.className = "crawl-state"; }
  }
  const total = s.ok + s.errors || 1;
  const maxPages = parseInt($("cr-max")?.value) || 1;
  const pct = Math.min(100, Math.round((s.ok + s.errors) / Math.max(maxPages, total) * 100));
  const prog = $("cr-progress"); if (prog) prog.style.width = pct + "%";
  const pages = s.pages || [];
  const logEl = $("cr-log");
  if (logEl) {
    logEl.innerHTML = pages.slice(-10).map(p =>
      `<div class="crawl-log-item">${escapeText(p.url)} — ${p.chars} chars (depth ${p.depth})</div>`
    ).join("");
  }
  // chart
  _crawlPagesHist.push(s.ok);
  _crawlCharsHist.push(s.chars || 0);
  if (_crawlPagesHist.length > 300) { _crawlPagesHist.shift(); _crawlCharsHist.shift(); }
  drawCrawlChart();
}

function drawCrawlChart() {
  const cv = $("cr-chart");
  if (!cv) return;
  const dpr = window.devicePixelRatio || 1;
  const cssW = 600, cssH = 120;
  cv.width = cssW * dpr;
  cv.height = cssH * dpr;
  cv.style.width = cssW + "px";
  cv.style.height = cssH + "px";
  const ctx = cv.getContext("2d");
  ctx.scale(dpr, dpr);
  ctx.clearRect(0, 0, cssW, cssH);
  if (_crawlPagesHist.length < 2) return;
  const pad = { top: 8, bottom: 16, left: 36, right: 10 };
  const plotW = cssW - pad.left - pad.right;
  const plotH = cssH - pad.top - pad.bottom;
  _drawChartGrid(ctx, pad.left, pad.top, plotW, plotH, 3);
  // pages (green)
  _drawSingleLine(ctx, _crawlPagesHist, pad.left, pad.top, plotW, plotH,
    "#4ade80", "rgba(74,222,128,0.10)");
  // chars (blue)
  _drawSingleLine(ctx, _crawlCharsHist, pad.left, pad.top, plotW, plotH,
    "#818cf8", "rgba(129,140,248,0.10)");
  // labels
  ctx.font = "9px sans-serif";
  ctx.fillStyle = "#4b5563"; ctx.textAlign = "right";
  const maxP = Math.max(..._crawlPagesHist), maxC = Math.max(..._crawlCharsHist);
  ctx.fillText(maxP, pad.left - 4, pad.top + 10);
  ctx.fillText(0, pad.left - 4, pad.top + plotH);
  ctx.textAlign = "left";
  // legend
  const lastP = _crawlPagesHist[_crawlPagesHist.length - 1];
  const lastC = _crawlCharsHist[_crawlCharsHist.length - 1];
  ctx.font = "10px sans-serif";
  ctx.fillStyle = "#4ade80";
  ctx.fillRect(pad.left, cssH - 14, 8, 2);
  ctx.fillStyle = "#9ca3af";
  ctx.fillText(`${t("crawl_pages")}: ${lastP}`, pad.left + 12, cssH - 10);
  ctx.fillStyle = "#818cf8";
  ctx.fillRect(pad.left + 100, cssH - 14, 8, 2);
  ctx.fillStyle = "#9ca3af";
  ctx.fillText(`${t("crawl_chars")}: ${_fmtChartNum(lastC)}`, pad.left + 112, cssH - 10);
}

// ===== TRAINING CORE =====
async function doTrain() {
  const model_id = $("tr-model")?.value;
  if (!model_id) return;
  const mode = ($("tr-mode") || {}).value || "scratch";
  const teacher_id = mode === "distill" ? ($("tr-teacher") || {}).value : null;
  const epochs = parseInt($("tr-epochs")?.value) || 1;
  const lr = parseFloat($("tr-lr")?.value) || 2e-4;
  const statusEl = $("tr-train-status"); if (statusEl) statusEl.classList.remove("hidden");
  const msg = $("tr-metrics"); if (msg) msg.innerHTML = t("loading");
  $("tr-start-btn").style.display = "none";
  $("tr-stop-btn").style.display = "";
  _trainLossHist = [];
  _trainPplHist = [];
  const r = await apiJson("/api/training/start", { method: "POST", body: JSON.stringify({ model_id, mode, teacher_id, epochs, lr }) });
  if (!r.ok) {
    if (msg) msg.innerHTML = `⚠ ${escapeText(r.reason || t("training_start_err"))}`;
    $("tr-start-btn").style.display = ""; $("tr-stop-btn").style.display = "none";
    return;
  }
  if (_trainTimer) clearInterval(_trainTimer);
  _trainTimer = setInterval(pollTrain, 1500); pollTrain();
}

async function pollTrain() {
  const s = await apiJson("/api/training/status").catch(() => null);
  if (!s) return;
  const msg = $("tr-metrics"); const prog = $("tr-progress"); const statusEl = $("tr-train-status");
  if (!msg) return;
  if (s.state === "running") {
    const pct = Math.round((s.progress || 0) * 100);
    if (prog) prog.style.width = pct + "%";
    if (s.loss != null) {
    _trainLossHist.push(s.loss);
    _trainPplHist.push(Math.exp(s.loss));
  }
    const speed = s.step > 0 && s.total > 0 ? (s.step / (s.total * 0.001 || 1)).toFixed(2) : "—";
    const lastLoss = s.loss != null ? s.loss.toFixed(4) : "—";
    const lastPpl = s.loss != null ? Math.exp(s.loss).toFixed(2) : "—";
    msg.innerHTML = `<span class="train-metric">${t("train_step")}: <b>${s.step}</b>/${s.total}</span>
      <span class="train-metric">${t("train_loss")}: <b>${lastLoss}</b></span>
      <span class="train-metric">${t("train_chart_perplexity")}: <b>${lastPpl}</b></span>
      <span class="train-metric">${t("train_speed")}: <b>${speed} ${t("train_samples_sec")}</b></span>
      <span class="train-metric">📋 ${escapeText(s.stage)}</span>
      <span class="train-metric"><button class="btn-sm" onclick="stopTrain()" style="background:#7f1d1d;border:1px solid #ef4444;color:#fca5a5;padding:2px 8px">${t("train_stop")}</button></span>`;
    drawTrainLossChart();
  } else if (s.state === "done") {
    if (prog) prog.style.width = "100%";
    msg.innerHTML = `✅ ${t("done")} · loss: ${s.loss != null ? s.loss.toFixed(4) : "—"}`;
    $("tr-start-btn").style.display = ""; $("tr-stop-btn").style.display = "none";
    clearInterval(_trainTimer); _trainTimer = null;
    loadTrainHistory();
  } else if (s.state === "error") {
    msg.innerHTML = `⚠ ${escapeText(s.error || t("error"))}`;
    $("tr-start-btn").style.display = ""; $("tr-stop-btn").style.display = "none";
    clearInterval(_trainTimer); _trainTimer = null;
  } else if (s.state === "stopped") {
    msg.innerHTML = "⏹ " + t("agent_stopped");
    $("tr-start-btn").style.display = ""; $("tr-stop-btn").style.display = "none";
    clearInterval(_trainTimer); _trainTimer = null;
  } else {
    msg.innerHTML = escapeText(s.stage || "");
  }
}

function _fmtChartNum(v) {
  if (v >= 1e6) return (v / 1e6).toFixed(1) + "M";
  if (v >= 1e3) return (v / 1e3).toFixed(1) + "K";
  return v.toFixed(2);
}

function _drawSingleLine(ctx, data, x0, y0, w, h, color, fillColor) {
  if (data.length < 2) return;
  const min = Math.min(...data), max = Math.max(...data);
  const range = Math.max(max - min, 0.001);
  const step = w / Math.max(data.length - 1, 1);
  ctx.strokeStyle = color; ctx.lineWidth = 2; ctx.beginPath();
  data.forEach((v, i) => {
    const x = x0 + i * step, y = y0 + h - ((v - min) / range) * h;
    i ? ctx.lineTo(x, y) : ctx.moveTo(x, y);
  });
  ctx.stroke();
  ctx.lineTo(x0 + (data.length - 1) * step, y0 + h);
  ctx.lineTo(x0, y0 + h); ctx.closePath();
  ctx.fillStyle = fillColor; ctx.fill();
}

function _drawChartGrid(ctx, x0, y0, w, h, n) {
  ctx.strokeStyle = "#1e2230"; ctx.lineWidth = 1;
  for (let i = 0; i <= n; i++) {
    const y = y0 + (h / n) * i;
    ctx.beginPath(); ctx.moveTo(x0, y); ctx.lineTo(x0 + w, y); ctx.stroke();
  }
}

function drawTrainLossChart() {
  const cv = $("tr-loss-chart");
  if (!cv) return;
  cv.classList.remove("hidden");
  const dpr = window.devicePixelRatio || 1;
  const cssW = 600, cssH = 140;
  cv.width = cssW * dpr;
  cv.height = cssH * dpr;
  cv.style.width = cssW + "px";
  cv.style.height = cssH + "px";
  const ctx = cv.getContext("2d");
  ctx.scale(dpr, dpr);
  ctx.clearRect(0, 0, cssW, cssH);
  const n = _trainLossHist.length;
  if (n < 2) return;
  // split into two equal charts: loss (top) | perplexity (bottom)
  const halfH = (cssH - 4) / 2;
  const padL = 42, padR = 10, padT = 14, padB = 8;
  const plotW = cssW - padL - padR;

  function drawMini(data, yOff, color, fillColor, label, fmtFn) {
    const plotH = halfH - padT - padB;
    const y0 = yOff + padT;
    _drawChartGrid(ctx, padL, y0, plotW, plotH, 2);
    _drawSingleLine(ctx, data, padL, y0, plotW, plotH, color, fillColor);
    // label + current value
    const last = data[n - 1];
    ctx.font = "600 11px sans-serif";
    ctx.fillStyle = "#9ca3af";
    ctx.fillText(label, padL, yOff + 11);
    ctx.fillStyle = color;
    ctx.fillText(fmtFn(last), padL + ctx.measureText(label).width + 8, yOff + 11);
    // Y-axis min/max
    const min = Math.min(...data), max = Math.max(...data);
    ctx.font = "9px sans-serif";
    ctx.fillStyle = "#4b5563";
    ctx.textAlign = "right";
    ctx.fillText(fmtFn(max), padL - 4, y0 + 10);
    ctx.fillText(fmtFn(min), padL - 4, y0 + plotH);
    ctx.textAlign = "left";
  }

  drawMini(_trainLossHist, 0, "#f59e0b", "rgba(245,158,11,0.10)",
    t("train_chart_loss") + ":", v => v.toFixed(4));
  drawMini(_trainPplHist, halfH + 4, "#3b82f6", "rgba(59,130,246,0.10)",
    t("train_chart_perplexity") + ":", _fmtChartNum);
}

async function stopTrain() { await apiJson("/api/training/stop", { method: "POST" }); }

async function loadTrainHistory() {
  const el = $("tr-history");
  if (!el) return;
  const r = await apiJson("/api/training/history").catch(() => ({ history: [] }));
  const h = r.history || [];
  if (!h.length) { el.innerHTML = `<span class="muted">${t("train_history_empty")}</span>`; return; }
  const rows = h.slice().reverse().map(x => {
    const date = new Date((x.ts || 0) * 1000).toLocaleString();
    const modeLabel = x.mode === "scratch" ? t("train_mode_scratch") : t("train_mode_distill");
    return `<div class="train-history-item">
      <div class="train-history-info">
        <div class="train-history-title">${escapeText(x.model_id || "")} · ${escapeText(modeLabel)}</div>
        <div class="train-history-meta">${escapeText(date)} · ${x.steps || 0} ${t("train_history_steps")}</div>
      </div>
      <div class="train-history-loss">${x.loss != null ? x.loss.toFixed(4) : "—"}</div>
    </div>`;
  }).join("");
  el.innerHTML = rows;
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
    cp.innerHTML = `<pre class="logs-console" id="logs-console-box">${appLines.map(l => escapeText(l)).join("\n")}</pre>`;
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

// ===== СТАТУС (аналитика чатов/сообщений, без CPU/RAM) =====
async function loadStatus() {
  const [s, stats, chatsData] = await Promise.all([
    apiJson("/api/status"),
    apiJson("/api/stats").catch(() => ({})),
    apiJson("/api/chats").catch(() => ({ chats: [] })),
  ]);
  const chatsN = (chatsData.chats || []).length;
  const total = stats.total || 0, tokens = stats.tokens || 0;
  const avgLen = total ? Math.round(tokens / total) : 0;

  const card = (label, val, cls) =>
    `<div class="status-card2"><div class="sk">${label}</div><div class="sv ${cls||""}">${val}</div></div>`;

  const bars = (title, obj, color) => {
    const keys = Object.keys(obj).sort().slice(-14);
    const max = keys.reduce((m, k) => Math.max(m, obj[k] || 0), 1);
    if (!keys.length) return `<div class="status-bar-chart"><div class="status-bar-chart-title">${title}</div><div class="muted">${t("no_data")}</div></div>`;
    return `<div class="status-bar-chart"><div class="status-bar-chart-title">${title}</div>
      <div class="day-bars">${keys.map(k => {
        const pct = Math.round(((obj[k]||0) / max) * 100);
        return `<div class="day-bar-wrap"><div style="flex:1;display:flex;align-items:flex-end;width:100%">
          <div class="day-bar" style="height:${pct}%;background:${color}" title="${k}: ${obj[k]}"></div></div>
          <div class="day-bar-label">${k.slice(5)}</div></div>`;
      }).join("")}</div></div>`;
  };

  // токены по дням (из history)
  const tokByDay = {};
  (stats.history || []).forEach(h => {
    const d = new Date((h.ts || 0) * 1000).toISOString().slice(0, 10);
    tokByDay[d] = (tokByDay[d] || 0) + (h.tokens || 0);
  });

  $("status-view").innerHTML = `
    <div class="status-cards-row">
      ${card(t("status_chats"), chatsN)}
      ${card(t("status_requests_total"), total)}
      ${card(t("status_requests_today"), stats.today || 0)}
      ${card(t("status_tokens"), tokens.toLocaleString())}
      ${card(t("status_tok_s"), stats.avg_tok_s ? stats.avg_tok_s.toFixed(1) : "—")}
      ${card(t("status_avg_len"), avgLen + " " + t("tok_short"))}
      ${card(t("active_model"), s.active_model || t("none"))}
      ${card(t("status_model_loaded"), s.model_loaded ? t("status_yes") : t("status_no"), s.model_loaded ? "ok" : "bad")}
    </div>
    ${bars(t("status_by_day"), stats.by_day || {}, "#7c8cf8")}
    ${bars(t("status_tokens_by_day"), tokByDay, "#4ade80")}`;
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

// ===== ФАЙЛЫ =====
function escapeAttr(s) { return String(s).replace(/\\/g, "\\\\").replace(/'/g, "\\'").replace(/"/g, "&quot;"); }
function joinPath(base, name) { const sep = base.includes("\\") ? "\\" : "/"; return base.endsWith(sep) ? base + name : base + sep + name; }
let _filesPath = ".";
async function loadFiles() {
  const r = await apiJson("/api/files?path=" + encodeURIComponent(_filesPath));
  if (!r.ok) { $("files-view").innerHTML = `<div class="err">${escapeText(r.error || t("error"))}</div>`; return; }
  _filesPath = r.path;
  const items = (r.items || []).map(it => {
    const full = joinPath(r.path, it.name);
    const fn = it.dir ? `filesGo('${escapeAttr(full)}')` : `filesOpen('${escapeAttr(full)}')`;
    return `<div class="file-row" onclick="${fn}">${it.dir ? "📁" : "📄"} ${escapeText(it.name)}${it.dir ? "" : ` <span class="muted">${it.size}b</span>`}</div>`;
  }).join("") || `<div class="muted">${t("files_empty")}</div>`;
  $("files-view").innerHTML = `
    <div class="files-bar">
      <button class="btn-sm" onclick="filesUp()">${t("files_up")}</button>
      <input id="files-path" class="am-input" style="flex:1" value="${escapeText(r.path)}" onkeydown="if(event.key==='Enter')filesGo(this.value)"/>
      <button class="btn-sm" onclick="filesGo(document.getElementById('files-path').value)">${t("files_go")}</button>
    </div>
    <div class="files-bar">
      <input id="files-q" class="am-input" style="flex:1" placeholder="${t("files_search_ph")}"/>
      <label class="muted"><input type="checkbox" id="files-content"/> ${t("files_by_content")}</label>
      <button class="btn-sm" onclick="filesSearch()">${t("files_search_btn")}</button>
      <button class="btn-sm" onclick="filesMkdir()">${t("files_mkdir")}</button>
      <label class="muted"><input type="checkbox" id="files-wl" onchange="filesWhitelist(this.checked)"/> ${t("files_whitelist")}</label>
    </div>
    <div class="muted">${escapeText(r.path)} · ${r.writable ? t("files_writable") : t("files_readonly")}</div>
    <div class="files-list">${items}</div>
    <div id="files-results"></div>
    <div id="files-editor"></div>`;
}
function filesGo(p) { _filesPath = p; loadFiles(); }
function filesUp() { _filesPath = _filesPath.replace(/[\\/][^\\/]+[\\/]?$/, "") || _filesPath; loadFiles(); }
async function filesOpen(p) {
  const r = await apiJson("/api/files/read", { method: "POST", body: JSON.stringify({ path: p }) });
  const e = $("files-editor");
  if (!r.ok) { e.innerHTML = `<div class="err">${escapeText(r.error || "")}</div>`; return; }
  e.innerHTML = `<div class="files-editor-title">${escapeText(p)}
      <button class="btn-sm" onclick="filesDelete('${escapeAttr(p)}')">${t("files_delete")}</button></div>
    <textarea id="files-ta" class="training-textarea" style="min-height:320px;font-family:monospace">${escapeText(r.content)}</textarea>
    <button class="btn-sm" onclick="filesSave('${escapeAttr(p)}')">${t("files_save")}</button>`;
}
async function filesSave(p) { const r = await apiJson("/api/files/write", { method: "POST", body: JSON.stringify({ path: p, content: $("files-ta").value }) }); alert(r.ok ? "✓" : (r.error || t("error"))); }
async function filesDelete(p) { if (!confirm(t("delete") + "?")) return; await apiJson("/api/files/delete", { method: "POST", body: JSON.stringify({ path: p }) }); $("files-editor").innerHTML = ""; loadFiles(); }
async function filesMkdir() { const n = prompt(t("files_mkdir_ph")); if (!n) return; await apiJson("/api/files/mkdir", { method: "POST", body: JSON.stringify({ path: joinPath(_filesPath, n) }) }); loadFiles(); }
async function filesSearch() {
  const q = $("files-q").value.trim(); if (!q) return;
  const content = $("files-content").checked;
  const r = await apiJson(`/api/files/search?q=${encodeURIComponent(q)}&root=${encodeURIComponent(_filesPath)}&content=${content}`);
  $("files-results").innerHTML = `<div class="files-editor-title">${t("files_search_results")} (${(r.results || []).length})</div>` +
    ((r.results || []).map(x => `<div class="file-row" onclick="filesOpen('${escapeAttr(x.path)}')">${x.match === "content" ? "🔎" : "📄"} ${escapeText(x.path)}</div>`).join("") || `<div class="muted">${t("files_no_results")}</div>`);
}
async function filesWhitelist(en) { await apiJson("/api/safety/whitelist", { method: "POST", body: JSON.stringify({ enabled: en }) }); loadFiles(); }

// ===== ТЕРМИНАЛ =====
let _termTab = "shell";
function loadTerminal() {
  $("terminal-view").innerHTML = `
    <div class="logs-tab-btns">
      <button class="logs-tab-btn ${_termTab === "shell" ? "active" : ""}" onclick="termTab('shell')">${t("terminal_tab_shell")}</button>
      <button class="logs-tab-btn ${_termTab === "python" ? "active" : ""}" onclick="termTab('python')">${t("terminal_tab_python")}</button>
    </div>
    <div id="term-input"></div>
    <pre class="logs-console" id="term-out" style="min-height:300px;margin-top:10px"></pre>`;
  termRenderInput();
}
function termTab(x) { _termTab = x; loadTerminal(); }
function termRenderInput() {
  const c = $("term-input");
  if (_termTab === "shell")
    c.innerHTML = `<div class="files-bar"><input id="term-cmd" class="am-input" style="flex:1" placeholder="${t("terminal_cmd_ph")}" onkeydown="if(event.key==='Enter')termRun()"/><button class="btn-sm" onclick="termRun()">${t("terminal_run")}</button></div>`;
  else
    c.innerHTML = `<textarea id="term-code" class="training-textarea" style="font-family:monospace" placeholder="${t("terminal_code_ph")}"></textarea><button class="btn-sm" onclick="termRun()">${t("terminal_run")}</button>`;
}
async function termRun() {
  let r, head;
  if (_termTab === "shell") {
    const cmd = $("term-cmd").value.trim(); if (!cmd) return;
    head = "$ " + cmd; $("term-cmd").value = "";
    r = await apiJson("/api/shell", { method: "POST", body: JSON.stringify({ command: cmd }) });
  } else {
    const code = $("term-code").value; if (!code.trim()) return;
    head = ">>> [python]";
    r = await apiJson("/api/exec_python", { method: "POST", body: JSON.stringify({ code }) });
  }
  const out = `${head}\n[${t("terminal_exit")} ${r.code}]\n${r.stdout || ""}${r.stderr ? "\n" + r.stderr : ""}`;
  const o = $("term-out"); o.textContent = out + "\n\n" + o.textContent;
}

// ===== САМО-КОД =====
async function loadSelfmod() {
  const h = await apiJson("/api/selfmod/history").catch(() => ({ history: [] }));
  const rows = (h.history || []).map(x => `<tr>
      <td class="log-ts">${new Date(x.ts * 1000).toLocaleString()}</td>
      <td class="log-action">${escapeText(x.sha)}</td>
      <td>${escapeText(x.subject)}</td>
      <td><button class="btn-sm" onclick="smDiff('${escapeAttr(x.full_sha)}')">${t("selfmod_diff_btn")}</button>
          <button class="btn-sm" onclick="smRollback('${escapeAttr(x.full_sha)}')">${t("selfmod_rollback_btn")}</button></td></tr>`).join("");
  $("selfmod-view").innerHTML = `
    <input id="sm-path" class="am-input" placeholder="${t("selfmod_path_ph")}"/>
    <textarea id="sm-content" class="training-textarea" style="min-height:220px;font-family:monospace;margin-top:8px"></textarea>
    <button class="btn-sm" onclick="smApply()">${t("selfmod_apply")}</button>
    <div id="sm-result" style="margin:8px 0"></div>
    <div class="files-editor-title">${t("selfmod_history_title")}</div>
    <table class="log-table"><tbody>${rows}</tbody></table>
    <pre class="logs-console" id="sm-diff" style="margin-top:10px"></pre>`;
}
async function smApply() {
  const path = $("sm-path").value.trim(), content = $("sm-content").value;
  if (!path) return;
  const r = await apiJson("/api/selfmod/edit", { method: "POST", body: JSON.stringify({ path, content }) });
  $("sm-result").innerHTML = r.ok
    ? `<span style="color:#4ade80">${t("selfmod_ok")} · ${t("selfmod_smoke_ok")}</span>`
    : `<span class="err">${escapeText(r.reason || t("selfmod_err"))} · ${t("selfmod_smoke_err")}</span>`;
  if (r.diff) $("sm-diff").textContent = r.diff;
}
async function smDiff(sha) { const r = await apiJson("/api/selfmod/diff?sha=" + sha); $("sm-diff").textContent = r.diff || r.stat || ""; }
async function smRollback(sha) { if (!confirm(t("selfmod_rollback_confirm"))) return; await apiJson("/api/selfmod/rollback", { method: "POST", body: JSON.stringify({ path: sha }) }); loadSelfmod(); }

// ===== АВТО-АГЕНТ (ReAct) =====
async function runAgent(task) {
  renderMessage("user", task, false);
  const bubble = renderMessage("assistant", "", true);
  bubble.innerHTML = `<div class="agent-events"><em>${t("agent_running")}</em></div>`;
  setGenerating(true);
  await api("/api/safety/resume", { method: "POST" }).catch(() => {});
  abortCtrl = new AbortController();
  let html = "";
  try {
    const r = await fetch("/api/agent/run", {
      method: "POST", headers: { "Content-Type": "application/json", Authorization: "Bearer " + TOKEN },
      body: JSON.stringify({ task }), signal: abortCtrl.signal,
    });
    if (r.status === 409) { bubble.innerHTML = `<div class="agent-events">⚠️ ${t("agent_model_err")}</div>`; setGenerating(false); return; }
    const reader = r.body.getReader(); const dec = new TextDecoder(); let buf = "";
    while (true) {
      const { done, value } = await reader.read(); if (done) break;
      buf += dec.decode(value, { stream: true });
      let idx;
      while ((idx = buf.indexOf("\n")) >= 0) {
        const line = buf.slice(0, idx); buf = buf.slice(idx + 1);
        if (!line.trim()) continue;
        let ev; try { ev = JSON.parse(line); } catch (e) { continue; }
        html += renderAgentEvent(ev);
        bubble.innerHTML = `<div class="agent-events">${html}</div>`;
        scrollChat();
      }
    }
  } catch (e) { if (e.name !== "AbortError") html += `<div>⚠️ ${t("error")}</div>`; bubble.innerHTML = `<div class="agent-events">${html}</div>`; }
  finally { setGenerating(false); }
}
function renderAgentEvent(ev) {
  if (ev.type === "thought") return `<div class="ag-ev ag-thought">${t("agent_thought")}: ${escapeText(ev.text)}</div>`;
  if (ev.type === "tool") return `<div class="ag-ev ag-tool">${t("agent_tool")}: <b>${escapeText(ev.name)}</b> <code>${escapeText(JSON.stringify(ev.args))}</code></div>`;
  if (ev.type === "result") { const s = JSON.stringify(ev.result).slice(0, 1500); return `<div class="ag-ev ag-result">${t("agent_result")}: <code>${escapeText(s)}</code></div>`; }
  if (ev.type === "final") return `<div class="ag-ev ag-final">${t("agent_final")}: <div class="answer">${mdToHtml(ev.text || "")}</div></div>`;
  if (ev.type === "error") return `<div class="ag-ev ag-result" style="border-left-color:#f87171;color:#fca5a5">⚠️ ${escapeText(ev.error || t("error"))}</div>`;
  if (ev.type === "stopped") return `<div class="ag-ev ag-final">${t("agent_stopped")}</div>`;
  return "";
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
  const _mt = $("max-tokens"); if (_mt) _mt.addEventListener("change", saveSettings);
  const _nc = $("n-ctx"); if (_nc) _nc.addEventListener("change", saveSettings);

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
