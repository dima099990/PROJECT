// Двуязычный словарь (ru/en). Переключение кнопкой в шапке.
const I18N = {
  ru: {
    login_title: "Вход", login_btn: "Войти", password: "Пароль", logout: "Выход",
    stop: "СТОП", send: "Отпр.", chat_ph: "Сообщение…",
    tab_chat: "Чат", tab_files: "Файлы", tab_agents: "Агенты", tab_models: "Модели",
    tab_training: "Обучение", tab_logs: "Логи", tab_status: "Статус",
    load: "Загрузить", active: "активна", download: "скачать", train: "Обучить",
    bad_pass: "Неверный пароль",
  },
  en: {
    login_title: "Sign in", login_btn: "Enter", password: "Password", logout: "Logout",
    stop: "STOP", send: "Send", chat_ph: "Message…",
    tab_chat: "Chat", tab_files: "Files", tab_agents: "Agents", tab_models: "Models",
    tab_training: "Training", tab_logs: "Logs", tab_status: "Status",
    load: "Load", active: "active", download: "download", train: "Train",
    bad_pass: "Wrong password",
  },
};
let LANG = localStorage.getItem("lang") || "ru";

function t(key) { return (I18N[LANG] && I18N[LANG][key]) || key; }

function applyI18n() {
  document.documentElement.lang = LANG;
  document.querySelectorAll("[data-i18n]").forEach(el => { el.textContent = t(el.dataset.i18n); });
  document.querySelectorAll("[data-i18n-ph]").forEach(el => { el.placeholder = t(el.dataset.i18nPh); });
  const lb = document.getElementById("lang-btn");
  if (lb) lb.textContent = LANG === "ru" ? "EN" : "RU";
}
function toggleLang() { LANG = LANG === "ru" ? "en" : "ru"; localStorage.setItem("lang", LANG); applyI18n(); }
