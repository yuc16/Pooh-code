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
  modelLabel: $("#model-label"),
  statusDot: $("#status-dot"),
  statusText: $("#status-text"),
};

const scrollBtn = document.getElementById("scroll-btn");

let state = {
  sessionId: null,
  sessionKey: null,
  runningSessions: new Set(),
  pendingFiles: [], // [{file: File, serverPath: string, name: string}]
};

const SIDEBAR_WIDTH_KEY = "pooh.sidebar.width";
const SIDEBAR_MIN = 220;
const SIDEBAR_MAX = 520;

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
    if (e.target.closest("button, input, textarea, select, label")) return;
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
  } catch (_) {}
}

try {
  const savedWidth = Number(localStorage.getItem(SIDEBAR_WIDTH_KEY) || 0);
  if (savedWidth) applySidebarWidth(savedWidth);
} catch (_) {}

// Show/hide scroll-to-bottom button based on scroll position.
els.messages.addEventListener("scroll", () => {
  const gap = els.messages.scrollHeight - els.messages.scrollTop - els.messages.clientHeight;
  scrollBtn.classList.toggle("hidden", gap < 200);
});
scrollBtn.addEventListener("click", () => {
  els.messages.scrollTo({ top: els.messages.scrollHeight, behavior: "smooth" });
});

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
    return;
  }
  setStatus("ok", "就绪");
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
    els.modelPill.textContent = payload.model;
    els.modelLabel.textContent = payload.model;
  }
  if (payload.usage) {
    els.usageLabel.textContent = payload.usage.display || "—";
    els.contextPill.textContent = payload.usage.display || "--/--";
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

function renderMarkdown(text) {
  if (typeof marked !== "undefined" && marked.parse) {
    try {
      return marked.parse(text);
    } catch (_) {}
  }
  return renderInline(text);
}

function hideEmptyHint() {
  if (els.emptyHint && els.emptyHint.parentNode) {
    els.emptyHint.remove();
  }
}

let _msgIndex = 0;

function appendMessage(role, text, { scroll = true } = {}) {
  hideEmptyHint();
  const div = document.createElement("div");
  div.className = `msg ${role}`;
  const roleLabel = role === "user" ? "YOU" : role === "assistant" ? "POOH" : "SYS";
  if (role === "assistant") {
    div.innerHTML = `<span class="role">${roleLabel}</span><div class="body rendered">${renderMarkdown(text)}</div>`;
  } else {
    div.innerHTML = `<span class="role">${roleLabel}</span><div class="body">${renderInline(text)}</div>`;
  }
  if (role === "user") {
    div.setAttribute("data-nav-id", `msg-${_msgIndex++}`);
  }
  els.messages.appendChild(div);
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
    if (!data.messages || data.messages.length === 0) {
      els.messages.appendChild(els.emptyHint || document.createElement("div"));
    } else {
      for (const m of data.messages) {
        if (m.role === "assistant") {
          hideEmptyHint();
          const div = document.createElement("div");
          div.className = "msg assistant";
          let bodyHTML = "";
          if (m.tools && m.tools.length) {
            bodyHTML += buildToolGroupHTML(m.tools);
          }
          if (m.text && m.text.trim()) {
            bodyHTML += `<div class="stream-part">${renderMarkdown(m.text)}</div>`;
          }
          div.innerHTML = `<span class="role">POOH</span><div class="body rendered">${bodyHTML || "(empty response)"}</div>`;
          els.messages.appendChild(div);
        } else if (m.text && m.text.trim()) {
          appendMessage(m.role, m.text, { scroll: false });
        }
      }
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
  hideEmptyHint();
  const div = document.createElement("div");
  div.className = "msg assistant";
  div.innerHTML = `<span class="role">POOH</span><div class="body"></div>`;
  els.messages.appendChild(div);
  els.messages.scrollTop = els.messages.scrollHeight;
  return {
    root: div,
    body: div.querySelector(".body"),
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
    group.querySelector(".thinking-label").textContent = `已思考`;
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
        <span class="thinking-label">思考中…</span>
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
    switch (evt.type) {
      case "text_delta":
        appendTextDelta(bubble, evt.text || "");
        break;
      case "reasoning_delta":
        appendReasoningDelta(bubble, evt.text || "");
        break;
      case "reasoning_part_added":
        startReasoningPart(bubble);
        break;
      case "reasoning_part_done":
        break;
      case "tool_use_started":
        addToolBlock(bubble, { call_id: evt.call_id, name: evt.name });
        break;
      case "tool_use_done":
        finalizeToolInput(bubble, evt);
        break;
      case "tool_result":
        attachToolResult(bubble, evt);
        break;
      case "turn_start":
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
        if (state.sessionId === launchedSessionId) {
          appendMessage("system", `[autocompact -> ${evt.display || ""}]`);
        }
        break;
      case "truncated":
        if (state.sessionId === launchedSessionId) {
          appendMessage(
            "system",
            `⚠️ 已达到 max_turns=${evt.max_turns} 上限,任务被截断。再发一条消息可让我继续。`,
          );
        }
        break;
      case "cancelled":
        setSessionRunning(launchedSessionId, false);
        if (state.sessionId === launchedSessionId) {
          appendMessage("system", "当前会话已请求取消。");
        }
        break;
      case "done":
        setSessionRunning(launchedSessionId, false);
        removeCursor(bubble);
        finalizeToolGroup(bubble);
        // 把每段原始文本用 markdown 渲染替换
        for (const part of bubble.textParts) {
          const trimmed = part.raw.trim();
          if (trimmed) {
            part.el.innerHTML = renderMarkdown(trimmed);
          }
        }
        bubble.body.classList.add("rendered");
        if (!bubble.body.textContent.trim()) {
          bubble.body.innerHTML = renderMarkdown(evt.text || "(empty response)");
        }
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
    try { await reader.cancel(); } catch (_) {}
    removeCursor(bubble);
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
    } catch (err) {
      appendMessage("system", `命令错误: ${err.message}`);
      setStatus("err", err.message);
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
  try {
    await streamChat(text, filePaths);
    await Promise.all([refreshSessions(), refreshFiles()]);
  } catch (err) {
    appendMessage("system", `请求失败: ${err.message}`);
    setStatus("err", err.message);
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
