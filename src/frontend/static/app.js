// Pooh Code frontend — vanilla JS, no build step.

const $ = (sel) => document.querySelector(sel);

const els = {
  app: $("#app"),
  leftPane: $("#left-pane"),
  middlePane: $("#middle-pane"),
  rightPane: $("#right-pane"),
  messages: $("#messages"),
  chatInner: $("#chat-inner"),
  emptyHint: $("#empty-hint"),
  input: $("#input"),
  composer: $("#composer"),
  btnSend: $("#btn-send"),
  btnStop: $("#btn-stop"),
  btnCompact: $("#btn-compact"),
  btnNew: $("#btn-new"),
  btnRefresh: $("#btn-refresh"),
  btnAttach: $("#btn-attach"),
  fileInput: $("#file-input"),
  filePreviewBar: $("#file-preview-bar"),
  sessionList: $("#session-list"),
  sessionSearch: $("#session-search"),
  sessionId: $("#session-id"),
  userEmail: $("#user-email"),
  userAvatar: $("#user-avatar"),
  btnLogout: $("#btn-logout"),
  usageLabel: $("#usage-label"),
  modelLabel: $("#model-label"),
  modelBadge: $("#model-badge"),
  statusPulse: $("#status-pulse"),
  chatTitle: $("#chat-title"),
  agentStatus: $("#agent-status"),
  agentStatusTitle: $("#agent-status-title"),
  agentStatusDetail: $("#agent-status-detail"),
  agentStatusTimer: $("#agent-status-timer"),
  agentStatusClose: $("#agent-status-close"),
  replyCtx: $("#reply-ctx"),
  replyCtxText: $("#reply-ctx-text"),
  replyCtxClear: $("#reply-ctx-clear"),
  scrollBtn: $("#scroll-btn"),
  colDividerLeft: $("#col-divider-left"),
  colDividerRight: $("#col-divider-right"),
  minimap: $("#minimap"),
  mmInner: $("#minimap-inner"),
  mmCanvas: $("#mm-canvas"),
  mmViewport: $("#mm-viewport"),
  btnMinimapJump: $("#btn-minimap-jump"),
};

// ─── Agent status banner ───
const agentStatus = (() => {
  let level = "idle";
  let startTs = 0;
  let timerHandle = null;
  let hidden = false;
  let lastActivity = 0;
  let baseDetail = "";

  function render() {
    if (!els.agentStatus) return;
    els.agentStatus.dataset.level = level;
    els.agentStatus.classList.toggle("hidden", hidden && level === "idle");
  }

  function fmtElapsed(ms) {
    const s = Math.floor(ms / 1000);
    if (s < 60) return `${s}s`;
    return `${Math.floor(s / 60)}m${String(s % 60).padStart(2, "0")}s`;
  }

  function tick() {
    if (!els.agentStatusTimer) return;
    if (level === "idle" || !startTs) {
      els.agentStatusTimer.textContent = "";
      return;
    }
    els.agentStatusTimer.textContent = fmtElapsed(Date.now() - startTs);
    if (els.agentStatusDetail && lastActivity) {
      const idleMs = Date.now() - lastActivity;
      if (idleMs > 8000) {
        els.agentStatusDetail.textContent =
          (baseDetail ? baseDetail + " · " : "") + `${fmtElapsed(idleMs)} 内容参数构造中，时间较长，请耐心等待`;
      } else if (baseDetail) {
        els.agentStatusDetail.textContent = baseDetail;
      }
    }
  }

  function startTimer() {
    stopTimer();
    startTs = Date.now();
    tick();
    timerHandle = window.setInterval(tick, 1000);
  }

  function stopTimer() {
    if (timerHandle) window.clearInterval(timerHandle);
    timerHandle = null;
  }

  function markActivity() {
    lastActivity = Date.now();
  }

  function set(newLevel, title, detail) {
    level = newLevel || "idle";
    if (title != null && els.agentStatusTitle) els.agentStatusTitle.textContent = title;
    if (detail != null) {
      baseDetail = detail;
      if (els.agentStatusDetail) els.agentStatusDetail.textContent = detail;
    }
    if (level === "idle") {
      stopTimer();
      if (els.agentStatusTimer) els.agentStatusTimer.textContent = "";
    } else if (!timerHandle) {
      startTimer();
    }
    markActivity();
    render();
  }

  function reset() {
    hidden = false;
    set("idle", "就绪", "等待你的指令");
  }

  els.agentStatusClose?.addEventListener("click", () => {
    hidden = true;
    render();
  });

  render();
  return { set, reset, markActivity };
})();

let state = {
  sessionId: null,
  sessionKey: null,
  runningSessions: new Set(),
  pendingFiles: [],
  capabilities: null,
  liveBubbles: new Map(),
  messageRenderSeq: 0,
  sessions: [],
  fileGroups: [],
  openConvos: new Set(),
  sessionFilter: "",
  replyCtx: null, // { who, text }
};

const COLS_KEY = "pooh.cols.v1";

// ─── Column dividers ───
function applyCols(ratios) {
  const [a, b, c] = ratios;
  document.documentElement.style.setProperty("--col-left", `${a}fr`);
  document.documentElement.style.setProperty("--col-mid", `${b}fr`);
  document.documentElement.style.setProperty("--col-right", `${c}fr`);
  positionDividers();
  try {
    localStorage.setItem(COLS_KEY, JSON.stringify(ratios));
  } catch (_) {}
}

function loadCols() {
  try {
    const raw = localStorage.getItem(COLS_KEY);
    if (raw) {
      const parsed = JSON.parse(raw);
      if (Array.isArray(parsed) && parsed.length === 3) {
        applyCols(parsed);
        return;
      }
    }
  } catch (_) {}
  applyCols([2, 7, 1]);
}

function positionDividers() {
  if (!els.leftPane || !els.middlePane || !els.colDividerLeft || !els.colDividerRight) return;
  const leftW = els.leftPane.getBoundingClientRect().width;
  const midW = els.middlePane.getBoundingClientRect().width;
  els.colDividerLeft.style.left = `${leftW}px`;
  els.colDividerRight.style.left = `${leftW + midW}px`;
}

function bindDividerDrag(divider, isLeft) {
  if (!divider) return;
  divider.addEventListener("pointerdown", (e) => {
    e.preventDefault();
    const startX = e.clientX;
    const totalW = els.app.getBoundingClientRect().width;
    const leftW = els.leftPane.getBoundingClientRect().width;
    const midW = els.middlePane.getBoundingClientRect().width;
    const rightW = els.rightPane.getBoundingClientRect().width;
    divider.setPointerCapture(e.pointerId);

    const onMove = (evt) => {
      const dx = evt.clientX - startX;
      let nl = leftW, nm = midW, nr = rightW;
      if (isLeft) {
        nl = Math.max(220, Math.min(totalW - 400, leftW + dx));
        nm = Math.max(360, midW - dx);
      } else {
        nr = Math.max(180, Math.min(totalW - 400, rightW - dx));
        nm = Math.max(360, midW + dx);
      }
      const sum = nl + nm + nr;
      applyCols([
        +(nl / sum * 10).toFixed(3),
        +(nm / sum * 10).toFixed(3),
        +(nr / sum * 10).toFixed(3),
      ]);
    };
    const onUp = () => {
      divider.releasePointerCapture?.(e.pointerId);
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
      scheduleMinimapRebuild();
    };
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
  });
}

// ─── Helpers ───
function syncIntroMode(hasMessages) {
  if (!els.chatInner) return;
  els.chatInner.classList.toggle("intro-mode", !hasMessages);
  if (els.emptyHint) els.emptyHint.classList.toggle("hidden", hasMessages);
  if (!hasMessages) els.scrollBtn?.classList.add("hidden");
}

function setStatusPulse(kind) {
  if (!els.modelBadge) return;
  els.modelBadge.classList.remove("busy", "err");
  if (kind === "busy") els.modelBadge.classList.add("busy");
  else if (kind === "err") els.modelBadge.classList.add("err");
}

function setBusy(busy, sessionId = state.sessionId) {
  if (!sessionId) {
    els.btnSend.disabled = false;
    els.btnStop.disabled = true;
    els.input.disabled = false;
    setStatusPulse("idle");
    return;
  }
  if (busy) state.runningSessions.add(sessionId);
  else state.runningSessions.delete(sessionId);
  updateRunningUI();
}

function setSessionRunning(sessionId, running) {
  if (!sessionId) return;
  if (running) state.runningSessions.add(sessionId);
  else state.runningSessions.delete(sessionId);
  updateRunningUI();
}

function updateRunningUI() {
  const currentBusy = !!(state.sessionId && state.runningSessions.has(state.sessionId));
  els.btnSend.disabled = false;
  els.btnStop.disabled = !currentBusy;
  els.input.disabled = false;
  els.input.placeholder = currentBusy
    ? "继续发送消息，Agent 将在下一轮看到…"
    : "继续这段对话，或者拖拽文件到这里…";
  if (currentBusy) {
    setStatusPulse("busy");
  } else if (state.runningSessions.size > 0) {
    setStatusPulse("busy");
  } else {
    setStatusPulse("idle");
    if (agentStatus) agentStatus.set("idle", "就绪", "等待你的指令");
  }
}

function refreshChatTitle() {
  if (!els.chatTitle) return;
  if (els.chatTitle.querySelector(".chat-title-input")) return;
  if (!state.sessionId) {
    els.chatTitle.textContent = "开始一段新对话";
    return;
  }
  const sess = (state.sessions || []).find((s) => s.session_id === state.sessionId);
  const label = (sess && sess.label) || state.currentLabel || state.sessionId.slice(0, 8);
  els.chatTitle.textContent = label;
  els.chatTitle.title = "双击重命名会话";
}

function applyState(payload) {
  if (!payload) return;
  if (payload.session_id) {
    state.sessionId = payload.session_id;
    if (els.sessionId) els.sessionId.textContent = payload.session_id.slice(0, 8);
  }
  if (typeof payload.running === "boolean" && payload.session_id) {
    setSessionRunning(payload.session_id, payload.running);
  }
  if (payload.session_key) state.sessionKey = payload.session_key;
  if (payload.model) {
    if (els.modelLabel) els.modelLabel.textContent = payload.model;
  }
  if (payload.usage) {
    if (els.usageLabel) els.usageLabel.textContent = payload.usage.display || "—";
  }
  if (payload.capabilities) {
    state.capabilities = payload.capabilities;
  }
  if (typeof payload.label === "string") {
    state.currentLabel = payload.label;
  }
  refreshChatTitle();
  updateRunningUI();
}

function escapeHtml(s) {
  return (s ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  }[c]));
}

function renderInline(text) {
  return escapeHtml(text).replace(/`([^`]+)`/g, "<code>$1</code>");
}

function guessCodeLanguage(text) {
  const sample = (text || "").trim();
  if (!sample) return "";
  if (/<!doctype html>|<html[\s>]|<head[\s>]|<body[\s>]/i.test(sample)) return "html";
  if (/^\s*[\[{]/.test(sample) && /[:",\]}]/.test(sample)) return "json";
  if (/\b(def|import|from|class|print)\b/.test(sample) && /:\s*(#.*)?$/m.test(sample)) return "python";
  if (/\b(function|const|let|var|return|=>)\b/.test(sample)) return "javascript";
  if (/\bSELECT\b|\bFROM\b|\bWHERE\b|\bORDER BY\b/i.test(sample)) return "sql";
  if (/<[a-z][\w-]*[^>]*>/.test(sample)) return "html";
  return "";
}

function looksLikeCodeBlock(text) {
  const sample = (text || "").trim();
  if (!sample) return false;
  if (sample.includes("```")) return false;
  const lines = sample.split("\n").map((line) => line.trim()).filter(Boolean);
  if (lines.length < 2) return false;
  const strongPatterns = [
    /<!doctype html>/i,
    /<\/?[a-z][\w-]*[^>]*>/i,
    /^\s*[{\[]/,
    /^\s*[A-Za-z_$][\w$]*\s*=\s*.+;?$/,
    /^\s*(const|let|var|function|class|if|for|while|return|import|export)\b/,
    /^\s*(def|class|from|import|print)\b/,
  ];
  const codeLikeLines = lines.filter((line) => {
    return strongPatterns.some((pattern) => pattern.test(line))
      || /[{}();<>]/.test(line)
      || /^\s*[.#][\w-]+\s*\{/.test(line);
  }).length;
  if (codeLikeLines >= Math.max(2, Math.ceil(lines.length * 0.45))) return true;
  if (lines.length >= 4 && lines.some((line) => /^[<][^>]+>/.test(line))) return true;
  return false;
}

function normalizeUserMarkdown(text) {
  const raw = typeof text === "string" ? text : "";
  if (!looksLikeCodeBlock(raw)) return raw;
  const lang = guessCodeLanguage(raw);
  const fence = `\`\`\`${lang}`;
  return `${fence}\n${raw.trim()}\n\`\`\``;
}

function normalizeCodeText(text) {
  let value = String(text || "").replace(/\r\n?/g, "\n");
  value = value.replace(/^\n+|\n+$/g, "");
  const lines = value.split("\n");
  const indents = lines
    .filter((line) => line.trim())
    .map((line) => {
      const match = line.match(/^[ \t]+/);
      return match ? match[0].replace(/\t/g, "    ").length : 0;
    });
  const minIndent = indents.length ? Math.min(...indents) : 0;
  if (minIndent > 0) {
    value = lines
      .map((line) => {
        if (!line.trim()) return "";
        let count = 0;
        let idx = 0;
        while (idx < line.length && count < minIndent) {
          count += line[idx] === "\t" ? 4 : 1;
          idx += 1;
        }
        return line.slice(idx);
      })
      .join("\n");
  }
  return value;
}

function resolveCodeLanguage(codeEl, text) {
  const cls = codeEl.className || "";
  const langMatch = cls.match(/language-([\w-]+)/i) || cls.match(/lang(?:uage)?-([\w-]+)/i);
  const raw = (langMatch && langMatch[1] ? langMatch[1] : "").toLowerCase();
  if (raw) {
    if (raw === "py") return "python";
    if (raw === "js") return "javascript";
    if (raw === "ts") return "typescript";
    if (raw === "htm" || raw === "xml") return "html";
    return raw;
  }
  return guessCodeLanguage(text) || "plaintext";
}

function formatCodeForDisplay(text, language) {
  const normalized = normalizeCodeText(text);
  const lang = (language || "").toLowerCase();
  try {
    if (lang === "json") {
      return JSON.stringify(JSON.parse(normalized), null, 2);
    }
    if (["javascript", "js", "typescript", "ts"].includes(lang) && typeof js_beautify === "function") {
      return js_beautify(normalized, {
        indent_size: 2,
        space_in_empty_paren: false,
        preserve_newlines: true,
        max_preserve_newlines: 2,
      });
    }
    if (["html", "xml"].includes(lang) && typeof html_beautify === "function") {
      return html_beautify(normalized, {
        indent_size: 2,
        wrap_line_length: 0,
        preserve_newlines: true,
        max_preserve_newlines: 2,
      });
    }
    if (lang === "python") {
      return normalized
        .split("\n")
        .map((line) => line.replace(/[ \t]+$/g, "").replace(/\t/g, "    "))
        .join("\n");
    }
  } catch (_) {}
  return normalized;
}

if (typeof marked !== "undefined" && marked.setOptions) {
  marked.setOptions({ gfm: true, breaks: true });
}

function renderMarkdown(text) {
  if (typeof marked !== "undefined" && marked.parse) {
    try {
      return marked.parse(text);
    } catch (_) {}
  }
  return renderInline(text);
}

function shouldStreamRenderMarkdown(text) {
  const value = typeof text === "string" ? text : "";
  if (!value) return false;
  return /[`*_#>\-\[\]\(\)\n|]/.test(value);
}

function streamRenderDelay(raw) {
  const size = (raw || "").length;
  if (size > 32000) return 220;
  if (size > 16000) return 180;
  if (size > 8000) return 140;
  return 90;
}

function renderStreamingTextPart(part) {
  if (!part || !part.el) return;
  const raw = part.raw || "";
  part.renderedRaw = raw;
  part.renderHandle = null;
  if (!raw) {
    part.el.textContent = "";
    return;
  }
  if (!shouldStreamRenderMarkdown(raw)) {
    part.el.textContent = raw;
    part.el.classList.remove("rendered");
    autoScrollIfNear();
    return;
  }
  part.el.classList.add("rendered");
  part.el.innerHTML = renderMarkdown(raw);
  autoScrollIfNear();
}

function scheduleStreamingTextRender(part, { force = false } = {}) {
  if (!part || !part.el) return;
  if (force) {
    if (part.renderHandle) {
      window.clearTimeout(part.renderHandle);
      part.renderHandle = null;
    }
    renderStreamingTextPart(part);
    return;
  }
  if (part.renderHandle) return;
  part.renderHandle = window.setTimeout(() => {
    renderStreamingTextPart(part);
  }, streamRenderDelay(part.raw));
}

function finalizeStreamingTextPart(part) {
  if (!part || !part.el) return;
  if (part.renderHandle) {
    window.clearTimeout(part.renderHandle);
    part.renderHandle = null;
  }
  const trimmed = (part.raw || "").trim();
  if (!trimmed) {
    part.el.textContent = "";
    return;
  }
  part.el.classList.add("rendered");
  part.el.innerHTML = renderMarkdown(trimmed);
  enhanceRenderedContent(part.el);
}

let _msgIndex = 0;

function setCopyButtonState(button, text) {
  if (!button) return;
  const value = typeof text === "string" ? text : "";
  button.dataset.copyText = value;
  button.disabled = !value.trim();
}

async function copyToClipboard(text) {
  if (!text) return false;
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(text);
    return true;
  }
  const ghost = document.createElement("textarea");
  ghost.value = text;
  ghost.setAttribute("readonly", "readonly");
  ghost.style.position = "fixed";
  ghost.style.opacity = "0";
  ghost.style.pointerEvents = "none";
  document.body.appendChild(ghost);
  ghost.select();
  let ok = false;
  try {
    ok = document.execCommand("copy");
  } finally {
    ghost.remove();
  }
  return ok;
}

function attachCopyHandler(button) {
  if (!button || button.dataset.boundCopy === "1") return;
  button.dataset.boundCopy = "1";
  button.addEventListener("click", async () => {
    const text = button.dataset.copyText || "";
    if (!text.trim()) return;
    try {
      await copyToClipboard(text);
      const orig = button.innerHTML;
      button.innerHTML = "已复制";
      button.classList.add("copied");
      window.setTimeout(() => {
        button.innerHTML = orig;
        button.classList.remove("copied");
      }, 1200);
    } catch (_) {}
  });
}

function enhanceRenderedContent(container) {
  if (!container) return;
  container.querySelectorAll("pre").forEach((pre) => {
    if (pre.parentElement?.classList.contains("code-block")) return;
    const codeEl = pre.querySelector("code") || pre;
    const originalText = codeEl.textContent || "";
    const language = resolveCodeLanguage(codeEl, originalText);
    const formatted = formatCodeForDisplay(originalText, language);
    codeEl.textContent = formatted;
    pre.dataset.language = language;
    if (codeEl !== pre) {
      codeEl.className = `language-${language}`;
    }
    const wrapper = document.createElement("div");
    wrapper.className = "code-block";
    const toolbar = document.createElement("div");
    toolbar.className = "code-block-toolbar";
    const langLabel = document.createElement("span");
    langLabel.className = "code-lang";
    langLabel.textContent = language === "plaintext" ? "CODE" : language.toUpperCase();
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "code-copy";
    btn.textContent = "复制代码";
    setCopyButtonState(btn, formatted);
    attachCopyHandler(btn);
    toolbar.appendChild(langLabel);
    toolbar.appendChild(btn);
    pre.parentNode.insertBefore(wrapper, pre);
    wrapper.appendChild(toolbar);
    wrapper.appendChild(pre);
    if (typeof hljs !== "undefined" && typeof hljs.highlightElement === "function") {
      try {
        hljs.highlightElement(codeEl);
      } catch (_) {}
    }
  });
}

function _fmtClockTime(d) {
  if (!d) return "";
  const dt = d instanceof Date ? d : new Date(d);
  if (isNaN(dt)) return "";
  const today = new Date();
  const sameDay = dt.getFullYear() === today.getFullYear()
    && dt.getMonth() === today.getMonth()
    && dt.getDate() === today.getDate();
  const hh = String(dt.getHours()).padStart(2, "0");
  const mm = String(dt.getMinutes()).padStart(2, "0");
  if (sameDay) return `${hh}:${mm}`;
  const mo = String(dt.getMonth() + 1).padStart(2, "0");
  const dd = String(dt.getDate()).padStart(2, "0");
  return `${mo}-${dd} ${hh}:${mm}`;
}

function _extractQuote(text) {
  const m = /^\[引用:\s*"((?:[^"\\]|\\.)*)"\]\r?\n\r?\n([\s\S]*)$/.exec(text || "");
  if (!m) return null;
  const quote = m[1].replace(/\\"/g, '"').replace(/\\\\/g, "\\");
  return { quote, body: m[2] };
}

// ─── Message rendering (avatar + bubble-head + body + msg-tools) ───
function createMessageShell(role, { msgId = null, who = null, time = null } = {}) {
  const cls = role === "user" ? "u" : role === "assistant" ? "a" : "s";
  const root = document.createElement("div");
  root.className = `msg ${cls}`;
  if (msgId) root.setAttribute("data-msg-id", msgId);
  root.setAttribute("data-role", role);

  const whoLabel = who || (role === "user" ? "你" : role === "assistant" ? "Pooh Code" : "系统");
  const avatarLetter = role === "user" ? (whoLabel[0] || "Y") : (role === "assistant" ? "P" : "S");
  const canAct = role === "user" || role === "assistant";
  const showHeader = role === "user";
  const timeText = _fmtClockTime(time);

  root.innerHTML = `
    ${showHeader ? `<div class="avatar-sm">${escapeHtml(avatarLetter)}</div>` : ""}
    <div class="bubble">
      ${showHeader ? `
      <div class="bubble-head">
        <span class="who">${escapeHtml(whoLabel)}</span>
      </div>` : ""}
      <div class="body"></div>
      <div class="msg-downloads"></div>
      ${canAct ? `
      <div class="msg-tools">
        <button class="msg-quote" type="button" title="引用此消息">引用</button>
        <button class="msg-copy" type="button" title="复制消息">复制</button>
        <span class="msg-time">${escapeHtml(timeText)}</span>
      </div>` : ""}
    </div>
  `;
  const body = root.querySelector(".body");
  const copyBtn = root.querySelector(".msg-copy");
  const quoteBtn = root.querySelector(".msg-quote");
  const downloads = root.querySelector(".msg-downloads");
  if (copyBtn) {
    setCopyButtonState(copyBtn, "");
    attachCopyHandler(copyBtn);
  }
  if (quoteBtn) {
    quoteBtn.addEventListener("click", () => {
      const text = copyBtn?.dataset.copyText || body.textContent || "";
      setReplyCtx({ who: whoLabel, text });
    });
  }
  return { root, body, copyBtn, quoteBtn, downloads };
}

function _renderUserBodyWithQuote(shell, text) {
  const parsed = _extractQuote(text);
  const bubble = shell.root.querySelector(".bubble");
  if (parsed) {
    const q = document.createElement("div");
    q.className = "quote";
    q.textContent = parsed.quote;
    bubble.insertBefore(q, shell.body);
    shell.body.textContent = parsed.body;
    shell.body.classList.remove("rendered");
  } else {
    const renderedText = normalizeUserMarkdown(text);
    shell.body.classList.add("rendered");
    shell.body.innerHTML = renderMarkdown(renderedText);
    enhanceRenderedContent(shell.body);
  }
  setCopyButtonState(shell.copyBtn, text);
}

function appendMessage(role, text, { scroll = true } = {}) {
  syncIntroMode(true);
  const shell = createMessageShell(role, { msgId: `m-${_msgIndex++}`, time: new Date() });
  if (role === "user") {
    _renderUserBodyWithQuote(shell, text);
  } else if (role === "assistant") {
    shell.body.classList.add("rendered");
    shell.body.innerHTML = renderMarkdown(text);
    enhanceRenderedContent(shell.body);
    setCopyButtonState(shell.copyBtn, text);
  } else {
    shell.body.innerHTML = renderInline(text);
  }
  els.chatInner.appendChild(shell.root);
  if (scroll) els.messages.scrollTop = els.messages.scrollHeight;
  scheduleMinimapRebuild();
}

function buildHistoryMessageNode(message) {
  if (!message) return null;
  if (message.role === "assistant") {
    const shell = createMessageShell("assistant", { msgId: `m-${_msgIndex++}` });
    let bodyHTML = "";
    if (message.tools && message.tools.length) {
      bodyHTML += buildToolGroupHTML(message.tools);
    }
    if (message.text && message.text.trim()) {
      bodyHTML += `<div class="stream-part">${renderMarkdown(message.text)}</div>`;
    }
    shell.body.classList.add("rendered");
    shell.body.innerHTML = bodyHTML || renderMarkdown("(empty response)");
    enhanceRenderedContent(shell.body);

    // Move download buttons from inside body to msg-downloads at the end
    const bodyDownloads = shell.body.querySelectorAll(".file-download");
    bodyDownloads.forEach((a) => shell.downloads.appendChild(a));
    // Remove the now-empty inline download container (stream-part wrapping the anchors)
    shell.body.querySelectorAll(".stream-part").forEach((sp) => {
      if (!sp.children.length && !sp.textContent.trim()) sp.remove();
    });

    setCopyButtonState(shell.copyBtn, message.text || shell.body.textContent || "");
    return shell.root;
  }
  if (message.text && message.text.trim()) {
    const shell = createMessageShell(message.role, { msgId: `m-${_msgIndex++}` });
    if (message.role === "user") {
      _renderUserBodyWithQuote(shell, message.text);
    } else {
      shell.body.innerHTML = renderInline(message.text);
    }
    return shell.root;
  }
  return null;
}

function nextPaint() {
  return new Promise((resolve) => window.requestAnimationFrame(() => resolve()));
}

function clearMessages() {
  els.chatInner.innerHTML = "";
  els.chatInner.appendChild(els.emptyHint);
}

async function api(path, opts = {}) {
  const resp = await fetch(path, {
    method: opts.method || "GET",
    headers: opts.body ? { "Content-Type": "application/json" } : undefined,
    body: opts.body ? JSON.stringify(opts.body) : undefined,
    credentials: "same-origin",
  });
  if (resp.status === 401) {
    window.location.href = "/login";
    throw new Error("未登录");
  }
  const data = await resp.json().catch(() => ({ ok: false, error: "invalid json" }));
  if (!resp.ok || !data.ok) {
    throw new Error(data.error || `HTTP ${resp.status}`);
  }
  return data;
}

async function logout() {
  try {
    await fetch("/api/auth/logout", { method: "POST", credentials: "same-origin" });
  } catch (_) {}
  window.location.href = "/login";
}

function buildToolGroupHTML(tools) {
  if (!tools || !tools.length) return "";
  const downloadPaths = [];
  const items = tools.map((t) => {
    const inputJson = escapeHtml(JSON.stringify(t.input || {}, null, 2));
    const resultText = escapeHtml(t.result || "");
    const errClass = t.is_error ? " error" : "";
    const statusLabel = t.is_error ? "失败" : "完成";
    const resultLabel = t.is_error ? "ERROR" : "OUTPUT";
    if (!t.is_error && t.result) {
      for (const outputPath of _extractOutputPaths(t.name, t.result)) {
        downloadPaths.push(outputPath);
      }
    }
    return `<div class="tool-block${errClass}">
      <div class="tool-head">
        <span class="badge">TOOL</span>
        <span class="tool-name">${escapeHtml(t.name)}</span>
        <span class="tool-status">${statusLabel}</span>
      </div>
      <div class="tool-body">
        <div class="tool-label">INPUT</div>
        <pre class="tool-input">${inputJson}</pre>
        ${resultText ? `<div class="tool-label">${resultLabel}</div><pre>${resultText}</pre>` : ""}
      </div>
    </div>`;
  }).join("");
  let downloadHTML = "";
  if (downloadPaths.length) {
    const btns = downloadPaths.map((p) => {
      const name = p.split("/").pop();
      const icon = _fileIcon(name);
      return `<a class="file-download" href="/api/download?path=${encodeURIComponent(p)}" target="_blank">` +
        `<span class="file-icon">${icon}</span>` +
        `<span class="file-info"><span class="file-name">${escapeHtml(name)}</span>` +
        `<span class="file-meta">点击下载</span></span></a>`;
    }).join("");
    downloadHTML = `<div class="stream-part" style="display:flex;flex-wrap:wrap;gap:8px">${btns}</div>`;
  }
  return `<div class="thinking-group stream-part collapsed">
    <div class="thinking-head" onclick="this.parentElement.classList.toggle('collapsed')">
      <span class="thinking-icon">⊙</span>
      <span class="thinking-label">已思考</span>
      <span class="thinking-count"> · ${tools.length} 个工具调用</span>
      <span class="caret">▾</span>
    </div>
    <div class="thinking-body">${items}</div>
  </div>${downloadHTML}`;
}

async function refreshMessages() {
  try {
    const query = state.sessionId ? `?session_id=${encodeURIComponent(state.sessionId)}` : "";
    const data = await api(`/api/messages${query}`);
    const renderSeq = ++state.messageRenderSeq;
    const sessionAtStart = state.sessionId;
    applyState(data);
    clearMessages();
    const messages = data.messages || [];
    syncIntroMode(messages.length > 0);
    const chunkSize = 6;
    for (let i = 0; i < messages.length; i += chunkSize) {
      if (renderSeq !== state.messageRenderSeq || sessionAtStart !== state.sessionId) return;
      const frag = document.createDocumentFragment();
      for (const message of messages.slice(i, i + chunkSize)) {
        const node = buildHistoryMessageNode(message);
        if (node) frag.appendChild(node);
      }
      els.chatInner.appendChild(frag);
      await nextPaint();
    }
    const liveBubble = state.liveBubbles.get(state.sessionId);
    if (liveBubble) {
      if (!liveBubble.root.isConnected) {
        els.chatInner.appendChild(liveBubble.root);
      }
      for (const part of liveBubble.textParts || []) {
        if ((part.raw || "") !== (part.renderedRaw || "")) {
          renderStreamingTextPart(part);
        }
      }
    }
    if ((data.messages || []).length > 0) {
      els.messages.scrollTop = els.messages.scrollHeight;
    }
    scheduleMinimapRebuild();
  } catch (err) {
    agentStatus.set("error", "加载消息失败", err.message || "");
  }
}

function _sessionDateLabel(isoStr) {
  if (!isoStr) return "未知";
  const d = new Date(isoStr);
  if (isNaN(d)) return "未知";
  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const target = new Date(d.getFullYear(), d.getMonth(), d.getDate());
  const diff = Math.round((today - target) / 86400000);
  if (diff === 0) return "今天";
  if (diff === 1) return "昨天";
  if (diff <= 6) return `${diff} 天前`;
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}

function _relTime(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  if (isNaN(d)) return "";
  const now = Date.now();
  const diff = (now - d.getTime()) / 1000;
  if (diff < 60) return "刚刚";
  if (diff < 3600) return `${Math.floor(diff / 60)} 分钟前`;
  if (diff < 86400) return `${Math.floor(diff / 3600)} 小时前`;
  const days = Math.floor(diff / 86400);
  if (days < 7) return `${days} 天前`;
  return `${d.getMonth() + 1}-${String(d.getDate()).padStart(2, "0")}`;
}

function _fmtTokens(n) {
  if (n >= 1000) return (n / 1000).toFixed(n >= 100000 ? 0 : 1) + "k";
  return String(n);
}

function _artifactType(name) {
  const ext = (name.match(/\.[^.]+$/) || [""])[0].toLowerCase();
  if ([".js", ".ts", ".jsx", ".tsx", ".py", ".java", ".go", ".rs", ".c", ".cpp", ".h", ".sh", ".json", ".yaml", ".yml", ".html", ".css"].includes(ext)) return "code";
  if ([".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp"].includes(ext)) return "image";
  if ([".csv", ".tsv", ".xls", ".xlsx"].includes(ext)) return "table";
  if ([".chart", ".plot"].includes(ext)) return "chart";
  return "doc";
}

function _artifactIconSvg(type) {
  const icons = {
    code: '<svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"><path d="m16 18 6-6-6-6"/><path d="m8 6-6 6 6 6"/></svg>',
    doc: '<svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>',
    image: '<svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="9" cy="9" r="2"/><path d="m21 15-5-5L5 21"/></svg>',
    table: '<svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="2"/><path d="M3 9h18M3 15h18M9 3v18M15 3v18"/></svg>',
    chart: '<svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"><path d="M3 3v18h18"/><path d="M7 15l3-3 4 4 6-6"/></svg>',
  };
  return icons[type] || icons.doc;
}

async function refreshSessions() {
  try {
    const data = await api("/api/sessions");
    state.sessions = data.sessions || [];
    applyState(data);
    refreshChatTitle();
    renderSessionList();
  } catch (err) {
    agentStatus.set("error", "加载会话失败", err.message || "");
  }
}

async function refreshFiles() {
  try {
    const data = await api("/api/files");
    applyState(data);
    state.fileGroups = data.groups || [];
    renderSessionList();
  } catch (err) {
    // non-fatal
  }
}

function renderSessionList() {
  if (!els.sessionList) return;
  const filterVal = (state.sessionFilter || "").trim().toLowerCase();
  const filesBySession = new Map();
  for (const group of state.fileGroups || []) {
    filesBySession.set(group.session_id, group);
  }

  const list = (state.sessions || []).filter((item) => {
    if (!filterVal) return true;
    const hay = `${item.label || ""} ${item.session_id || ""}`.toLowerCase();
    return hay.includes(filterVal);
  });

  els.sessionList.innerHTML = "";
  let lastGroup = null;
  for (const item of list) {
    const group = _sessionDateLabel(item.last_active);
    if (group !== lastGroup) {
      lastGroup = group;
      const hdr = document.createElement("div");
      hdr.className = "section-label";
      hdr.textContent = group;
      els.sessionList.appendChild(hdr);
    }

    const files = filesBySession.get(item.session_id);
    const artifactCount = files ? (files.file_count || (files.files || []).length) : 0;
    const hasArtifacts = artifactCount > 0;
    const isActive = item.session_id === state.sessionId;
    const isOpen = state.openConvos.has(item.session_id) && hasArtifacts;

    const convo = document.createElement("div");
    convo.className = "convo" + (isActive ? " active" : "") + (isOpen ? " open" : "");
    convo.dataset.sessionId = item.session_id;

    const label = item.label || item.session_id;
    const relTime = _relTime(item.last_active);
    const usage = item.usage || null;
    const tokBarHTML = usage && usage.limit ? `
      <div class="tok-bar" title="${usage.tokens.toLocaleString()} / ${usage.limit.toLocaleString()} tokens">
        <div class="tok-track"><div class="tok-fill${(usage.tokens / usage.limit) >= 0.75 ? " warn" : ""}" style="width: ${Math.min(100, (usage.tokens / usage.limit) * 100)}%"></div></div>
        <div class="tok-text">${_fmtTokens(usage.tokens)}<span>/${_fmtTokens(usage.limit)}</span></div>
      </div>` : "";

    convo.innerHTML = `
      <div class="convo-head">
        <span class="convo-caret">
          ${hasArtifacts ? `<svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2"><path d="m9 6 6 6-6 6" stroke-linecap="round" stroke-linejoin="round"/></svg>` : `<svg viewBox="0 0 24 24" width="10" height="10" fill="currentColor" style="opacity:0.3"><circle cx="12" cy="12" r="2"/></svg>`}
        </span>
        <div class="convo-meta">
          <div class="convo-row">
            <div class="convo-title" title="${escapeHtml(label)}">${escapeHtml(label)}</div>
            ${item.running ? `<span class="convo-running">运行中</span>` : ""}
            <span class="convo-time">${escapeHtml(relTime)}</span>
          </div>
          ${tokBarHTML}
        </div>
        <button class="convo-del icon-btn" title="删除会话" aria-label="删除会话">
          <svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"><path d="M18 6 6 18M6 6l12 12"/></svg>
        </button>
      </div>
      <div class="artifacts"></div>
    `;

    const artifactsDiv = convo.querySelector(".artifacts");
    if (files && (files.files || []).length) {
      for (const f of files.files) {
        const type = _artifactType(f.name);
        const a = document.createElement("a");
        a.className = `artifact-row`;
        a.href = `/api/download?path=${encodeURIComponent(f.path)}`;
        a.target = "_blank";
        a.innerHTML = `
          <div class="artifact-icon t-${type}">${_artifactIconSvg(type)}</div>
          <div class="artifact-name">${escapeHtml(f.name)}</div>
          <div class="artifact-meta">${_humanSize(f.size || 0)}</div>
        `;
        a.addEventListener("click", (e) => e.stopPropagation());
        artifactsDiv.appendChild(a);
      }
    }

    const head = convo.querySelector(".convo-head");
    head.addEventListener("click", (e) => {
      if (e.target.closest(".convo-del")) return;
      if (convo.querySelector(".convo-title-input")) return;
      if (hasArtifacts) {
        if (state.openConvos.has(item.session_id)) {
          state.openConvos.delete(item.session_id);
        } else {
          state.openConvos.add(item.session_id);
        }
      }
      if (item.session_id !== state.sessionId) {
        switchSession(item.session_id);
      } else {
        renderSessionList();
      }
    });
    convo.querySelector(".convo-title").addEventListener("dblclick", (e) => {
      e.stopPropagation();
      startRenameSession(convo, item.session_id, item.label || "");
    });
    convo.querySelector(".convo-del").addEventListener("click", (e) => {
      e.stopPropagation();
      deleteSession(item.session_id);
    });

    els.sessionList.appendChild(convo);
  }
}

function startRenameSession(row, sessionId, currentLabel) {
  const labelEl = row.querySelector(".convo-title");
  if (!labelEl || labelEl.querySelector("input")) return;
  const displayLabel = currentLabel || sessionId;
  const input = document.createElement("input");
  input.type = "text";
  input.className = "convo-title-input";
  input.value = currentLabel;
  input.placeholder = sessionId;
  input.addEventListener("click", (e) => e.stopPropagation());
  input.addEventListener("dblclick", (e) => e.stopPropagation());

  let cancelled = false;
  const commit = async () => {
    if (cancelled) { labelEl.textContent = displayLabel; return; }
    const newLabel = input.value.trim();
    if (newLabel !== currentLabel) {
      await renameSession(sessionId, newLabel);
    } else {
      labelEl.textContent = displayLabel;
    }
  };
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter") { e.preventDefault(); input.blur(); }
    if (e.key === "Escape") { cancelled = true; input.blur(); }
  });
  input.addEventListener("blur", commit);

  labelEl.textContent = "";
  labelEl.appendChild(input);
  input.focus();
  input.select();
}

async function renameSession(sessionId, label) {
  try {
    await api("/api/session/rename", {
      method: "POST",
      body: { session_id: sessionId, label },
    });
    if (sessionId === state.sessionId) state.currentLabel = label;
    await Promise.all([refreshSessions(), refreshFiles()]);
    refreshChatTitle();
  } catch (err) {
    agentStatus.set("error", "重命名失败", err.message);
  }
}

function startRenameChatTitle() {
  if (!els.chatTitle || !state.sessionId) return;
  if (els.chatTitle.querySelector(".chat-title-input")) return;
  const current = (els.chatTitle.textContent || "").trim();
  const sess = (state.sessions || []).find((s) => s.session_id === state.sessionId);
  const initialLabel = (sess && sess.label) || "";
  const displayFallback = initialLabel || current || state.sessionId.slice(0, 8);

  const input = document.createElement("input");
  input.type = "text";
  input.className = "chat-title-input";
  input.value = initialLabel || current;
  input.placeholder = state.sessionId.slice(0, 8);

  let cancelled = false;
  const commit = async () => {
    els.chatTitle.classList.remove("editing");
    if (cancelled) {
      els.chatTitle.textContent = displayFallback;
      return;
    }
    const newLabel = input.value.trim();
    if (newLabel === initialLabel) {
      els.chatTitle.textContent = displayFallback;
      return;
    }
    els.chatTitle.textContent = newLabel || state.sessionId.slice(0, 8);
    await renameSession(state.sessionId, newLabel);
  };
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter") { e.preventDefault(); input.blur(); }
    if (e.key === "Escape") { cancelled = true; input.blur(); }
  });
  input.addEventListener("blur", commit);

  els.chatTitle.classList.add("editing");
  els.chatTitle.textContent = "";
  els.chatTitle.appendChild(input);
  input.focus();
  input.select();
}

async function deleteSession(sessionId) {
  try {
    const data = await api("/api/session/delete", {
      method: "POST",
      body: { session_id: sessionId },
    });
    applyState(data);
    await Promise.all([refreshMessages(), refreshSessions(), refreshFiles()]);
  } catch (err) {
    agentStatus.set("error", "删除失败", err.message);
  }
}

// ─── Streaming bubble ───
function createAssistantBubble() {
  const shell = createMessageShell("assistant", { msgId: `m-${_msgIndex++}`, time: new Date() });
  return {
    root: shell.root,
    body: shell.body,
    copyBtn: shell.copyBtn,
    downloads: shell.downloads,
    currentText: null,
    textParts: [],
    toolBlocks: {},
    cursor: null,
  };
}

function ensureCursor(bubble) {
  if (bubble.cursor && bubble.cursor.parentNode) return;
  const cur = document.createElement("span");
  cur.className = "cursor";
  bubble.body.appendChild(cur);
  bubble.cursor = cur;
}

function removeCursor(bubble) {
  if (bubble.cursor && bubble.cursor.parentNode) {
    bubble.cursor.remove();
  }
  bubble.cursor = null;
}

function finalizeToolGroup(bubble) {
  const group = bubble._currentToolGroup;
  if (group && !group._finalized) {
    group._finalized = true;
    const n = group._toolCount || 0;
    group.querySelector(".thinking-icon").textContent = "⊙";
    group.querySelector(".thinking-label").textContent = `工具调用完毕`;
    group.querySelector(".thinking-count").textContent =
      n > 1 ? ` · ${n} 个工具调用` : n === 1 ? ` · 1 个工具调用` : "";
  }
}

function _endOtherBlocks(bubble, keep) {
  if (keep !== "text") bubble.currentText = null;
  if (keep !== "reasoning") bubble._currentReasoning = null;
  if (keep !== "tool") finalizeToolGroup(bubble);
}

function appendTextDelta(bubble, delta) {
  removeCursor(bubble);
  _endOtherBlocks(bubble, "text");
  bubble.body.classList.add("rendered");
  if (!bubble.currentText) {
    const span = document.createElement("div");
    span.className = "stream-part";
    bubble.body.appendChild(span);
    bubble.currentText = span;
    bubble.textParts.push({ el: span, raw: "", renderedRaw: "", renderHandle: null });
  }
  const part = bubble.textParts[bubble.textParts.length - 1];
  part.raw += delta;
  setCopyButtonState(
    bubble.copyBtn,
    bubble.textParts.map((p) => p.raw).join("\n\n"),
  );
  scheduleStreamingTextRender(part);
  ensureCursor(bubble);
  autoScrollIfNear();
}

function appendReasoningDelta(bubble, delta) {
  removeCursor(bubble);
  _endOtherBlocks(bubble, "reasoning");
  if (!bubble._currentReasoning) {
    const block = document.createElement("div");
    block.className = "reasoning-block stream-part";
    block.innerHTML = `<div class="reasoning-label">REASONING</div><div class="reasoning-text"></div>`;
    bubble.body.appendChild(block);
    bubble._currentReasoning = block.querySelector(".reasoning-text");
  }
  bubble._currentReasoning.appendChild(document.createTextNode(delta));
  autoScrollIfNear();
}

function startReasoningPart(bubble) {
  bubble._currentReasoning = null;
}

function addToolBlock(bubble, { call_id, name }) {
  removeCursor(bubble);
  _endOtherBlocks(bubble, "tool");

  let group = bubble._currentToolGroup;
  if (!group || group._finalized) {
    group = document.createElement("div");
    group.className = "thinking-group stream-part collapsed";
    group.innerHTML = `
      <div class="thinking-head">
        <span class="thinking-icon">⊘</span>
        <span class="thinking-label">调用工具中</span>
        <span class="thinking-count"></span>
        <span class="caret">▾</span>
      </div>
      <div class="thinking-body"></div>
    `;
    group._toolCount = 0;
    group._finalized = false;
    group.querySelector(".thinking-head").addEventListener("click", () => {
      group.classList.toggle("collapsed");
    });
    bubble.body.appendChild(group);
    bubble._currentToolGroup = group;
  }

  group._toolCount++;
  group.querySelector(".thinking-count").textContent =
    group._toolCount > 1 ? ` (${group._toolCount} 个工具调用)` : "";

  const wrap = document.createElement("div");
  wrap.className = "tool-block";
  wrap.innerHTML = `
    <div class="tool-head">
      <span class="badge">TOOL</span>
      <span class="tool-name"></span>
      <span class="tool-status">调用中…</span>
    </div>
    <div class="tool-body">
      <div class="tool-label">INPUT</div>
      <pre class="tool-input">（等待参数…）</pre>
    </div>
  `;
  wrap.querySelector(".tool-name").textContent = name || "tool";
  group.querySelector(".thinking-body").appendChild(wrap);
  bubble.toolBlocks[call_id] = wrap;
  autoScrollIfNear();
  return wrap;
}

function finalizeToolInput(bubble, { call_id, id, name, input }) {
  let wrap = bubble.toolBlocks[call_id];
  if (!wrap) wrap = addToolBlock(bubble, { call_id, name });
  wrap.querySelector(".tool-name").textContent = name || "tool";
  wrap.querySelector(".tool-input").textContent = JSON.stringify(input || {}, null, 2);
  wrap.querySelector(".tool-status").textContent = "执行中…";
  if (id) bubble.toolBlocks[id] = wrap;
  autoScrollIfNear();
}

function attachToolResult(bubble, { tool_use_id, name, content, is_error }) {
  let wrap = bubble.toolBlocks[tool_use_id];
  if (!wrap) {
    const callId = String(tool_use_id || "").split("|")[0];
    wrap = bubble.toolBlocks[callId];
  }
  if (!wrap) {
    wrap = addToolBlock(bubble, { call_id: tool_use_id, name });
  }
  if (is_error) wrap.classList.add("error");
  wrap.querySelector(".tool-status").textContent = is_error ? "失败" : "完成";
  const body = wrap.querySelector(".tool-body");
  const label = document.createElement("div");
  label.className = "tool-label";
  label.textContent = is_error ? "ERROR" : "OUTPUT";
  const pre = document.createElement("pre");
  pre.textContent = content || "";
  body.appendChild(label);
  body.appendChild(pre);

  if (!is_error && content) {
    for (const outputPath of _extractOutputPaths(name, content)) {
      const dlBtn = createDownloadButton(outputPath);
      if (!bubble._pendingDownloads) bubble._pendingDownloads = [];
      bubble._pendingDownloads.push(dlBtn);
    }
  }
  autoScrollIfNear();
}

function autoScrollIfNear() {
  const el = els.messages;
  const nearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 160;
  if (nearBottom) el.scrollTop = el.scrollHeight;
}

// ─── File helpers ───
const FILE_ICONS = {
  ".docx": "📄", ".doc": "📄",
  ".xlsx": "📊", ".xls": "📊", ".csv": "📊",
  ".pptx": "📑", ".ppt": "📑",
  ".pdf": "📕", ".txt": "📝", ".md": "📝",
  ".png": "🖼️", ".jpg": "🖼️", ".jpeg": "🖼️", ".gif": "🖼️", ".svg": "🖼️",
  ".zip": "📦", ".json": "📋", ".html": "🌐",
};

function _fileIcon(name) {
  const ext = (name.match(/\.[^.]+$/) || [""])[0].toLowerCase();
  return FILE_ICONS[ext] || "📁";
}

function _humanSize(bytes) {
  if (!bytes) return "0 B";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function _extractOutputPaths(toolName, resultText) {
  if (toolName !== "write_file" && toolName !== "bash") return [];
  const matches = resultText.match(/workplace\/output\/([^\s"'`)\]}]+)/gi) || [];
  const outputPaths = [];
  for (const match of matches) {
    const relPath = match.replace(/^.*?workplace\/output\//i, "").replace(/[),;:\]}]+$/, "");
    if (!outputPaths.includes(relPath)) outputPaths.push(relPath);
  }
  return outputPaths;
}

function createDownloadButton(relPath) {
  const name = relPath.split("/").pop();
  const a = document.createElement("a");
  a.className = "file-download";
  a.href = `/api/download?path=${encodeURIComponent(relPath)}`;
  a.target = "_blank";
  a.innerHTML = `<span class="file-icon">${_fileIcon(name)}</span>` +
    `<span class="file-info">` +
    `<span class="file-name">${escapeHtml(name)}</span>` +
    `<span class="file-meta">点击下载</span>` +
    `</span>`;
  return a;
}

// ─── SSE Chat Stream ───
async function streamChat(text, files = []) {
  const launchedSessionId = state.sessionId;
  const bubble = createAssistantBubble();
  state.liveBubbles.set(launchedSessionId, bubble);
  els.chatInner.appendChild(bubble.root);
  els.messages.scrollTop = els.messages.scrollHeight;
  ensureCursor(bubble);
  scheduleMinimapRebuild();
  const canRenderStream = () => state.sessionId === launchedSessionId;

  agentStatus.set("busy", "提交请求中", `正在发送消息到 Agent${files.length ? `（含 ${files.length} 个附件）` : ""}`);

  const payload = { text, session_id: launchedSessionId };
  if (files && files.length) payload.files = files;
  const resp = await fetch("/api/chat/stream", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!resp.ok || !resp.body) {
    throw new Error(`HTTP ${resp.status}`);
  }

  const reader = resp.body.getReader();
  const decoder = new TextDecoder("utf-8");
  let buf = "";
  let finished = false;

  const handle = (evt) => {
    if (!evt || !evt.type) return;
    agentStatus.markActivity();
    switch (evt.type) {
      case "text_delta":
        if (canRenderStream()) {
          appendTextDelta(bubble, evt.text || "");
          agentStatus.set("streaming", "生成回复中", "模型正在输出最终回答…");
        }
        break;
      case "reasoning_delta":
        if (canRenderStream()) {
          appendReasoningDelta(bubble, evt.text || "");
          agentStatus.set("thinking", "思考中", "模型正在进行推理（reasoning）…");
        }
        break;
      case "reasoning_part_added":
        if (canRenderStream()) {
          startReasoningPart(bubble);
          agentStatus.set("thinking", "思考中", "开始新的推理片段…");
        }
        break;
      case "reasoning_part_done":
        break;
      case "tool_use_started":
        if (canRenderStream()) {
          addToolBlock(bubble, { call_id: evt.call_id, name: evt.name });
          agentStatus.set("tool", `调用工具: ${evt.name || "unknown"}`, "模型正在构造工具调用参数…");
        }
        break;
      case "tool_use_done":
        if (canRenderStream()) {
          finalizeToolInput(bubble, evt);
          agentStatus.set("tool", `执行工具: ${evt.name || "unknown"}`, "等待工具返回结果…");
        }
        break;
      case "tool_result":
        if (canRenderStream()) {
          attachToolResult(bubble, evt);
          agentStatus.set("busy", "工具已返回", "继续交由模型处理结果…");
        }
        break;
      case "turn_start":
        if (canRenderStream()) {
          agentStatus.set("busy", `第 ${evt.turn || 1} 轮`, "开始新一轮 LLM 推理…");
        }
        if (canRenderStream() && evt.turn && evt.turn > 1) {
          removeCursor(bubble);
          bubble.currentText = null;
          const div = document.createElement("div");
          div.className = "turn-divider stream-part";
          div.textContent = `· turn ${evt.turn} ·`;
          bubble.body.appendChild(div);
          ensureCursor(bubble);
        }
        break;
      case "compacted":
        if (canRenderStream()) {
          agentStatus.set("busy", "上下文已压缩", `autocompact → ${evt.display || ""}`);
        }
        if (state.sessionId === launchedSessionId) {
          appendMessage("system", `[autocompact -> ${evt.display || ""}]`);
        }
        break;
      case "truncated":
        agentStatus.set("error", "已截断", `已达到 max_turns=${evt.max_turns} 上限`);
        if (state.sessionId === launchedSessionId) {
          appendMessage(
            "system",
            `⚠️ 已达到 max_turns=${evt.max_turns} 上限,任务被截断。再发一条消息可让我继续。`,
          );
        }
        break;
      case "cancelled":
        setSessionRunning(launchedSessionId, false);
        agentStatus.set("idle", "已取消", "当前会话被用户取消");
        if (state.sessionId === launchedSessionId) {
          appendMessage("system", "当前会话已请求取消。");
        }
        break;
      case "done":
        setSessionRunning(launchedSessionId, false);
        if (canRenderStream()) {
          agentStatus.set("idle", "完成", "回答已返回");
          removeCursor(bubble);
          finalizeToolGroup(bubble);
          for (const part of bubble.textParts) {
            finalizeStreamingTextPart(part);
          }
          bubble.body.classList.add("rendered");
          if (!bubble.body.textContent.trim()) {
            bubble.body.innerHTML = renderMarkdown(evt.text || "(empty response)");
            enhanceRenderedContent(bubble.body);
          }
          setCopyButtonState(
            bubble.copyBtn,
            bubble.textParts.map((p) => p.raw).join("\n\n") || evt.text || "",
          );
          if (bubble._pendingDownloads && bubble._pendingDownloads.length) {
            const dlContainer = bubble.root.querySelector(".msg-downloads");
            for (const btn of bubble._pendingDownloads) {
              dlContainer.appendChild(btn);
            }
          }
          scheduleMinimapRebuild();
        }
        if (evt.session_id && state.sessionId === launchedSessionId) {
          state.sessionId = evt.session_id;
          if (els.sessionId) els.sessionId.textContent = evt.session_id.slice(0, 8);
        }
        state.liveBubbles.delete(launchedSessionId);
        finished = true;
        break;
      case "injected":
        if (canRenderStream()) {
          removeCursor(bubble);
          _endOtherBlocks(bubble, null);
          const injDiv = document.createElement("div");
          injDiv.className = "injected-msg stream-part";
          injDiv.innerHTML = `<span class="injected-badge">USER</span> ${escapeHtml(evt.text || "")}`;
          bubble.body.appendChild(injDiv);
          ensureCursor(bubble);
          agentStatus.set("busy", "插话已送达", "Agent 正在基于你的新消息继续推理…");
          autoScrollIfNear();
        }
        break;
      case "state":
        if (state.sessionId === launchedSessionId) {
          applyState(evt);
        } else if (typeof evt.running === "boolean") {
          setSessionRunning(launchedSessionId, evt.running);
        }
        break;
      case "error":
        setSessionRunning(launchedSessionId, false);
        if (canRenderStream()) {
          agentStatus.set("error", "发生错误", evt.error || "未知错误");
          removeCursor(bubble);
        }
        if (state.sessionId === launchedSessionId) {
          appendMessage("system", `请求失败: ${evt.error || "unknown"}`);
        }
        state.liveBubbles.delete(launchedSessionId);
        break;
    }
  };

  try {
    while (!finished) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      let idx;
      while ((idx = buf.indexOf("\n\n")) !== -1) {
        const frame = buf.slice(0, idx);
        buf = buf.slice(idx + 2);
        const lines = frame.split("\n");
        const dataLines = [];
        for (const line of lines) {
          if (line.startsWith("data:")) {
            dataLines.push(line.slice(5).replace(/^ /, ""));
          }
        }
        if (!dataLines.length) continue;
        const raw = dataLines.join("\n");
        if (raw === "[DONE]") { finished = true; continue; }
        try { handle(JSON.parse(raw)); } catch (_) {}
        if (finished) break;
      }
    }
  } finally {
    try { await reader.cancel(); } catch (_) {}
    removeCursor(bubble);
    finalizeToolGroup(bubble);
    if (!finished) {
      for (const part of bubble.textParts) {
        finalizeStreamingTextPart(part);
      }
      bubble.body.classList.add("rendered");
      setSessionRunning(launchedSessionId, false);
      agentStatus.set("idle", "连接已结束", "流式响应提前终止，已显示已接收的内容");
    }
    state.liveBubbles.delete(launchedSessionId);
  }
}

async function injectMessage(sessionId, text) {
  appendMessage("user", text);
  agentStatus.set("busy", "已插话", "Agent 将在当前工具执行完后看到你的消息");
  try {
    await api("/api/session/inject", {
      method: "POST",
      body: { session_id: sessionId, text },
    });
  } catch (err) {
    appendMessage("system", `插话失败: ${err.message}`);
  }
}

async function sendMessage(text) {
  if (!text.trim() && !state.pendingFiles.length) return;
  const launchedSessionId = state.sessionId;

  if (launchedSessionId && state.runningSessions.has(launchedSessionId)) {
    if (!text.trim()) return;
    await injectMessage(launchedSessionId, text);
    clearReplyCtx();
    return;
  }

  // If we have a reply-ctx, prepend as plain-text quote marker
  let composed = text;
  if (state.replyCtx && state.replyCtx.text) {
    const raw = state.replyCtx.text.replace(/\s+/g, " ").trim();
    const snippet = raw.length > 240 ? raw.slice(0, 240) + "…" : raw;
    const escaped = snippet.replace(/\\/g, "\\\\").replace(/"/g, '\\"');
    composed = `[引用: "${escaped}"]\n\n${text}`;
  }

  const filePaths = state.pendingFiles.map((f) => f.serverPath);
  const fileNames = state.pendingFiles.map((f) => f.name);
  state.pendingFiles = [];
  renderFilePreview();
  clearReplyCtx();

  if (composed.startsWith("/")) {
    setBusy(true, launchedSessionId);
    agentStatus.set("busy", `执行命令 ${composed}`, "调用后端命令处理器…");
    try {
      const data = await api("/api/command", {
        method: "POST",
        body: { text: composed, session_id: launchedSessionId },
      });
      data.session_id = data.session_id || launchedSessionId;
      applyState(data);
      await refreshMessages();
      appendMessage("system", `> ${composed}`);
      if (data.text && data.text !== "__EXIT__") {
        appendMessage("system", data.text);
      }
      await Promise.all([refreshSessions(), refreshFiles()]);
      agentStatus.set("idle", "命令完成", `${composed} 已执行`);
    } catch (err) {
      const msg = err.message || "unknown";
      const isRunning = /session is running|running/i.test(msg);
      appendMessage("system", `命令错误: ${msg}`);
      agentStatus.set(
        "error",
        isRunning ? `无法执行 ${composed}` : `命令失败`,
        isRunning ? "当前会话仍在运行中。请先点击「停止」或等待本轮完成后再执行命令。" : msg,
      );
    } finally {
      setBusy(false, launchedSessionId);
    }
    return;
  }

  const displayText = fileNames.length
    ? composed + "\n" + fileNames.map((n) => `[${_fileIcon(n)} ${n}]`).join(" ")
    : composed;
  appendMessage("user", displayText);
  setSessionRunning(launchedSessionId, true);
  agentStatus.set("busy", "已提交消息", "正在建立到 Agent 的流式连接…");
  try {
    await streamChat(composed, filePaths);
    await Promise.all([refreshSessions(), refreshFiles()]);
  } catch (err) {
    appendMessage("system", `请求失败: ${err.message}`);
    agentStatus.set("error", "请求失败", err.message || "unknown");
  } finally {
    setSessionRunning(launchedSessionId, false);
  }
}

async function newSession() {
  try {
    const data = await api("/api/session/new", { method: "POST" });
    // Reset local filter so the new session is never hidden behind a stale search
    if (els.sessionSearch) els.sessionSearch.value = "";
    state.sessionFilter = "";
    state.currentLabel = typeof data.label === "string" ? data.label : "";
    applyState(data);
    // Load sessions first so the list doesn't flicker to empty before /sessions returns
    await refreshSessions();
    await Promise.all([refreshMessages(), refreshFiles()]);
  } catch (err) {
    agentStatus.set("error", "新建会话失败", err.message);
  }
}

async function switchSession(prefix) {
  try {
    if (!prefix || prefix === state.sessionId) return;
    const data = await api("/api/session/switch", {
      method: "POST",
      body: { session_id_prefix: prefix, session_id: state.sessionId },
    });
    applyState(data);
    await refreshMessages();
    window.requestAnimationFrame(refreshSessions);
    window.setTimeout(refreshFiles, 180);
  } catch (err) {
    agentStatus.set("error", "切换会话失败", err.message);
  }
}

// ─── Reply context ───
function setReplyCtx(ctx) {
  state.replyCtx = ctx;
  if (!els.replyCtx) return;
  if (!ctx) {
    els.replyCtx.classList.add("hidden");
    return;
  }
  els.replyCtx.classList.remove("hidden");
  const snippet = (ctx.text || "").replace(/\s+/g, " ").trim().slice(0, 60);
  els.replyCtxText.textContent = `引用 ${ctx.who}: ${snippet}${snippet.length >= 60 ? "…" : ""}`;
  els.input.focus();
}

function clearReplyCtx() {
  setReplyCtx(null);
}

els.replyCtxClear?.addEventListener("click", clearReplyCtx);

// ─── Minimap ───
let minimapRebuildHandle = null;
function scheduleMinimapRebuild() {
  if (minimapRebuildHandle) return;
  minimapRebuildHandle = window.requestAnimationFrame(() => {
    minimapRebuildHandle = null;
    rebuildMinimap();
  });
}

function rebuildMinimap() {
  if (!els.mmCanvas) return;
  const scroller = els.messages;
  if (!scroller) return;
  els.mmCanvas.innerHTML = "";

  const userMsgs = els.chatInner.querySelectorAll(".msg.u");
  if (!userMsgs.length) {
    const empty = document.createElement("div");
    empty.className = "mm-empty";
    empty.textContent = "暂无提问";
    els.mmCanvas.appendChild(empty);
    return;
  }

  userMsgs.forEach((msgEl, idx) => {
    const bodyEl = msgEl.querySelector(".body");
    const raw = (bodyEl?.textContent || "").replace(/\s+/g, " ").trim();
    const snippet = raw.length > 64 ? raw.slice(0, 64) + "…" : (raw || "（空）");
    const item = document.createElement("div");
    item.className = "mm-nav";
    item.dataset.msgId = msgEl.dataset.msgId || "";
    item.innerHTML = `<span class="mm-idx">${idx + 1}</span><span class="mm-text"></span>`;
    item.querySelector(".mm-text").textContent = snippet;
    item.title = raw || "";
    item.addEventListener("click", (e) => {
      e.stopPropagation();
      const top = msgEl.offsetTop - 24;
      scroller.scrollTo({ top, behavior: "smooth" });
    });
    els.mmCanvas.appendChild(item);
  });
  updateMinimapActive();
}

function updateMinimapActive() {
  if (!els.mmCanvas) return;
  const scroller = els.messages;
  if (!scroller) return;
  const threshold = scroller.scrollTop + 80;
  const userMsgs = els.chatInner.querySelectorAll(".msg.u");
  let activeIdx = -1;
  userMsgs.forEach((m, i) => {
    if (m.offsetTop <= threshold) activeIdx = i;
  });
  const items = els.mmCanvas.querySelectorAll(".mm-nav");
  items.forEach((it, i) => it.classList.toggle("active", i === activeIdx));
}

function bindMinimap() {
  if (!els.minimap) return;
  els.messages.addEventListener("scroll", updateMinimapActive);
  window.addEventListener("resize", scheduleMinimapRebuild);
}

// ─── File upload ───
function renderFilePreview() {
  els.filePreviewBar.innerHTML = "";
  els.filePreviewBar.classList.toggle("hidden", !state.pendingFiles.length);
  for (let i = 0; i < state.pendingFiles.length; i++) {
    const f = state.pendingFiles[i];
    const item = document.createElement("div");
    item.className = "file-preview-item";

    const isImage = f.file.type.startsWith("image/");
    if (isImage) {
      const thumb = document.createElement("img");
      thumb.className = "fp-thumb";
      thumb.src = URL.createObjectURL(f.file);
      item.appendChild(thumb);
    } else {
      const icon = document.createElement("span");
      icon.className = "fp-icon";
      icon.textContent = _fileIcon(f.name);
      item.appendChild(icon);
    }

    const nameEl = document.createElement("span");
    nameEl.className = "fp-name";
    nameEl.textContent = f.name;
    item.appendChild(nameEl);

    const sizeEl = document.createElement("span");
    sizeEl.className = "fp-size";
    sizeEl.textContent = _humanSize(f.file.size);
    item.appendChild(sizeEl);

    const removeBtn = document.createElement("button");
    removeBtn.className = "fp-remove";
    removeBtn.textContent = "×";
    removeBtn.addEventListener("click", () => {
      state.pendingFiles.splice(i, 1);
      renderFilePreview();
    });
    item.appendChild(removeBtn);

    els.filePreviewBar.appendChild(item);
  }
}

async function uploadFiles(files) {
  if (!files || !files.length) return [];
  const formData = new FormData();
  for (const f of files) {
    formData.append("files", f, f.name);
  }
  const resp = await fetch("/api/upload", { method: "POST", body: formData });
  const data = await resp.json();
  if (!data.ok) throw new Error(data.error || "upload failed");
  return data.files;
}

async function addFiles(fileList) {
  if (!fileList || !fileList.length) return;
  try {
    const saved = await uploadFiles(fileList);
    for (let i = 0; i < saved.length; i++) {
      state.pendingFiles.push({
        file: fileList[i],
        serverPath: saved[i].path,
        name: saved[i].name,
      });
    }
    renderFilePreview();
  } catch (err) {
    appendMessage("system", `文件上传失败: ${err.message}`);
  }
}

els.btnAttach?.addEventListener("click", () => els.fileInput.click());
els.fileInput?.addEventListener("change", () => {
  if (els.fileInput.files.length) {
    addFiles(Array.from(els.fileInput.files));
    els.fileInput.value = "";
  }
});

els.composer?.addEventListener("dragover", (e) => {
  e.preventDefault();
  els.composer.classList.add("drag-over");
});
els.composer?.addEventListener("dragleave", () => {
  els.composer.classList.remove("drag-over");
});
els.composer?.addEventListener("drop", (e) => {
  e.preventDefault();
  els.composer.classList.remove("drag-over");
  if (e.dataTransfer.files.length) {
    addFiles(Array.from(e.dataTransfer.files));
  }
});

// ─── Composer events ───
els.composer?.addEventListener("submit", (e) => {
  e.preventDefault();
  const text = els.input.value;
  els.input.value = "";
  autosize();
  sendMessage(text);
});

els.input?.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey && !e.isComposing && !(e.metaKey || e.ctrlKey)) {
    e.preventDefault();
    els.composer.requestSubmit();
  }
  if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
    e.preventDefault();
    els.composer.requestSubmit();
  }
});

els.input?.addEventListener("focus", () => els.composer.classList.add("focus"));
els.input?.addEventListener("blur", () => els.composer.classList.remove("focus"));

function autosize() {
  if (!els.input) return;
  els.input.style.height = "auto";
  els.input.style.height = Math.min(els.input.scrollHeight, 240) + "px";
}
els.input?.addEventListener("input", autosize);

els.btnLogout?.addEventListener("click", logout);
els.btnNew?.addEventListener("click", newSession);
els.btnRefresh?.addEventListener("click", () => {
  refreshMessages();
  refreshSessions();
  refreshFiles();
});
els.btnCompact?.addEventListener("click", () => sendMessage("/compact"));
els.btnStop?.addEventListener("click", async () => {
  if (!state.sessionId || !state.runningSessions.has(state.sessionId)) return;
  try {
    const data = await api("/api/session/cancel", {
      method: "POST",
      body: { session_id: state.sessionId },
    });
    applyState(data);
    appendMessage("system", "已发送取消请求。");
  } catch (err) {
    agentStatus.set("error", "取消失败", err.message);
  }
});

els.chatTitle?.addEventListener("dblclick", (e) => {
  e.preventDefault();
  if (!state.sessionId) return;
  startRenameChatTitle();
});

els.btnMinimapJump?.addEventListener("click", () => {
  els.messages.scrollTo({ top: els.messages.scrollHeight, behavior: "smooth" });
});

els.scrollBtn?.addEventListener("click", () => {
  els.messages.scrollTo({ top: els.messages.scrollHeight, behavior: "smooth" });
});

els.messages?.addEventListener("scroll", () => {
  const gap = els.messages.scrollHeight - els.messages.scrollTop - els.messages.clientHeight;
  els.scrollBtn?.classList.toggle("hidden", gap < 200);
});

els.sessionSearch?.addEventListener("input", () => {
  state.sessionFilter = els.sessionSearch.value;
  renderSessionList();
});

document.querySelectorAll(".chip[data-cmd]").forEach((chip) => {
  chip.addEventListener("click", () => {
    const cmd = chip.dataset.cmd;
    if (els.input) {
      els.input.value = cmd;
      autosize();
      els.input.focus();
    }
  });
});

// Keyboard shortcuts
document.addEventListener("keydown", (e) => {
  const isMod = e.metaKey || e.ctrlKey;
  if (isMod && e.key.toLowerCase() === "k") {
    e.preventDefault();
    els.sessionSearch?.focus();
  }
  if (isMod && e.key.toLowerCase() === "n") {
    e.preventDefault();
    newSession();
  }
});

// Bind dividers
bindDividerDrag(els.colDividerLeft, true);
bindDividerDrag(els.colDividerRight, false);
window.addEventListener("resize", positionDividers);
loadCols();

// Minimap init
bindMinimap();

// ─── Boot ───
(async () => {
  try {
    const me = await api("/api/auth/me");
    if (me.user && els.userEmail) {
      els.userEmail.textContent = me.user.email;
      if (els.userAvatar) els.userAvatar.textContent = (me.user.email[0] || "·").toUpperCase();
    }
  } catch (_) {
    return;
  }
  try {
    const data = await api("/api/state");
    applyState(data);
  } catch (err) {
    agentStatus.set("error", "无法获取状态", err.message);
    return;
  }
  await Promise.all([refreshMessages(), refreshSessions(), refreshFiles()]);
  agentStatus.set("idle", "就绪", "等待你的指令");
  els.input?.focus();
})();
