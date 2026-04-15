// Pooh Code frontend — vanilla JS, no build step.

const $ = (sel) => document.querySelector(sel);

const els = {
  messages: $("#messages"),
  emptyHint: $("#empty-hint"),
  input: $("#input"),
  composer: $("#composer"),
  btnSend: $("#btn-send"),
  btnStop: $("#btn-stop"),
  btnNew: $("#btn-new"),
  btnRefresh: $("#btn-refresh"),
  sidebarResizer: $("#sidebar-resizer"),
  btnAttach: $("#btn-attach"),
  fileInput: $("#file-input"),
  filePreviewBar: $("#file-preview-bar"),
  sessionList: $("#session-list"),
  fileGroups: $("#file-groups"),
  filesSummary: $("#files-summary"),
  sessionId: $("#session-id"),
  usageLabel: $("#usage-label"),
  contextPill: $("#context-pill"),
  modelPill: $("#model-pill"),
  themeToggle: $("#theme-toggle"),
  modelLabel: $("#model-label"),
  statusDot: $("#status-dot"),
  statusText: $("#status-text"),
  agentStatus: $("#agent-status"),
  agentStatusTitle: $("#agent-status-title"),
  agentStatusDetail: $("#agent-status-detail"),
  agentStatusTimer: $("#agent-status-timer"),
  agentStatusClose: $("#agent-status-close"),
};

// ───────── 主页面 Agent 状态面板 ─────────
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
    // 超过 8 秒没新事件：在详情里追加实时的"X 秒无进展"，并随时间刷新。
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

  function setTitle(text) {
    if (els.agentStatusTitle) els.agentStatusTitle.textContent = text;
  }
  function setDetail(text) {
    if (els.agentStatusDetail) els.agentStatusDetail.textContent = text;
  }

  function set(newLevel, title, detail) {
    level = newLevel || "idle";
    if (title != null) setTitle(title);
    if (detail != null) {
      baseDetail = detail;
      setDetail(detail);
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

  // idle 时也保留可见（让用户看到"就绪"）
  render();

  return { set, reset, markActivity, setDetail };
})();

const scrollBtn = document.getElementById("scroll-btn");

let state = {
  sessionId: null,
  sessionKey: null,
  runningSessions: new Set(),
  pendingFiles: [], // [{file: File, serverPath: string, name: string}]
  capabilities: null,
  welcomeCardsCollapsed: {
    commands: false,
    tools: false,
    skills: false,
  },
};

const SIDEBAR_WIDTH_KEY = "pooh.sidebar.width";
const SIDEBAR_MIN = 220;
const SIDEBAR_MAX = 520;
const THEME_KEY = "pooh.theme";

function getPreferredTheme() {
  try {
    const saved = localStorage.getItem(THEME_KEY);
    if (saved === "light" || saved === "dark") return saved;
  } catch (_) { }
  return window.matchMedia?.("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

function updateThemeToggle(theme) {
  if (!els.themeToggle) return;
  const next = theme === "dark" ? "浅色" : "深色";
  els.themeToggle.title = `切换到${next}模式`;
  els.themeToggle.setAttribute("aria-label", `切换到${next}模式`);
}

function applyTheme(theme, { persist = true } = {}) {
  const normalized = theme === "dark" ? "dark" : "light";
  document.body.classList.toggle("theme-dark", normalized === "dark");
  document.body.classList.toggle("theme-light", normalized !== "dark");
  document.documentElement.style.colorScheme = normalized;
  updateThemeToggle(normalized);
  if (!persist) return;
  try {
    localStorage.setItem(THEME_KEY, normalized);
  } catch (_) { }
}

function enableDragScroll(container) {
  if (!container) return;
  let pointerId = null;
  let startY = 0;
  let startScrollTop = 0;
  let dragging = false;
  let moved = false;
  let suppressClick = false;

  container.addEventListener("pointerdown", (e) => {
    if (e.button !== 0) return;
    if (e.target.closest("button, input, textarea, select, label, summary, details, a, [data-copy-skill]")) return;
    e.preventDefault();
    pointerId = e.pointerId;
    startY = e.clientY;
    startScrollTop = container.scrollTop;
    dragging = true;
    moved = false;
    container.classList.add("dragging-scroll");
    container.setPointerCapture(pointerId);
  });

  container.addEventListener("pointermove", (e) => {
    if (!dragging || e.pointerId !== pointerId) return;
    e.preventDefault();
    const deltaY = e.clientY - startY;
    if (Math.abs(deltaY) > 4) moved = true;
    container.scrollTop = startScrollTop - deltaY;
  });

  const stopDragging = (e) => {
    if (!dragging || e.pointerId !== pointerId) return;
    if (container.hasPointerCapture(pointerId)) {
      container.releasePointerCapture(pointerId);
    }
    suppressClick = moved;
    pointerId = null;
    dragging = false;
    container.classList.remove("dragging-scroll");
    if (moved) {
      e.preventDefault();
    }
  };

  container.addEventListener("pointerup", stopDragging);
  container.addEventListener("pointercancel", stopDragging);
  container.addEventListener(
    "click",
    (e) => {
      if (!suppressClick) return;
      e.preventDefault();
      e.stopPropagation();
      suppressClick = false;
    },
    true
  );
}

function applySidebarWidth(width) {
  const clamped = Math.max(SIDEBAR_MIN, Math.min(SIDEBAR_MAX, Math.round(width)));
  document.documentElement.style.setProperty("--sidebar-width", `${clamped}px`);
  try {
    localStorage.setItem(SIDEBAR_WIDTH_KEY, String(clamped));
  } catch (_) { }
}

try {
  const savedWidth = Number(localStorage.getItem(SIDEBAR_WIDTH_KEY) || 0);
  if (savedWidth) applySidebarWidth(savedWidth);
} catch (_) { }

applyTheme(getPreferredTheme(), { persist: false });

// Show/hide scroll-to-bottom button based on scroll position.
els.messages.addEventListener("scroll", () => {
  const gap = els.messages.scrollHeight - els.messages.scrollTop - els.messages.clientHeight;
  scrollBtn.classList.toggle("hidden", gap < 200);
});
scrollBtn.addEventListener("click", () => {
  els.messages.scrollTo({ top: els.messages.scrollHeight, behavior: "smooth" });
});

function syncIntroMode(hasMessages) {
  if (!els.messages) return;
  els.messages.classList.toggle("intro-mode", !hasMessages);
  if (!hasMessages) {
    scrollBtn?.classList.add("hidden");
  }
}

function setStatus(kind, text) {
  els.statusDot.className = "dot";
  if (kind === "busy") els.statusDot.classList.add("busy");
  else if (kind === "err") els.statusDot.classList.add("err");
  els.statusText.textContent = text;
}

function setBusy(busy, sessionId = state.sessionId) {
  if (!sessionId) {
    els.btnSend.disabled = false;
    els.btnStop.disabled = true;
    els.input.disabled = false;
    setStatus("ok", "就绪");
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
  els.btnSend.disabled = currentBusy;
  els.btnStop.disabled = !currentBusy;
  els.input.disabled = currentBusy;
  if (currentBusy) {
    setStatus("busy", "当前会话运行中…");
    return;
  }
  if (state.runningSessions.size > 0) {
    setStatus("busy", `后台运行 ${state.runningSessions.size} 个会话`);
    if (agentStatus) agentStatus.set("busy", "后台会话运行中", `仍有 ${state.runningSessions.size} 个会话在后台处理中`);
    return;
  }
  setStatus("ok", "就绪");
  if (agentStatus) agentStatus.set("idle", "就绪", "等待你的指令");
}

function renderWelcomePanel() {
  if (!els.emptyHint) return;
  const caps = state.capabilities || {};
  const commands = Array.isArray(caps.commands) ? caps.commands : [];
  const tools = Array.isArray(caps.tools) ? caps.tools : [];
  const skills = Array.isArray(caps.skills) ? caps.skills : [];
  const commandHtml = commands.length
    ? commands.map((item) => {
      const name = escapeHtml(item.name || "");
      const desc = escapeHtml(item.desc || "");
      return `
          <details class="empty-item empty-item-command">
            <summary class="empty-item-summary">
              <span class="empty-item-name" title="${name}">${name}</span>
              <span class="empty-item-toggle" aria-hidden="true"></span>
            </summary>
            <div class="empty-item-body">
              <p class="empty-item-desc">${desc}</p>
              <button class="empty-item-action" data-cmd="${name}">立即发送</button>
            </div>
          </details>
        `;
    }).join("")
    : `<div class="empty-note">当前未返回命令列表</div>`;
  const toolHtml = tools.length
    ? tools.map((tool) => {
      const desc = escapeHtml(tool.description || "");
      return `
          <details class="empty-item empty-item-tool">
            <summary class="empty-item-summary">
              <span class="empty-item-name" title="${escapeHtml(tool.name || "")}">${escapeHtml(tool.name || "")}</span>
              <span class="empty-item-toggle" aria-hidden="true"></span>
            </summary>
            <div class="empty-item-body">
              <p class="empty-item-desc">${desc}</p>
            </div>
          </details>
        `;
    }).join("")
    : `<div class="empty-note">当前未返回工具列表</div>`;
  const skillHtml = skills.length
    ? skills.map((skill) => {
      const name = escapeHtml(skill?.name || "");
      const desc = escapeHtml(skill?.description || "当前技能未提供描述。");
      return `
          <details class="empty-item empty-item-skill">
            <summary class="empty-item-summary">
              <span class="empty-item-name empty-skill-copy" title="${name}" data-copy-skill="${name}" role="button" tabindex="0">${name}</span>
              <span class="empty-item-toggle" aria-hidden="true"></span>
            </summary>
            <div class="empty-item-body">
              <p class="empty-item-desc">${desc}</p>
            </div>
          </details>
        `;
    }).join("")
    : `<div class="empty-note">当前没有已加载技能</div>`;

  els.emptyHint.innerHTML = `
    <section class="empty-hero">
      <div class="empty-welcome">
        <div class="empty-badge">Pooh Code 工作台</div>
        <div class="empty-title">开始和 Pooh Code 对话</div>
        <div class="empty-sub">我可以在云端仓库写代码、改代码、跑命令、处理 Office 文件、分析图片与视频、调用技能，并在同一会话中持续推进任务。</div>
      </div>
      <div class="empty-hero-rail">
        <div class="empty-hero-chip"><span>Slash Commands</span><strong>${commands.length}</strong></div>
        <div class="empty-hero-chip"><span>Built-in Tools</span><strong>${tools.length}</strong></div>
        <div class="empty-hero-chip"><span>Loaded Skills</span><strong>${skills.length}</strong></div>
      </div>
    </section>
    <div class="empty-grid${Object.values(state.welcomeCardsCollapsed).some(Boolean) ? " compact-layout" : ""}">
      <section class="empty-card empty-card-commands${state.welcomeCardsCollapsed.commands ? " collapsed" : ""}" data-card="commands">
        <div class="empty-card-head">
          <span class="empty-card-title">Commands</span>
          <div class="empty-card-head-actions">
            <span class="empty-card-meta">${commands.length} 项</span>
            <button class="empty-card-toggle" type="button" data-card-toggle="commands">${state.welcomeCardsCollapsed.commands ? "展开" : "折叠"}</button>
          </div>
        </div>
        <div class="empty-card-sub">常用 slash commands。默认只展示名称，点开后可查看说明并直接发送。</div>
        <div class="empty-card-body">
          <div class="empty-command-list">${commandHtml}</div>
        </div>
      </section>
      <section class="empty-card empty-card-tools${state.welcomeCardsCollapsed.tools ? " collapsed" : ""}" data-card="tools">
        <div class="empty-card-head">
          <span class="empty-card-title">Tools</span>
          <div class="empty-card-head-actions">
            <span class="empty-card-meta">${tools.length} 项</span>
            <button class="empty-card-toggle" type="button" data-card-toggle="tools">${state.welcomeCardsCollapsed.tools ? "展开" : "折叠"}</button>
          </div>
        </div>
        <div class="empty-card-sub">当前模型可直接调用的内置工具。默认收起详情，需要时展开查看。</div>
        <div class="empty-card-body">
          <div class="empty-tool-grid">${toolHtml}</div>
        </div>
      </section>
      <section class="empty-card empty-card-skills${state.welcomeCardsCollapsed.skills ? " collapsed" : ""}" data-card="skills">
        <div class="empty-card-head">
          <span class="empty-card-title">Skills</span>
          <div class="empty-card-head-actions">
            <span class="empty-card-meta">${skills.length} 项</span>
            <button class="empty-card-toggle" type="button" data-card-toggle="skills">${state.welcomeCardsCollapsed.skills ? "展开" : "折叠"}</button>
          </div>
        </div>
        <div class="empty-card-sub">Skills 会按需加载完整工作流说明。默认只显示技能名，展开后查看用途描述。</div>
        <div class="empty-card-body">
          <div class="empty-skill-list">${skillHtml}</div>
        </div>
      </section>
    </div>
  `;
  els.emptyHint.querySelectorAll(".empty-item-action[data-cmd]").forEach((button) => {
    button.addEventListener("click", () => {
      sendMessage(button.dataset.cmd || "");
    });
  });
  els.emptyHint.querySelectorAll(".empty-card-body").forEach((container) => {
    enableDragScroll(container);
  });
  els.emptyHint.querySelectorAll("[data-copy-skill]").forEach((node) => {
    const copySkillName = async (e) => {
      e.preventDefault();
      e.stopPropagation();
      const text = node.getAttribute("data-copy-skill") || "";
      if (!text) return;
      try {
        await copyToClipboard(text);
        const original = node.textContent;
        node.textContent = "已复制";
        window.setTimeout(() => {
          node.textContent = original;
        }, 1200);
      } catch (_) { }
    };
    node.addEventListener("click", copySkillName);
    node.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") {
        copySkillName(e);
      }
    });
  });
  els.emptyHint.querySelectorAll(".empty-card-toggle[data-card-toggle]").forEach((button) => {
    button.addEventListener("click", () => {
      const card = button.dataset.cardToggle || "";
      if (!card) return;
      state.welcomeCardsCollapsed[card] = !state.welcomeCardsCollapsed[card];
      renderWelcomePanel();
    });
  });
}

function applyState(payload) {
  if (!payload) return;
  if (payload.session_id) {
    state.sessionId = payload.session_id;
    els.sessionId.textContent = payload.session_id;
  }
  if (typeof payload.running === "boolean" && payload.session_id) {
    setSessionRunning(payload.session_id, payload.running);
  }
  if (payload.session_key) state.sessionKey = payload.session_key;
  if (payload.model) {
    if (els.modelPill) els.modelPill.textContent = payload.model;
    if (els.modelLabel) els.modelLabel.textContent = payload.model;
  }
  if (payload.usage) {
    els.usageLabel.textContent = payload.usage.display || "—";
    if (els.contextPill) els.contextPill.textContent = payload.usage.display || "--/--";
  }
  if (payload.capabilities) {
    state.capabilities = payload.capabilities;
    renderWelcomePanel();
  }
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
  // Minimal inline: backticks -> <code>.
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
  } catch (_) { }
  return normalized;
}

if (typeof marked !== "undefined" && marked.setOptions) {
  marked.setOptions({
    gfm: true,
    breaks: true,
  });
}

function renderMarkdown(text) {
  if (typeof marked !== "undefined" && marked.parse) {
    try {
      return marked.parse(text);
    } catch (_) { }
  }
  return renderInline(text);
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
      const original = button.textContent;
      button.textContent = "已复制";
      button.classList.add("copied");
      window.setTimeout(() => {
        button.textContent = original;
        button.classList.remove("copied");
      }, 1200);
    } catch (_) {
      button.textContent = "复制失败";
      button.classList.add("copied");
      window.setTimeout(() => {
        button.textContent = "复制";
        button.classList.remove("copied");
      }, 1200);
    }
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
      } catch (_) { }
    }
  });
}

function createMessageShell(role, { navId = null } = {}) {
  const root = document.createElement("div");
  root.className = `msg ${role}`;
  if (navId) {
    root.setAttribute("data-nav-id", navId);
  }
  const roleLabel = role === "user" ? "YOU" : role === "assistant" ? "POOH" : "SYS";
  const canCopy = role === "user" || role === "assistant";
  root.innerHTML =
    `<div class="msg-meta">` +
    `<span class="role">${roleLabel}</span>` +
    `${canCopy ? '<button class="msg-copy" type="button" aria-label="复制消息">复制</button>' : ""}` +
    `</div>` +
    `<div class="body${role === "user" ? " rendered" : ""}"></div>`;
  const body = root.querySelector(".body");
  const copyBtn = root.querySelector(".msg-copy");
  if (copyBtn) {
    setCopyButtonState(copyBtn, "");
    attachCopyHandler(copyBtn);
  }
  return { root, body, copyBtn };
}

function appendMessage(role, text, { scroll = true } = {}) {
  syncIntroMode(true);
  const shell = createMessageShell(role, {
    navId: role === "user" ? `msg-${_msgIndex++}` : null,
  });
  if (role === "assistant" || role === "user") {
    const renderedText = role === "user" ? normalizeUserMarkdown(text) : text;
    shell.body.classList.add("rendered");
    shell.body.innerHTML = renderMarkdown(renderedText);
    enhanceRenderedContent(shell.body);
    setCopyButtonState(shell.copyBtn, text);
  } else {
    shell.body.innerHTML = renderInline(text);
  }
  els.messages.appendChild(shell.root);
  if (scroll) els.messages.scrollTop = els.messages.scrollHeight;
}

function clearMessages() {
  els.messages.innerHTML = "";
}

async function api(path, opts = {}) {
  const resp = await fetch(path, {
    method: opts.method || "GET",
    headers: opts.body ? { "Content-Type": "application/json" } : undefined,
    body: opts.body ? JSON.stringify(opts.body) : undefined,
  });
  const data = await resp.json().catch(() => ({ ok: false, error: "invalid json" }));
  if (!resp.ok || !data.ok) {
    throw new Error(data.error || `HTTP ${resp.status}`);
  }
  return data;
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
    // 检测文件下载
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
  // 在工具组后面追加下载按钮
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
    applyState(data);
    clearMessages();
    els.messages.appendChild(els.emptyHint || document.createElement("div"));
    syncIntroMode((data.messages || []).length > 0);
    for (const m of data.messages || []) {
      if (m.role === "assistant") {
        const shell = createMessageShell("assistant");
        let bodyHTML = "";
        if (m.tools && m.tools.length) {
          bodyHTML += buildToolGroupHTML(m.tools);
        }
        if (m.text && m.text.trim()) {
          bodyHTML += `<div class="stream-part">${renderMarkdown(m.text)}</div>`;
        }
        shell.body.classList.add("rendered");
        shell.body.innerHTML = bodyHTML || renderMarkdown("(empty response)");
        enhanceRenderedContent(shell.body);
        setCopyButtonState(shell.copyBtn, m.text || shell.body.textContent || "");
        els.messages.appendChild(shell.root);
      } else if (m.text && m.text.trim()) {
        appendMessage(m.role, m.text, { scroll: false });
      }
    }
    if ((data.messages || []).length > 0) {
      els.messages.scrollTop = els.messages.scrollHeight;
    }
    rebuildChatNav();
  } catch (err) {
    setStatus("err", `加载消息失败: ${err.message}`);
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

async function refreshSessions() {
  try {
    const data = await api("/api/sessions");
    applyState(data);
    const list = data.sessions || [];
    els.sessionList.innerHTML = "";

    let lastGroup = null;
    for (const item of list) {
      const group = _sessionDateLabel(item.last_active);
      if (group !== lastGroup) {
        lastGroup = group;
        const hdr = document.createElement("div");
        hdr.className = "session-date-group";
        hdr.textContent = group;
        els.sessionList.appendChild(hdr);
      }

      const displayLabel = item.label || item.session_id;
      const rawLabel = item.label || "";
      const row = document.createElement("div");
      row.className = "session-item" + (item.session_id === state.sessionId ? " active" : "");
      row.innerHTML =
        `<div class="session-item-main">` +
        `<span class="session-item-label">${escapeHtml(displayLabel)}</span>` +
        `<span class="session-item-id">${escapeHtml(item.session_id)}</span>` +
        `</div>` +
        `${item.running ? '<span class="session-item-run">运行中</span>' : ""}` +
        `<button class="session-item-del" title="删除会话">✕</button>`;
      const mainEl = row.querySelector(".session-item-main");
      let clickTimer = null;
      mainEl.addEventListener("click", (e) => {
        // 如果正在编辑则不触发切换
        if (row.querySelector(".session-rename-input")) return;
        if (clickTimer) { clearTimeout(clickTimer); clickTimer = null; return; }
        clickTimer = setTimeout(() => { clickTimer = null; switchSession(item.session_id); }, 250);
      });
      row.querySelector(".session-item-label").addEventListener("dblclick", (e) => {
        e.stopPropagation();
        if (clickTimer) { clearTimeout(clickTimer); clickTimer = null; }
        startRenameSession(row, item.session_id, rawLabel);
      });
      row.querySelector(".session-item-del").addEventListener("click", (e) => {
        e.stopPropagation();
        deleteSession(item.session_id);
      });
      els.sessionList.appendChild(row);
    }
  } catch (err) {
    setStatus("err", `加载会话失败: ${err.message}`);
  }
}

function startRenameSession(row, sessionId, currentLabel) {
  const labelEl = row.querySelector(".session-item-label");
  if (!labelEl || labelEl.querySelector("input")) return;

  const displayLabel = currentLabel || sessionId;
  const input = document.createElement("input");
  input.type = "text";
  input.className = "session-rename-input";
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
    await Promise.all([refreshSessions(), refreshFiles()]);
  } catch (err) {
    setStatus("err", `重命名失败: ${err.message}`);
  }
}

async function deleteSession(sessionId) {
  try {
    const data = await api("/api/session/delete", {
      method: "POST",
      body: { session_id: sessionId },
    });
    applyState(data);
    await Promise.all([refreshMessages(), refreshSessions(), refreshFiles()]);
    setStatus("ok", `已删除 ${sessionId}`);
  } catch (err) {
    setStatus("err", `删除失败: ${err.message}`);
  }
}

// ---------- streaming assistant bubble ----------
function createAssistantBubble() {
  const shell = createMessageShell("assistant");
  els.messages.appendChild(shell.root);
  els.messages.scrollTop = els.messages.scrollHeight;
  return {
    root: shell.root,
    body: shell.body,
    copyBtn: shell.copyBtn,
    currentText: null, // active text stream-part being appended to
    textParts: [],     // [{el, raw}] — accumulate raw text per segment for markdown rendering
    toolBlocks: {},    // call_id -> element
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

// ── 线性时间线：每次切换事件类型都会结束前一个"当前块" ──
function _endOtherBlocks(bubble, keep) {
  if (keep !== "text") bubble.currentText = null;
  if (keep !== "reasoning") bubble._currentReasoning = null;
  if (keep !== "tool") finalizeToolGroup(bubble);
}

function appendTextDelta(bubble, delta) {
  removeCursor(bubble);
  _endOtherBlocks(bubble, "text");
  if (!bubble.currentText) {
    const span = document.createElement("div");
    span.className = "stream-part";
    bubble.body.appendChild(span);
    bubble.currentText = span;
    bubble.textParts.push({ el: span, raw: "" });
  }
  bubble.textParts[bubble.textParts.length - 1].raw += delta;
  setCopyButtonState(
    bubble.copyBtn,
    bubble.textParts.map((part) => part.raw).join("\n\n"),
  );
  bubble.currentText.appendChild(document.createTextNode(delta));
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
  // 一个 reasoning part 结束 → 关闭当前块，下一次 delta 会新开一块
  bubble._currentReasoning = null;
}

function addToolBlock(bubble, { call_id, name }) {
  removeCursor(bubble);
  _endOtherBlocks(bubble, "tool");

  // Merge consecutive tool calls into one collapsible "thinking" group.
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
  // Remember both ids for matching the later tool_result.
  if (id) bubble.toolBlocks[id] = wrap;
  autoScrollIfNear();
}

function attachToolResult(bubble, { tool_use_id, name, content, is_error }) {
  let wrap = bubble.toolBlocks[tool_use_id];
  if (!wrap) {
    // tool_use_id from agent is `call_id|item_id`; try the call_id prefix.
    const callId = String(tool_use_id || "").split("|")[0];
    wrap = bubble.toolBlocks[callId];
  }
  if (!wrap) {
    // Fallback: create a fresh block so the user still sees the result.
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

  // 检测是否在 output/ 下生成了文件，自动添加下载按钮
  if (!is_error && content) {
    for (const outputPath of _extractOutputPaths(name, content)) {
      const dlBtn = createDownloadButton(outputPath);
      // 追加到气泡主体（不在折叠的 tool group 里），让用户更容易看到
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

// ---------- file download ----------
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
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function _formatTime(ts) {
  if (!ts) return "未知时间";
  const d = new Date(ts * 1000);
  if (isNaN(d)) return "未知时间";
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")} ${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}

/**
 * 从工具结果中提取 output/ 下的文件路径。
 */
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

function renderFileGroups(groups) {
  els.fileGroups.innerHTML = "";
  const items = groups || [];
  const totalFiles = items.reduce((sum, group) => sum + (group.file_count || 0), 0);
  els.filesSummary.textContent = `${items.length} 组 / ${totalFiles} 文件`;

  if (!items.length) {
    const empty = document.createElement("div");
    empty.className = "file-empty";
    empty.textContent = "还没有产物";
    els.fileGroups.appendChild(empty);
    return;
  }

  for (const group of items) {
    const wrap = document.createElement("div");
    const isCurrent = group.session_id === state.sessionId;
    wrap.className = "file-group" + (isCurrent ? " current" : "");

    const header = document.createElement("button");
    header.className = "file-group-head";
    header.type = "button";
    const groupLabel = group.label || group.session_id;
    header.innerHTML =
      `<span class="file-group-label">${escapeHtml(groupLabel)}</span>` +
      `<span class="file-group-session">${escapeHtml(group.session_id)}</span>` +
      `<span class="file-group-count">${group.file_count || 0} 文件</span>`;
    wrap.appendChild(header);

    const body = document.createElement("div");
    body.className = "file-group-body";

    const meta = document.createElement("div");
    meta.className = "file-group-meta";
    meta.textContent = `最近更新 ${_formatTime(group.latest_modified)}`;
    body.appendChild(meta);

    for (const file of group.files || []) {
      const row = document.createElement("a");
      row.className = "file-row downloadable";
      row.href = `/api/download?path=${encodeURIComponent(file.path)}`;
      row.target = "_blank";
      row.draggable = false;
      row.innerHTML =
        `<span class="file-row-icon">${_fileIcon(file.name)}</span>` +
        `<span class="file-row-main">` +
        `<span class="file-row-name">${escapeHtml(file.name)}</span>` +
        `<span class="file-row-path">${escapeHtml(file.relative_path || file.path)}</span>` +
        `</span>` +
        `<span class="file-row-side">` +
        `<span class="file-row-size">${_humanSize(file.size || 0)}</span>` +
        `<span class="file-row-tag">下载</span>` +
        `</span>`;
      body.appendChild(row);
    }

    wrap.appendChild(body);
    header.addEventListener("click", () => {
      wrap.classList.toggle("collapsed");
    });
    if (!isCurrent) wrap.classList.add("collapsed");
    els.fileGroups.appendChild(wrap);
  }
}

async function refreshFiles() {
  try {
    const data = await api("/api/files");
    applyState(data);
    renderFileGroups(data.groups || []);
  } catch (err) {
    els.filesSummary.textContent = "加载失败";
    els.fileGroups.innerHTML = `<div class="file-empty">产物列表加载失败: ${escapeHtml(err.message)}</div>`;
  }
}

async function streamChat(text, files = []) {
  const launchedSessionId = state.sessionId;
  const bubble = createAssistantBubble();
  ensureCursor(bubble);

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
        appendTextDelta(bubble, evt.text || "");
        agentStatus.set("streaming", "生成回复中", "模型正在输出最终回答…");
        break;
      case "reasoning_delta":
        appendReasoningDelta(bubble, evt.text || "");
        agentStatus.set("thinking", "思考中", "模型正在进行推理（reasoning）…");
        break;
      case "reasoning_part_added":
        startReasoningPart(bubble);
        agentStatus.set("thinking", "思考中", "开始新的推理片段…");
        break;
      case "reasoning_part_done":
        break;
      case "tool_use_started":
        addToolBlock(bubble, { call_id: evt.call_id, name: evt.name });
        agentStatus.set("tool", `调用工具: ${evt.name || "unknown"}`, "模型正在构造工具调用参数…");
        break;
      case "tool_use_done":
        finalizeToolInput(bubble, evt);
        agentStatus.set("tool", `执行工具: ${evt.name || "unknown"}`, "等待工具返回结果…");
        break;
      case "tool_result":
        attachToolResult(bubble, evt);
        agentStatus.set("busy", "工具已返回", "继续交由模型处理结果…");
        break;
      case "turn_start":
        agentStatus.set("busy", `第 ${evt.turn || 1} 轮`, "开始新一轮 LLM 推理…");
        // subtle divider between turns
        if (evt.turn && evt.turn > 1) {
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
        agentStatus.set("busy", "上下文已压缩", `autocompact → ${evt.display || ""}`);
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
        agentStatus.set("idle", "完成", "回答已返回");
        removeCursor(bubble);
        finalizeToolGroup(bubble);
        // 把每段原始文本用 markdown 渲染替换
        for (const part of bubble.textParts) {
          const trimmed = part.raw.trim();
          if (trimmed) {
            part.el.innerHTML = renderMarkdown(trimmed);
            enhanceRenderedContent(part.el);
          }
        }
        bubble.body.classList.add("rendered");
        if (!bubble.body.textContent.trim()) {
          bubble.body.innerHTML = renderMarkdown(evt.text || "(empty response)");
          enhanceRenderedContent(bubble.body);
        }
        setCopyButtonState(
          bubble.copyBtn,
          bubble.textParts.map((part) => part.raw).join("\n\n") || evt.text || "",
        );
        // 将累积的下载按钮追加到气泡末尾
        if (bubble._pendingDownloads && bubble._pendingDownloads.length) {
          const dlContainer = document.createElement("div");
          dlContainer.className = "stream-part";
          dlContainer.style.display = "flex";
          dlContainer.style.flexWrap = "wrap";
          dlContainer.style.gap = "8px";
          for (const btn of bubble._pendingDownloads) {
            dlContainer.appendChild(btn);
          }
          bubble.body.appendChild(dlContainer);
        }
        if (evt.session_id && state.sessionId === launchedSessionId) {
          state.sessionId = evt.session_id;
          els.sessionId.textContent = evt.session_id;
        }
        finished = true;
        break;
      case "state":
        applyState(evt);
        break;
      case "error":
        setSessionRunning(launchedSessionId, false);
        agentStatus.set("error", "发生错误", evt.error || "未知错误");
        removeCursor(bubble);
        if (state.sessionId === launchedSessionId) {
          appendMessage("system", `请求失败: ${evt.error || "unknown"}`);
          setStatus("err", evt.error || "error");
        }
        break;
    }
  };

  try {
    while (!finished) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      // Parse SSE frames separated by blank line.
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
        if (raw === "[DONE]") {
          finished = true;
          continue;
        }
        try {
          handle(JSON.parse(raw));
        } catch (_) {
          // ignore malformed frame
        }
        if (finished) break;
      }
    }
  } finally {
    // 主动 cancel 释放底层 socket，不再等待服务端关闭连接。
    try { await reader.cancel(); } catch (_) { }
    removeCursor(bubble);
    // 即便流提前结束（未收到 done 事件）也要把"思考中"落定为"已思考"，并渲染已收到的文本。
    finalizeToolGroup(bubble);
    if (!finished) {
      for (const part of bubble.textParts) {
        const trimmed = part.raw.trim();
        if (trimmed) {
          part.el.innerHTML = renderMarkdown(trimmed);
          enhanceRenderedContent(part.el);
        }
      }
      bubble.body.classList.add("rendered");
      setSessionRunning(launchedSessionId, false);
      agentStatus.set("idle", "连接已结束", "流式响应提前终止，已显示已接收的内容");
    }
  }
}

async function sendMessage(text) {
  if (!text.trim() && !state.pendingFiles.length) return;
  const launchedSessionId = state.sessionId;
  if (launchedSessionId && state.runningSessions.has(launchedSessionId)) return;

  // 收集附件路径并清空
  const filePaths = state.pendingFiles.map((f) => f.serverPath);
  const fileNames = state.pendingFiles.map((f) => f.name);
  state.pendingFiles = [];
  renderFilePreview();

  // Slash commands: run through /api/command and surface the output.
  if (text.startsWith("/")) {
    setBusy(true, launchedSessionId);
    agentStatus.set("busy", `执行命令 ${text}`, "调用后端命令处理器…");
    try {
      const data = await api("/api/command", {
        method: "POST",
        body: { text, session_id: launchedSessionId },
      });
      data.session_id = data.session_id || launchedSessionId;
      applyState(data);
      // /clear /new /switch 会改写 transcript，先刷新历史避免重复。
      await refreshMessages();
      appendMessage("system", `> ${text}`);
      if (data.text && data.text !== "__EXIT__") {
        appendMessage("system", data.text);
      }
      await Promise.all([refreshSessions(), refreshFiles()]);
      agentStatus.set("idle", "命令完成", `${text} 已执行`);
    } catch (err) {
      const msg = err.message || "unknown";
      const isRunning = /session is running|running/i.test(msg);
      appendMessage("system", `命令错误: ${msg}`);
      setStatus("err", msg);
      agentStatus.set(
        "error",
        isRunning ? `无法执行 ${text}` : `命令失败`,
        isRunning
          ? "当前会话仍在运行中。请先点击「停止」或等待本轮完成后再执行命令。"
          : msg,
      );
    } finally {
      setBusy(false, launchedSessionId);
    }
    return;
  }

  const displayText = fileNames.length
    ? text + "\n" + fileNames.map((n) => `[${_fileIcon(n)} ${n}]`).join(" ")
    : text;
  appendMessage("user", displayText);
  rebuildChatNav();
  setSessionRunning(launchedSessionId, true);
  agentStatus.set("busy", "已提交消息", "正在建立到 Agent 的流式连接…");
  try {
    await streamChat(text, filePaths);
    await Promise.all([refreshSessions(), refreshFiles()]);
  } catch (err) {
    appendMessage("system", `请求失败: ${err.message}`);
    setStatus("err", err.message);
    agentStatus.set("error", "请求失败", err.message || "unknown");
  } finally {
    setSessionRunning(launchedSessionId, false);
  }
}

async function newSession() {
  try {
    const data = await api("/api/session/new", { method: "POST" });
    applyState(data);
    await Promise.all([refreshMessages(), refreshSessions(), refreshFiles()]);
    setStatus("ok", `新会话 ${data.session_id}`);
  } catch (err) {
    setStatus("err", err.message);
  }
}

async function switchSession(prefix) {
  try {
    const data = await api("/api/session/switch", {
      method: "POST",
      body: { session_id_prefix: prefix, session_id: state.sessionId },
    });
    applyState(data);
    await Promise.all([refreshMessages(), refreshSessions(), refreshFiles()]);
  } catch (err) {
    setStatus("err", err.message);
  }
}

// ---------- chat nav ----------
const chatNavList = document.getElementById("chat-nav-list");

function rebuildChatNav() {
  chatNavList.innerHTML = "";
  const userMsgs = els.messages.querySelectorAll('.msg.user[data-nav-id]');
  userMsgs.forEach((el, i) => {
    const rawText = el.querySelector(".body")?.textContent?.trim() || `消息 ${i + 1}`;
    const truncated = rawText.length > 24 ? rawText.slice(0, 24) + "…" : rawText;
    const btn = document.createElement("button");
    btn.className = "chat-nav-item";
    btn.innerHTML = `<span class="nav-text">${escapeHtml(truncated)}</span><span class="nav-indicator"></span>`;
    btn.addEventListener("click", () => {
      el.scrollIntoView({ behavior: "smooth", block: "center" });
      // Highlight briefly.
      el.style.outline = "2px solid var(--accent)";
      setTimeout(() => { el.style.outline = ""; }, 1200);
    });
    chatNavList.appendChild(btn);
  });
  updateChatNavActive();
}

function updateChatNavActive() {
  const userMsgs = els.messages.querySelectorAll('.msg.user[data-nav-id]');
  const navItems = chatNavList.querySelectorAll('.chat-nav-item');
  if (!userMsgs.length || !navItems.length) return;

  const containerRect = els.messages.getBoundingClientRect();
  const containerMid = containerRect.top + containerRect.height / 2;
  let closestIdx = 0;
  let closestDist = Infinity;
  userMsgs.forEach((el, i) => {
    const rect = el.getBoundingClientRect();
    const dist = Math.abs(rect.top + rect.height / 2 - containerMid);
    if (dist < closestDist) {
      closestDist = dist;
      closestIdx = i;
    }
  });
  navItems.forEach((n, i) => n.classList.toggle("active", i === closestIdx));
}

els.messages.addEventListener("scroll", updateChatNavActive);

// ---------- file upload ----------
function renderFilePreview() {
  els.filePreviewBar.innerHTML = "";
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
    removeBtn.textContent = "\u00d7";
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
  return data.files; // [{path, name, size}]
}

async function addFiles(fileList) {
  if (!fileList || !fileList.length) return;
  // 先上传到服务器
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

els.btnAttach.addEventListener("click", () => els.fileInput.click());
els.fileInput.addEventListener("change", () => {
  if (els.fileInput.files.length) {
    addFiles(Array.from(els.fileInput.files));
    els.fileInput.value = "";
  }
});

// 拖放支持
els.composer.addEventListener("dragover", (e) => {
  e.preventDefault();
  els.composer.classList.add("drag-over");
});
els.composer.addEventListener("dragleave", () => {
  els.composer.classList.remove("drag-over");
});
els.composer.addEventListener("drop", (e) => {
  e.preventDefault();
  els.composer.classList.remove("drag-over");
  if (e.dataTransfer.files.length) {
    addFiles(Array.from(e.dataTransfer.files));
  }
});

// ---------- events ----------
els.composer.addEventListener("submit", (e) => {
  e.preventDefault();
  const text = els.input.value;
  els.input.value = "";
  autosize();
  sendMessage(text);
});

els.input.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey && !e.isComposing) {
    e.preventDefault();
    els.composer.requestSubmit();
  }
});

function autosize() {
  els.input.style.height = "auto";
  els.input.style.height = Math.min(els.input.scrollHeight, 240) + "px";
}
els.input.addEventListener("input", autosize);

els.btnNew.addEventListener("click", newSession);
els.btnRefresh.addEventListener("click", () => {
  refreshMessages();
  refreshSessions();
  refreshFiles();
});

els.btnStop.addEventListener("click", async () => {
  if (!state.sessionId || !state.runningSessions.has(state.sessionId)) return;
  try {
    const data = await api("/api/session/cancel", {
      method: "POST",
      body: { session_id: state.sessionId },
    });
    applyState(data);
    appendMessage("system", "已发送取消请求。");
  } catch (err) {
    setStatus("err", `取消失败: ${err.message}`);
  }
});

els.sidebarResizer.addEventListener("pointerdown", (e) => {
  if (document.body.classList.contains("sidebar-collapsed")) return;
  e.preventDefault();
  const startX = e.clientX;
  const startWidth = parseInt(getComputedStyle(document.documentElement).getPropertyValue("--sidebar-width"), 10) || SIDEBAR_MIN;
  const onMove = (evt) => {
    applySidebarWidth(startWidth + (evt.clientX - startX));
  };
  const onUp = () => {
    window.removeEventListener("pointermove", onMove);
    window.removeEventListener("pointerup", onUp);
  };
  window.addEventListener("pointermove", onMove);
  window.addEventListener("pointerup", onUp);
});

document.getElementById("sidebar-toggle").addEventListener("click", () => {
  document.body.classList.toggle("sidebar-collapsed");
});

document.getElementById("nav-toggle").addEventListener("click", () => {
  const nav = document.getElementById("chat-nav");
  nav.classList.toggle("collapsed");
  const btn = document.getElementById("nav-toggle");
  btn.textContent = nav.classList.contains("collapsed") ? "‹" : "›";
});

els.themeToggle?.addEventListener("click", () => {
  const nextTheme = document.body.classList.contains("theme-dark") ? "light" : "dark";
  applyTheme(nextTheme);
});

document.querySelectorAll(".chip[data-cmd]").forEach((chip) => {
  chip.addEventListener("click", () => {
    sendMessage(chip.dataset.cmd);
  });
});

// ---------- boot ----------
(async () => {
  setStatus("ok", "连接中…");
  try {
    const data = await api("/api/state");
    applyState(data);
  } catch (err) {
    setStatus("err", err.message);
    return;
  }
  await Promise.all([refreshMessages(), refreshSessions(), refreshFiles()]);
  setStatus("ok", "就绪");
  els.input.focus();
})();
