// Pooh Code frontend — vanilla JS, no build step.

const $ = (sel) => document.querySelector(sel);

const els = {
  messages: $("#messages"),
  emptyHint: $("#empty-hint"),
  input: $("#input"),
  composer: $("#composer"),
  btnSend: $("#btn-send"),
  btnNew: $("#btn-new"),
  btnRefresh: $("#btn-refresh"),
  sessionList: $("#session-list"),
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
  busy: false,
  sessionId: null,
  sessionKey: null,
};

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

function setBusy(busy) {
  state.busy = busy;
  els.btnSend.disabled = busy;
  els.input.disabled = busy;
  if (busy) setStatus("busy", "思考中…");
  else setStatus("ok", "就绪");
}

function applyState(payload) {
  if (!payload) return;
  if (payload.session_id) {
    state.sessionId = payload.session_id;
    els.sessionId.textContent = payload.session_id;
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
  const items = tools.map((t) => {
    const inputJson = escapeHtml(JSON.stringify(t.input || {}, null, 2));
    const resultText = escapeHtml(t.result || "");
    const errClass = t.is_error ? " error" : "";
    const statusLabel = t.is_error ? "失败" : "完成";
    const resultLabel = t.is_error ? "ERROR" : "OUTPUT";
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
  return `<div class="thinking-group stream-part collapsed">
    <div class="thinking-head" onclick="this.parentElement.classList.toggle('collapsed')">
      <span class="thinking-icon">⊙</span>
      <span class="thinking-label">已思考</span>
      <span class="thinking-count"> · ${tools.length} 个工具调用</span>
      <span class="caret">▾</span>
    </div>
    <div class="thinking-body">${items}</div>
  </div>`;
}

async function refreshMessages() {
  try {
    const data = await api("/api/messages");
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

async function refreshSessions() {
  try {
    const data = await api("/api/sessions");
    applyState(data);
    const list = data.sessions || [];
    els.sessionList.innerHTML = "";
    for (const item of list) {
      const li = document.createElement("li");
      if (item.active) li.classList.add("active");
      const label = item.label ? escapeHtml(item.label) : "";
      li.innerHTML = `
        <div class="session-row">
          <div class="session-info">
            ${label ? `<div class="session-label">${label}</div>` : ""}
            <div class="session-id">${escapeHtml(item.session_id)}${item.active ? " ·当前" : ""}</div>
            <div class="session-meta">msgs=${item.message_count}</div>
          </div>
          <button class="session-del" title="删除会话" aria-label="删除会话">✕</button>
        </div>
      `;
      li.querySelector(".session-info").addEventListener("click", () => switchSession(item.session_id));
      li.querySelector(".session-del").addEventListener("click", (e) => {
        e.stopPropagation();
        deleteSession(item.session_id);
      });
      els.sessionList.appendChild(li);
    }
  } catch (err) {
    setStatus("err", `加载会话失败: ${err.message}`);
  }
}

async function deleteSession(sessionId) {
  const ok = confirm(`确定删除会话 ${sessionId} 吗？\n对应的 transcript 文件会被一并删除，此操作不可撤销。`);
  if (!ok) return;
  try {
    const data = await api("/api/session/delete", {
      method: "POST",
      body: { session_id: sessionId },
    });
    applyState(data);
    await Promise.all([refreshMessages(), refreshSessions()]);
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
  autoScrollIfNear();
}

function autoScrollIfNear() {
  const el = els.messages;
  const nearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 160;
  if (nearBottom) el.scrollTop = el.scrollHeight;
}

async function streamChat(text) {
  const bubble = createAssistantBubble();
  ensureCursor(bubble);

  const resp = await fetch("/api/chat/stream", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text }),
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
        appendMessage("system", `[autocompact -> ${evt.display || ""}]`);
        break;
      case "done":
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
        if (evt.session_id) {
          state.sessionId = evt.session_id;
          els.sessionId.textContent = evt.session_id;
        }
        finished = true;
        break;
      case "state":
        applyState(evt);
        break;
      case "error":
        removeCursor(bubble);
        appendMessage("system", `请求失败: ${evt.error || "unknown"}`);
        setStatus("err", evt.error || "error");
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
  if (!text.trim() || state.busy) return;

  // Slash commands: run through /api/command and surface the output.
  if (text.startsWith("/")) {
    setBusy(true);
    try {
      const data = await api("/api/command", { method: "POST", body: { text } });
      applyState(data);
      // /clear /new /switch 会改写 transcript，先刷新历史避免重复。
      await refreshMessages();
      appendMessage("system", `> ${text}`);
      if (data.text && data.text !== "__EXIT__") {
        appendMessage("system", data.text);
      }
      await refreshSessions();
    } catch (err) {
      appendMessage("system", `命令错误: ${err.message}`);
      setStatus("err", err.message);
    } finally {
      setBusy(false);
    }
    return;
  }

  appendMessage("user", text);
  rebuildChatNav();
  setBusy(true);
  try {
    await streamChat(text);
    refreshSessions();
  } catch (err) {
    appendMessage("system", `请求失败: ${err.message}`);
    setStatus("err", err.message);
  } finally {
    setBusy(false);
  }
}

async function newSession() {
  try {
    const data = await api("/api/session/new", { method: "POST" });
    applyState(data);
    await Promise.all([refreshMessages(), refreshSessions()]);
    setStatus("ok", `新会话 ${data.session_id}`);
  } catch (err) {
    setStatus("err", err.message);
  }
}

async function switchSession(prefix) {
  try {
    const data = await api("/api/session/switch", {
      method: "POST",
      body: { session_id_prefix: prefix },
    });
    applyState(data);
    await Promise.all([refreshMessages(), refreshSessions()]);
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
  await Promise.all([refreshMessages(), refreshSessions()]);
  setStatus("ok", "就绪");
  els.input.focus();
})();
