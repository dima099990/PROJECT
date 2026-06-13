// Минимальный Markdown -> HTML (без внешних либ)
// Поддерживает: заголовки, **жирный**, *курсив*, `инлайн-код`, ```блоки кода```, списки, горизонталь

function escHtml(s) {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
          .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}

function mdToHtml(src) {
  // Сначала выделяем code-блоки (защита от обработки внутри)
  const codeBlocks = [];
  src = src.replace(/```(\w*)\n?([\s\S]*?)```/g, (_, lang, code) => {
    const idx = codeBlocks.length;
    codeBlocks.push({ lang: lang || "", code: code.replace(/\n$/, "") });
    return `\x00CODE${idx}\x00`;
  });

  // Инлайн-код (защита)
  const inlineCodes = [];
  src = src.replace(/`([^`\n]+)`/g, (_, code) => {
    const idx = inlineCodes.length;
    inlineCodes.push(escHtml(code));
    return `\x00IC${idx}\x00`;
  });

  // Построчная обработка
  const lines = src.split("\n");
  const out = [];
  let inList = false;
  let listTag = "";

  const flushList = () => {
    if (inList) { out.push(`</${listTag}>`); inList = false; listTag = ""; }
  };

  for (let i = 0; i < lines.length; i++) {
    let line = lines[i];

    // Code block placeholder
    if (/^\x00CODE\d+\x00$/.test(line.trim())) {
      flushList();
      const idx = parseInt(line.trim().replace(/\x00CODE(\d+)\x00/, "$1"));
      const { lang, code } = codeBlocks[idx];
      const escaped = escHtml(code);
      out.push(
        `<div class="code-block">` +
        (lang ? `<div class="code-lang">${escHtml(lang)}</div>` : "") +
        `<button class="copy-btn" onclick="copyCode(this)" data-i18n="copy">${t("copy")}</button>` +
        `<pre><code>${escaped}</code></pre></div>`
      );
      continue;
    }

    // Заголовки
    const hm = line.match(/^(#{1,6})\s+(.+)/);
    if (hm) {
      flushList();
      const lvl = hm[1].length;
      out.push(`<h${lvl}>${inlineFormat(hm[2], inlineCodes)}</h${lvl}>`);
      continue;
    }

    // Горизонталь
    if (/^[-*_]{3,}$/.test(line.trim())) {
      flushList();
      out.push("<hr>");
      continue;
    }

    // Маркированный список
    const ulm = line.match(/^[\s]*[-*+]\s+(.+)/);
    if (ulm) {
      if (!inList || listTag !== "ul") { flushList(); out.push("<ul>"); inList = true; listTag = "ul"; }
      out.push(`<li>${inlineFormat(ulm[1], inlineCodes)}</li>`);
      continue;
    }

    // Нумерованный список
    const olm = line.match(/^[\s]*\d+\.\s+(.+)/);
    if (olm) {
      if (!inList || listTag !== "ol") { flushList(); out.push("<ol>"); inList = true; listTag = "ol"; }
      out.push(`<li>${inlineFormat(olm[1], inlineCodes)}</li>`);
      continue;
    }

    flushList();

    // Пустая строка
    if (line.trim() === "") {
      out.push("<br>");
      continue;
    }

    // Обычный абзац
    out.push(`<p>${inlineFormat(line, inlineCodes)}</p>`);
  }

  flushList();
  return out.join("\n");
}

function inlineFormat(s, inlineCodes) {
  // Сначала escapeHTML кроме плейсхолдеров IC
  // Разбиваем по плейсхолдерам IC, экранируем части между ними
  const parts = s.split(/(\x00IC\d+\x00)/);
  s = parts.map((p, i) => {
    if (i % 2 === 1) {
      const idx = parseInt(p.replace(/\x00IC(\d+)\x00/, "$1"));
      return `<code class="inline-code">${inlineCodes[idx]}</code>`;
    }
    return escHtml(p);
  }).join("");

  // Жирный + курсив
  s = s.replace(/\*\*\*(.+?)\*\*\*/g, "<strong><em>$1</em></strong>");
  s = s.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
  s = s.replace(/\*(.+?)\*/g, "<em>$1</em>");
  s = s.replace(/__(.+?)__/g, "<strong>$1</strong>");
  s = s.replace(/_(.+?)_/g, "<em>$1</em>");

  return s;
}

function copyCode(btn) {
  const code = btn.parentElement.querySelector("pre code").textContent;
  navigator.clipboard.writeText(code).then(() => {
    const orig = btn.textContent;
    btn.textContent = t("copied");
    setTimeout(() => { btn.textContent = t("copy"); }, 1500);
  });
}
