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
  btnImageMode: $("#btn-image-mode"),
  aspectSelect: $("#image-aspect-ratio"),
  aspectWrap: $("#image-aspect-wrap"),
  imageModelSelect: $("#image-model"),
  imageModelWrap: $("#model-switcher"),
  resolutionSelect: $("#image-resolution"),
  resolutionWrap: $("#image-resolution-wrap"),
  referenceBar: $("#image-reference-bar"),
  referenceName: $("#image-reference-name"),
  referenceClear: $("#image-reference-clear"),
  confirmDialog: $("#confirm-dialog"),
  confirmDialogTitle: $("#confirm-dialog-title"),
  confirmDialogBody: $("#confirm-dialog-body"),
  confirmDialogOk: $("#confirm-dialog-ok"),
  confirmDialogCancel: $("#confirm-dialog-cancel"),
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
  replyCtx: $("#reply-ctx"),
  replyCtxText: $("#reply-ctx-text"),
  replyCtxClear: $("#reply-ctx-clear"),
  scrollBtn: $("#scroll-btn"),
  colDividerLeft: $("#col-divider-left"),
  colDividerRight: $("#col-divider-right"),
  btnCollapseLeft: $("#btn-collapse-left"),
  btnCollapseRight: $("#btn-collapse-right"),
  btnExpandLeft: $("#btn-expand-left"),
  btnExpandRight: $("#btn-expand-right"),
  minimap: $("#minimap"),
  mmInner: $("#minimap-inner"),
  mmCanvas: $("#mm-canvas"),
  mmViewport: $("#mm-viewport"),
  btnMinimapJump: $("#btn-minimap-jump"),
  imageLightbox: $("#image-lightbox"),
  imageLightboxDialog: $("#image-lightbox-dialog"),
  imageLightboxImg: $("#image-lightbox-img"),
  imageLightboxName: $("#image-lightbox-name"),
  imageLightboxClose: $("#image-lightbox-close"),
  selectionQuote: $("#selection-quote"),
  selectionQuoteBtn: $("#selection-quote-btn"),
};

// ─── Agent status banner ───
const agentStatus = (() => {
  let level = "idle";
  let startTs = 0;
  let timerHandle = null;
  let lastActivity = 0;
  let baseDetail = "";

  function render() {
    if (!els.agentStatus) return;
    els.agentStatus.dataset.level = level;
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
    set("idle", "就绪", "等待你的指令");
  }

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
  sessionViewCache: new Map(),
  sessionMessageSignatures: new Map(),
  openConvos: new Set(),
  sessionFilter: "",
  replyCtx: null, // { who, text }
  selectionQuote: null,
  selectionDragging: false,
  agentModel: "—",
  imageModel: "gemini-3.1-flash-image-preview-free",
  imageModels: [],
  imageCapabilities: {},
  imageResolution: "1k",
  imageReference: null,
  imageAspectRatio: "1:1",
  imageMode: false,
  imageGenerating: false,
  toolSchemas: {},
};

const COLS_KEY = "pooh.cols.v1";
const COLLAPSE_KEY = "pooh.collapse.v1";

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
  const leftCollapsed = els.app?.classList.contains("left-collapsed");
  const leftW = leftCollapsed ? 0 : els.leftPane.getBoundingClientRect().width;
  const midW = els.middlePane.getBoundingClientRect().width;
  els.colDividerLeft.style.left = `${leftW}px`;
  els.colDividerRight.style.left = `${leftW + midW}px`;
}

function setPaneCollapsed(side, collapsed, persist = true) {
  if (!els.app) return;
  const cls = side === "left" ? "left-collapsed" : "right-collapsed";
  els.app.classList.toggle(cls, !!collapsed);
  if (persist) {
    try {
      localStorage.setItem(
        COLLAPSE_KEY,
        JSON.stringify({
          left: els.app.classList.contains("left-collapsed"),
          right: els.app.classList.contains("right-collapsed"),
        }),
      );
    } catch (_) {}
  }
  positionDividers();
  scheduleMinimapRebuild();
}

function togglePaneCollapsed(side) {
  const cls = side === "left" ? "left-collapsed" : "right-collapsed";
  const currently = !!els.app?.classList.contains(cls);
  setPaneCollapsed(side, !currently);
}

function loadCollapse() {
  try {
    const raw = localStorage.getItem(COLLAPSE_KEY);
    if (!raw) return;
    const parsed = JSON.parse(raw);
    if (parsed && typeof parsed === "object") {
      setPaneCollapsed("left", !!parsed.left, false);
      setPaneCollapsed("right", !!parsed.right, false);
    }
  } catch (_) {}
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

function refreshDisplayedModel() {
  if (!els.modelLabel) return;
  const label = state.imageMode ? (state.imageModel || "图片生成") : (state.agentModel || "—");
  els.modelLabel.textContent = label;
  els.modelBadge?.classList.toggle("image-mode", !!state.imageMode);
}

function refreshComposerPlaceholder() {
  const currentBusy = !!(state.sessionId && state.runningSessions.has(state.sessionId));
  if (!els.input) return;
  if (state.imageGenerating) {
    els.input.placeholder = "图片生成中，请稍候…";
    return;
  }
  if (currentBusy) {
    els.input.placeholder = "继续发送消息，Agent 将在下一轮看到…";
    return;
  }
  els.input.placeholder = state.imageMode
    ? "描述你想生成的图片…"
    : "继续这段对话，或者拖拽文件到这里…";
}

const FALLBACK_RATIOS = ["1:1", "2:3", "3:2", "3:4", "4:3", "4:5", "5:4", "9:16", "16:9", "21:9"];

function _currentCaps() {
  const caps = state.imageCapabilities?.[state.imageModel];
  return caps && typeof caps === "object" ? caps : null;
}

function _ratiosForCurrentModel() {
  const caps = _currentCaps();
  if (caps?.ratios?.length) return caps.ratios;
  return FALLBACK_RATIOS;
}

function _resolutionsForCurrentModel() {
  const caps = _currentCaps();
  return Array.isArray(caps?.resolutions) ? caps.resolutions : [];
}

function _modelSupportsReference() {
  return !!_currentCaps()?.supports_reference;
}

function rebuildAspectOptions() {
  if (!els.aspectSelect) return;
  const ratios = _ratiosForCurrentModel();
  els.aspectSelect.innerHTML = "";
  for (const ratio of ratios) {
    const opt = document.createElement("option");
    opt.value = ratio;
    opt.textContent = ratio;
    els.aspectSelect.appendChild(opt);
  }
}

function syncAspectSelect() {
  if (!els.aspectSelect) return;
  rebuildAspectOptions();
  const ratios = _ratiosForCurrentModel();
  let value = ratios.includes(state.imageAspectRatio) ? state.imageAspectRatio : ratios[0] || "1:1";
  if (els.aspectSelect.value !== value) els.aspectSelect.value = value;
  state.imageAspectRatio = value;
}

function rebuildResolutionOptions() {
  if (!els.resolutionSelect) return;
  const list = _resolutionsForCurrentModel();
  els.resolutionSelect.innerHTML = "";
  for (const r of list) {
    const opt = document.createElement("option");
    opt.value = r;
    opt.textContent = r;
    els.resolutionSelect.appendChild(opt);
  }
}

function syncResolutionSelect() {
  if (!els.resolutionSelect) return;
  rebuildResolutionOptions();
  const list = _resolutionsForCurrentModel();
  if (!list.length) return;
  const value = list.includes(state.imageResolution) ? state.imageResolution : list[0];
  if (els.resolutionSelect.value !== value) els.resolutionSelect.value = value;
  state.imageResolution = value;
}

function rebuildImageModelOptions() {
  if (!els.imageModelSelect) return;
  const models = (state.imageModels || []).filter((name) => typeof name === "string" && name);
  if (!models.length && state.imageModel) models.push(state.imageModel);
  els.imageModelSelect.innerHTML = "";
  for (const name of models) {
    const opt = document.createElement("option");
    opt.value = name;
    opt.textContent = name;
    els.imageModelSelect.appendChild(opt);
  }
}

function syncImageModelSelect() {
  if (!els.imageModelSelect) return;
  rebuildImageModelOptions();
  const options = Array.from(els.imageModelSelect.options).map((opt) => opt.value);
  const value = options.includes(state.imageModel) ? state.imageModel : options[0] || "";
  if (value) {
    if (els.imageModelSelect.value !== value) els.imageModelSelect.value = value;
    state.imageModel = value;
  }
}

const IMAGE_PREF_PREFIX = "pooh.image.";

function _imagePrefKey(sessionId) {
  return sessionId ? `${IMAGE_PREF_PREFIX}${sessionId}` : null;
}

function loadSessionImagePrefs(sessionId) {
  const key = _imagePrefKey(sessionId);
  if (!key) return null;
  try {
    const raw = localStorage.getItem(key);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    return typeof parsed === "object" && parsed ? parsed : null;
  } catch {
    return null;
  }
}

function saveSessionImagePrefs() {
  const key = _imagePrefKey(state.sessionId);
  if (!key) return;
  const payload = {
    model: state.imageModel || null,
    aspect: state.imageAspectRatio || null,
    resolution: state.imageResolution || null,
    reference: state.imageReference || null,
  };
  try {
    localStorage.setItem(key, JSON.stringify(payload));
  } catch {
    // localStorage 配额满或被禁用就静默跳过；下次还可以兜底用服务端默认
  }
}

function clearImageReference() {
  state.imageReference = null;
  refreshReferenceBar();
  saveSessionImagePrefs();
}

function openConfirmDialog({ title = "提示", body = [], confirmText = "确认", cancelText = "取消" } = {}) {
  return new Promise((resolve) => {
    if (!els.confirmDialog || !els.confirmDialogOk || !els.confirmDialogCancel) {
      resolve(window.confirm(typeof body === "string" ? body : (Array.isArray(body) ? body.join("\n") : "")));
      return;
    }
    if (els.confirmDialogTitle) els.confirmDialogTitle.textContent = title;
    if (els.confirmDialogBody) {
      els.confirmDialogBody.innerHTML = "";
      const lines = Array.isArray(body) ? body : [String(body || "")];
      for (const line of lines) {
        if (!line) continue;
        const p = document.createElement("p");
        p.textContent = line;
        els.confirmDialogBody.appendChild(p);
      }
    }
    els.confirmDialogOk.textContent = confirmText;
    els.confirmDialogCancel.textContent = cancelText;
    els.confirmDialog.classList.remove("hidden");
    els.confirmDialog.setAttribute("aria-hidden", "false");
    const cleanup = () => {
      els.confirmDialog.classList.add("hidden");
      els.confirmDialog.setAttribute("aria-hidden", "true");
      els.confirmDialogOk.removeEventListener("click", onOk);
      els.confirmDialogCancel.removeEventListener("click", onCancel);
      els.confirmDialog.removeEventListener("click", onBackdrop);
      document.removeEventListener("keydown", onKey);
    };
    const onOk = () => { cleanup(); resolve(true); };
    const onCancel = () => { cleanup(); resolve(false); };
    const onBackdrop = (e) => { if (e.target === els.confirmDialog) onCancel(); };
    const onKey = (e) => {
      if (e.key === "Escape") onCancel();
      else if (e.key === "Enter" && !e.isComposing) onOk();
    };
    els.confirmDialogOk.addEventListener("click", onOk);
    els.confirmDialogCancel.addEventListener("click", onCancel);
    els.confirmDialog.addEventListener("click", onBackdrop);
    document.addEventListener("keydown", onKey);
    setTimeout(() => els.confirmDialogOk?.focus(), 30);
  });
}

function refreshReferenceBar() {
  if (!els.referenceBar) return;
  const ref = state.imageReference;
  const visible = !!(state.imageMode && ref && _modelSupportsReference());
  els.referenceBar.classList.toggle("hidden", !visible);
  if (visible && els.referenceName) {
    els.referenceName.textContent = ref.name || ref.path || "";
  }
}

function setImageMode(enabled) {
  state.imageMode = !!enabled;
  els.btnImageMode?.classList.toggle("active", state.imageMode);
  els.aspectWrap?.classList.toggle("hidden", !state.imageMode);
  const modelsCount = (state.imageModels || []).filter(Boolean).length;
  els.imageModelWrap?.classList.toggle("hidden", !state.imageMode || modelsCount < 2);
  const hasResolutions = _resolutionsForCurrentModel().length > 0;
  els.resolutionWrap?.classList.toggle("hidden", !state.imageMode || !hasResolutions);
  syncAspectSelect();
  syncImageModelSelect();
  syncResolutionSelect();
  refreshDisplayedModel();
  refreshComposerPlaceholder();
  refreshReferenceBar();
}

function setBusy(busy, sessionId = state.sessionId) {
  if (!sessionId) {
    els.btnSend.disabled = !!state.imageGenerating;
    els.btnStop.disabled = true;
    els.input.disabled = false;
    setStatusPulse("idle");
    refreshComposerPlaceholder();
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
  els.btnSend.disabled = !!state.imageGenerating;
  els.btnStop.disabled = !currentBusy;
  els.input.disabled = false;
  refreshComposerPlaceholder();
  if (state.imageGenerating || currentBusy) {
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
    state.agentModel = payload.model;
  }
  if (payload.image_generation) {
    if (Array.isArray(payload.image_generation.models)) {
      state.imageModels = payload.image_generation.models.filter((name) => typeof name === "string" && name);
    }
    if (payload.image_generation.capabilities && typeof payload.image_generation.capabilities === "object") {
      state.imageCapabilities = payload.image_generation.capabilities;
    }
    if (payload.image_generation.model) state.imageModel = payload.image_generation.model;
    if (payload.image_generation.default_aspect_ratio) state.imageAspectRatio = payload.image_generation.default_aspect_ratio;
    if (payload.image_generation.default_resolution) state.imageResolution = payload.image_generation.default_resolution;
    // 如果当前 session 在本地有用户上次的图片偏好，优先用它覆盖服务端默认
    const prefs = loadSessionImagePrefs(state.sessionId);
    if (prefs) {
      if (prefs.model && (state.imageModels || []).includes(prefs.model)) {
        state.imageModel = prefs.model;
      }
      if (prefs.aspect) state.imageAspectRatio = prefs.aspect;
      if (prefs.resolution) state.imageResolution = prefs.resolution;
      if (prefs.reference && typeof prefs.reference === "object" && prefs.reference.path) {
        state.imageReference = { path: prefs.reference.path, name: prefs.reference.name || "" };
      }
    }
    syncImageModelSelect();
    syncAspectSelect();
    syncResolutionSelect();
    const modelsCount = (state.imageModels || []).filter(Boolean).length;
    if (state.imageMode) {
      els.imageModelWrap?.classList.toggle("hidden", modelsCount < 2);
      const hasResolutions = _resolutionsForCurrentModel().length > 0;
      els.resolutionWrap?.classList.toggle("hidden", !hasResolutions);
    }
    refreshReferenceBar();
  }
  if (payload.usage) {
    if (els.usageLabel) els.usageLabel.textContent = payload.usage.display || "—";
  }
  if (payload.capabilities) {
    state.capabilities = payload.capabilities;
    state.toolSchemas = Object.fromEntries(
      (payload.capabilities.tools || [])
        .filter((tool) => tool && tool.name)
        .map((tool) => [tool.name, tool.input_schema || {}]),
    );
  }
  if (typeof payload.label === "string") {
    state.currentLabel = payload.label;
  }
  refreshDisplayedModel();
  refreshChatTitle();
  updateRunningUI();
}

function _toolSchemaPlaceholder(schema) {
  if (!schema || typeof schema !== "object") return "";
  if (schema.type === "object") {
    const props = schema.properties && typeof schema.properties === "object" ? schema.properties : {};
    const out = {};
    for (const [key, child] of Object.entries(props)) {
      out[key] = _toolSchemaPlaceholderValue(child);
    }
    return JSON.stringify(out, null, 2);
  }
  return "";
}

function _toolSchemaPlaceholderValue(schema) {
  if (!schema || typeof schema !== "object") return "…";
  const t = schema.type;
  if (Array.isArray(t)) return _toolSchemaPlaceholderValue({ ...schema, type: t[0] });
  if (t === "object") {
    const props = schema.properties && typeof schema.properties === "object" ? schema.properties : {};
    const out = {};
    for (const [key, child] of Object.entries(props)) {
      out[key] = _toolSchemaPlaceholderValue(child);
    }
    return out;
  }
  if (t === "array") return [];
  if (t === "number" || t === "integer") return 0;
  if (t === "boolean") return false;
  return "…";
}

function _toolInputPendingText(name) {
  const schema = state.toolSchemas?.[name];
  const skeleton = _toolSchemaPlaceholder(schema);
  return skeleton || "（等待参数…）";
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

const markdownWorkerState = {
  worker: null,
  nextId: 0,
  pending: new Map(),
  disabled: false,
};

function ensureMarkdownWorker() {
  if (markdownWorkerState.disabled) return null;
  if (markdownWorkerState.worker) return markdownWorkerState.worker;
  if (typeof Worker === "undefined") {
    markdownWorkerState.disabled = true;
    return null;
  }
  try {
    const worker = new Worker("/static/markdown-worker.js?v=20260420a");
    worker.addEventListener("message", (event) => {
      const { id, html } = event.data || {};
      const callback = markdownWorkerState.pending.get(id);
      if (!callback) return;
      markdownWorkerState.pending.delete(id);
      callback(typeof html === "string" ? html : "");
    });
    worker.addEventListener("error", () => {
      markdownWorkerState.disabled = true;
      for (const [, callback] of markdownWorkerState.pending) {
        callback(null);
      }
      markdownWorkerState.pending.clear();
      try { worker.terminate(); } catch (_) {}
      markdownWorkerState.worker = null;
    });
    markdownWorkerState.worker = worker;
    return worker;
  } catch (_) {
    markdownWorkerState.disabled = true;
    return null;
  }
}

function requestMarkdownHTML(text, onDone) {
  const worker = ensureMarkdownWorker();
  if (!worker) {
    onDone(renderMarkdown(text));
    return;
  }
  const id = ++markdownWorkerState.nextId;
  markdownWorkerState.pending.set(id, onDone);
  worker.postMessage({ id, text });
}

function applyStreamingRenderedHTML(part, raw, html, { enhance = false, finalized = false } = {}) {
  if (!part || !part.el) return;
  if (part._renderSource !== raw) return;
  part.renderedRaw = raw;
  part.el.classList.add("rendered");
  part.el.innerHTML = html;
  if (enhance) enhanceRenderedContent(part.el);
  if (finalized) part.finalized = true;
  autoScrollIfNear();
}

function shouldStreamRenderMarkdown(text) {
  const value = typeof text === "string" ? text : "";
  if (!value) return false;
  return /[`*_#>\-\[\]\(\)\n|]/.test(value);
}

function streamRenderDelay(raw) {
  const size = (raw || "").length;
  if (size > 32000) return 420;
  if (size > 16000) return 320;
  if (size > 8000) return 240;
  if (size > 3000) return 180;
  return 120;
}

function countFenceMarkers(raw) {
  return ((raw || "").match(/```/g) || []).length;
}

function findStreamingSplitIndex(raw) {
  const value = typeof raw === "string" ? raw : "";
  if (value.length < 2200) return -1;
  if (countFenceMarkers(value) % 2 === 1) return -1;

  const softTail = 700;
  const searchLimit = Math.max(0, value.length - softTail);
  const doubleBreak = value.lastIndexOf("\n\n", searchLimit);
  if (doubleBreak >= 800) return doubleBreak + 2;

  const singleBreak = value.lastIndexOf("\n", searchLimit);
  if (singleBreak >= 1200) return singleBreak + 1;

  return -1;
}

function renderStreamingTextPart(part) {
  if (!part || !part.el) return;
  const raw = part.raw || "";
  part.renderHandle = null;
  if (!raw) {
    part._renderSource = "";
    part.el.textContent = "";
    return;
  }
  if (!shouldStreamRenderMarkdown(raw)) {
    part._renderSource = raw;
    part.renderedRaw = raw;
    part.el.textContent = raw;
    part.el.classList.remove("rendered");
    autoScrollIfNear();
    return;
  }
  part._renderSource = raw;
  requestMarkdownHTML(raw, (html) => {
    if (typeof html !== "string") {
      html = renderMarkdown(raw);
    }
    applyStreamingRenderedHTML(part, raw, html);
  });
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
    part._renderSource = "";
    part.el.textContent = "";
    return;
  }
  part._renderSource = trimmed;
  requestMarkdownHTML(trimmed, (html) => {
    if (typeof html !== "string") {
      html = renderMarkdown(trimmed);
    }
    applyStreamingRenderedHTML(part, trimmed, html, { enhance: true });
  });
}

function createStreamingTextPart() {
  const el = document.createElement("div");
  el.className = "stream-part";
  return { el, raw: "", renderedRaw: "", renderHandle: null, finalized: false, _renderSource: "" };
}

function appendStreamingPart(bubble) {
  const part = createStreamingTextPart();
  bubble.body.appendChild(part.el);
  bubble.currentText = part.el;
  bubble.textParts.push(part);
  return part;
}

function finalizeCompletedStreamingChunk(part) {
  if (!part || part.finalized) return;
  if (part.renderHandle) {
    window.clearTimeout(part.renderHandle);
    part.renderHandle = null;
  }
  const raw = part.raw || "";
  if (!raw.trim()) {
    part._renderSource = "";
    part.el.textContent = "";
    part.finalized = true;
    return;
  }
  part._renderSource = raw;
  requestMarkdownHTML(raw, (html) => {
    if (typeof html !== "string") {
      html = renderMarkdown(raw);
    }
    applyStreamingRenderedHTML(part, raw, html, { enhance: true, finalized: true });
  });
}

function maybeSplitStreamingPart(bubble, part) {
  if (!bubble || !part || part.finalized) return part;
  const splitIndex = findStreamingSplitIndex(part.raw);
  if (splitIndex < 0) return part;

  const completedRaw = part.raw.slice(0, splitIndex);
  const remainderRaw = part.raw.slice(splitIndex);
  part.raw = completedRaw;
  finalizeCompletedStreamingChunk(part);

  const nextPart = appendStreamingPart(bubble);
  nextPart.raw = remainderRaw;
  return nextPart;
}

function reasoningRenderDelay(raw) {
  const size = (raw || "").length;
  if (size > 20000) return 280;
  if (size > 8000) return 200;
  return 120;
}

function renderReasoningBlock(blockState) {
  if (!blockState || !blockState.el) return;
  blockState.renderHandle = null;
  blockState.renderedRaw = blockState.raw || "";
  blockState.el.textContent = blockState.renderedRaw;
  autoScrollIfNear();
}

function scheduleReasoningRender(blockState, { force = false } = {}) {
  if (!blockState || !blockState.el) return;
  if (force) {
    if (blockState.renderHandle) {
      window.clearTimeout(blockState.renderHandle);
      blockState.renderHandle = null;
    }
    renderReasoningBlock(blockState);
    return;
  }
  if (blockState.renderHandle) return;
  blockState.renderHandle = window.setTimeout(() => {
    renderReasoningBlock(blockState);
  }, reasoningRenderDelay(blockState.raw));
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
  bindResizableCommandTables(container);
}

function bindResizableCommandTables(container = document) {
  container.querySelectorAll('.cmd-table[data-resizable="1"]').forEach((table) => {
    if (table.dataset.boundResize === "1") return;
    table.dataset.boundResize = "1";
    const key = table.dataset.tableKey || "";
    const minWidth = Number(table.dataset.minCol || 128);
    const maxWidth = Number(table.dataset.maxCol || 520);
    const handle = table.querySelector(".cmd-divider-handle");
    if (!handle) return;

    if (key) {
      try {
        const saved = localStorage.getItem(`pooh.cmdtable.${key}`);
        if (saved) {
          const width = Number(saved);
          if (Number.isFinite(width)) {
            table.style.setProperty("--cmd-col-width", `${Math.max(minWidth, Math.min(maxWidth, width))}px`);
          }
        }
      } catch (_) {}
    }

    handle.addEventListener("pointerdown", (e) => {
      e.preventDefault();
      const startX = e.clientX;
      const startWidth = parseFloat(getComputedStyle(table).getPropertyValue("--cmd-col-width")) || 180;
      handle.setPointerCapture?.(e.pointerId);

      const onMove = (evt) => {
        const nextWidth = Math.max(minWidth, Math.min(maxWidth, startWidth + evt.clientX - startX));
        table.style.setProperty("--cmd-col-width", `${nextWidth}px`);
      };
      const onUp = () => {
        try {
          handle.releasePointerCapture?.(e.pointerId);
        } catch (_) {}
        window.removeEventListener("pointermove", onMove);
        window.removeEventListener("pointerup", onUp);
        if (key) {
          try {
            const width = parseFloat(getComputedStyle(table).getPropertyValue("--cmd-col-width")) || startWidth;
            localStorage.setItem(`pooh.cmdtable.${key}`, String(width));
          } catch (_) {}
        }
      };

      window.addEventListener("pointermove", onMove);
      window.addEventListener("pointerup", onUp);
    });
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
      <div class="msg-attachments"></div>
      ${canAct ? `
      <div class="msg-tools">
        <button class="msg-copy" type="button" title="复制消息">复制</button>
        <span class="msg-time">${escapeHtml(timeText)}</span>
      </div>` : ""}
    </div>
  `;
  const body = root.querySelector(".body");
  const attachments = root.querySelector(".msg-attachments");
  const copyBtn = root.querySelector(".msg-copy");
  if (copyBtn) {
    setCopyButtonState(copyBtn, "");
    attachCopyHandler(copyBtn);
  }
  return { root, body, attachments, copyBtn };
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
    shell.body.classList.toggle("empty", !String(parsed.body || "").trim());
  } else {
    const renderedText = normalizeUserMarkdown(text);
    if (renderedText.trim()) {
      shell.body.classList.add("rendered");
      shell.body.classList.remove("empty");
      shell.body.innerHTML = renderMarkdown(renderedText);
      enhanceRenderedContent(shell.body);
    } else {
      shell.body.classList.remove("rendered");
      shell.body.classList.add("empty");
      shell.body.innerHTML = "";
    }
  }
}

function buildMessageCopyText(text, attachments = []) {
  const lines = [];
  const normalized = typeof text === "string" ? text.trim() : "";
  if (normalized) lines.push(normalized);
  for (const attachment of attachments || []) {
    if (!attachment) continue;
    const name = String(attachment.name || "").trim() || "未命名附件";
    lines.push(`${attachment.kind === "image" ? "[图片]" : "[文件]"} ${name}`);
  }
  return lines.join("\n").trim();
}

function renderMessageAttachments(shell, attachments = []) {
  if (!shell?.attachments) return;
  const items = Array.isArray(attachments) ? attachments.filter(Boolean) : [];
  shell.attachments.innerHTML = "";
  shell.attachments.dataset.count = String(items.length);
  if (!items.length) return;

  for (const attachment of items) {
    const name = String(attachment.name || "").trim() || "未命名附件";
    const kind = attachment.kind || (_artifactType(name) === "image" ? "image" : "file");
    const meta = attachment.size ? _humanSize(attachment.size) : "";

    if (kind === "image" && attachment.url) {
      const card = document.createElement("a");
      card.className = "msg-attachment-card is-image";
      card.href = attachment.url;
      card.target = "_blank";
      card.rel = "noreferrer";
      const refPath = attachment.path || "";
      const reuseBtn = state.imageMode && _modelSupportsReference() && refPath
        ? `<button type="button" class="msg-attachment-reuse" data-ref-path="${escapeHtml(refPath)}" data-ref-name="${escapeHtml(name)}" title="基于此图继续修改" aria-label="基于此图继续修改"><svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg></button>`
        : "";
      card.innerHTML = `
        <div class="msg-attachment-media">
          <img src="${escapeHtml(attachment.url)}" alt="${escapeHtml(name)}" loading="lazy" />
        </div>
        ${reuseBtn}
        <div class="msg-attachment-caption">
          <span class="msg-attachment-badge">图片</span>
          <div class="msg-attachment-texts">
            <span class="msg-attachment-name" title="${escapeHtml(name)}">${escapeHtml(name)}</span>
            ${meta ? `<span class="msg-attachment-meta">${escapeHtml(meta)}</span>` : ""}
          </div>
        </div>
      `;
      const reuse = card.querySelector(".msg-attachment-reuse");
      if (reuse) {
        reuse.addEventListener("click", (e) => {
          e.preventDefault();
          e.stopPropagation();
          state.imageReference = {
            path: reuse.dataset.refPath || "",
            name: reuse.dataset.refName || "",
          };
          refreshReferenceBar();
          saveSessionImagePrefs();
          els.input?.focus();
        });
      }
      card.addEventListener("click", (e) => {
        if (e.target.closest(".msg-attachment-reuse")) return;
        e.preventDefault();
        openImageLightbox({
          url: attachment.url,
          name,
        });
      });
      shell.attachments.appendChild(card);
      continue;
    }

    const card = document.createElement("div");
    card.className = "msg-attachment-card is-file";
    card.innerHTML = `
      <div class="msg-attachment-file-icon">${escapeHtml(_fileIcon(name))}</div>
      <div class="msg-attachment-texts">
        <span class="msg-attachment-name" title="${escapeHtml(name)}">${escapeHtml(name)}</span>
        ${meta ? `<span class="msg-attachment-meta">${escapeHtml(meta)}</span>` : ""}
      </div>
    `;
    shell.attachments.appendChild(card);
  }
}

function buildPendingMessageAttachments(files = []) {
  return files.map((item) => {
    const name = String(item.name || "").trim();
    const kind = _artifactType(name) === "image" ? "image" : "file";
    return {
      kind,
      name,
      size: item.size || item.file?.size || 0,
      url: kind === "image" ? (item.previewUrl || "") : "",
    };
  }).filter((item) => item.kind !== "image" || item.url);
}

function openImageLightbox({ url, name = "" } = {}) {
  if (!els.imageLightbox || !els.imageLightboxImg) return;
  if (!url) return;
  els.imageLightboxImg.src = url;
  els.imageLightboxImg.alt = name || "图片预览";
  if (els.imageLightboxName) els.imageLightboxName.textContent = name || "图片预览";
  els.imageLightbox.classList.remove("hidden");
  els.imageLightbox.setAttribute("aria-hidden", "false");
  document.body.classList.add("lightbox-open");
}

function closeImageLightbox() {
  if (!els.imageLightbox || !els.imageLightboxImg) return;
  els.imageLightbox.classList.add("hidden");
  els.imageLightbox.setAttribute("aria-hidden", "true");
  els.imageLightboxImg.removeAttribute("src");
  els.imageLightboxImg.alt = "";
  document.body.classList.remove("lightbox-open");
}

function appendMessage(role, text, { scroll = true, attachments = [] } = {}) {
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
    shell.body.classList.add("rendered");
    shell.body.innerHTML = renderMarkdown(text);
    enhanceRenderedContent(shell.body);
  }
  renderMessageAttachments(shell, attachments);
  setCopyButtonState(shell.copyBtn, buildMessageCopyText(text, attachments));
  els.chatInner.appendChild(shell.root);
  if (scroll) els.messages.scrollTop = els.messages.scrollHeight;
  scheduleMinimapRebuild();
}

function buildHistoryMessageNode(message) {
  if (!message) return null;
  if (message.role === "assistant") {
    const shell = createMessageShell("assistant", { msgId: `m-${_msgIndex++}` });
    let bodyHTML = "";
    const hasAttachments = Array.isArray(message.attachments) && message.attachments.length > 0;
    if (message.tools && message.tools.length) {
      bodyHTML += buildToolGroupHTML(message.tools);
    }
    if (message.text && message.text.trim()) {
      bodyHTML += `<div class="stream-part">${renderMarkdown(message.text)}</div>`;
    }
    if ((message.tools && message.tools.length) && !String(message.text || "").trim() && !hasAttachments) {
      shell.root.classList.add("tools-only");
    }
    shell.body.classList.add("rendered");
    shell.body.innerHTML = bodyHTML || (hasAttachments ? "" : renderMarkdown("(empty response)"));
    if (bodyHTML) enhanceRenderedContent(shell.body);

    renderMessageAttachments(shell, message.attachments || []);
    setCopyButtonState(shell.copyBtn, buildMessageCopyText(message.text || shell.body.textContent || "", message.attachments || []));
    return shell.root;
  }
  if ((message.text && message.text.trim()) || (message.attachments || []).length) {
    const shell = createMessageShell(message.role, { msgId: `m-${_msgIndex++}` });
    if (message.role === "user") {
      _renderUserBodyWithQuote(shell, message.text || "");
    } else if (message.role === "assistant") {
      shell.body.classList.add("rendered");
      shell.body.innerHTML = renderMarkdown(message.text || "");
      enhanceRenderedContent(shell.body);
    } else {
      shell.body.classList.add("rendered");
      shell.body.innerHTML = renderMarkdown(message.text || "");
      enhanceRenderedContent(shell.body);
    }
    renderMessageAttachments(shell, message.attachments || []);
    setCopyButtonState(shell.copyBtn, buildMessageCopyText(message.text || "", message.attachments || []));
    return shell.root;
  }
  return null;
}

function _wrapToolMega(nodes, kindClass) {
  if (!nodes || nodes.length < 2) return;
  const parent = nodes[0].parentNode;
  if (!parent) return;
  let totalTools = 0;
  for (const node of nodes) {
    totalTools += node.querySelectorAll?.(".tool-block").length || 0;
  }
  if (!totalTools) totalTools = nodes.length;

  const mega = document.createElement("div");
  mega.className = `tools-mega collapsed ${kindClass}`;
  const head = document.createElement("div");
  head.className = "tools-mega-head";
  head.innerHTML = `
    <span class="thinking-icon">⊙</span>
    <span class="thinking-label">已处理</span>
    <span class="thinking-count">${totalTools} 个工具调用</span>
    <span class="tools-mega-hint">展开详情</span>
    <span class="caret">▾</span>
  `;
  head.addEventListener("click", () => {
    const willCollapse = !mega.classList.contains("collapsed");
    mega.classList.toggle("collapsed");
    const hint = head.querySelector(".tools-mega-hint");
    if (hint) hint.textContent = willCollapse ? "展开详情" : "点击收起";
  });
  const body = document.createElement("div");
  body.className = "tools-mega-body";
  mega.appendChild(head);
  mega.appendChild(body);
  parent.insertBefore(mega, nodes[0]);
  for (const node of nodes) body.appendChild(node);
}

function _wrapConsecutiveRuns(container, matcher, kindClass) {
  if (!container) return;
  const children = Array.from(container.children);
  let i = 0;
  const runs = [];
  while (i < children.length) {
    const node = children[i];
    if (
      node &&
      !node.classList?.contains("tools-mega") &&
      !node.closest?.(".tools-mega") &&
      matcher(node)
    ) {
      let j = i + 1;
      while (j < children.length && matcher(children[j]) && !children[j].classList?.contains("tools-mega")) j++;
      if (j - i >= 2) runs.push(children.slice(i, j));
      i = j;
    } else {
      i++;
    }
  }
  for (const run of runs) _wrapToolMega(run, kindClass);
}

function applyToolMegaCollapse(scope) {
  if (scope) {
    _wrapConsecutiveRuns(
      scope,
      (n) => n.classList?.contains("thinking-group"),
      "tools-mega-inline",
    );
    return;
  }
  const root = els.chatInner;
  if (!root) return;

  _wrapConsecutiveRuns(
    root,
    (n) => n.classList?.contains("msg") && n.classList?.contains("a") && n.classList?.contains("tools-only"),
    "tools-mega-history",
  );

  for (const body of root.querySelectorAll(".msg.a .bubble > .body")) {
    if (body.closest(".tools-mega-body")) continue;
    _wrapConsecutiveRuns(
      body,
      (n) => n.classList?.contains("thinking-group"),
      "tools-mega-inline",
    );
  }
}

function nextPaint() {
  return new Promise((resolve) => window.requestAnimationFrame(() => resolve()));
}

function clearMessages() {
  els.chatInner.innerHTML = "";
  els.chatInner.appendChild(els.emptyHint);
}

function _hashString(input, seed = 2166136261) {
  let hash = seed >>> 0;
  const text = String(input || "");
  for (let i = 0; i < text.length; i += 1) {
    hash ^= text.charCodeAt(i);
    hash = Math.imul(hash, 16777619);
  }
  return hash >>> 0;
}

function buildMessageSignature(messages = []) {
  let hash = 2166136261;
  for (const message of messages) {
    if (!message) continue;
    hash = _hashString(message.role || "", hash);
    hash = _hashString(message.ts || "", hash);
    hash = _hashString(message.mode || "", hash);
    hash = _hashString(message.model || "", hash);
    hash = _hashString(message.text || "", hash);
    for (const attachment of message.attachments || []) {
      hash = _hashString(attachment.kind || "", hash);
      hash = _hashString(attachment.name || "", hash);
      hash = _hashString(attachment.url || "", hash);
      hash = _hashString(attachment.size || "", hash);
    }
    for (const tool of message.tools || []) {
      hash = _hashString(tool.name || "", hash);
      hash = _hashString(JSON.stringify(tool.input || {}), hash);
      hash = _hashString(tool.result || "", hash);
      hash = _hashString(tool.is_error ? "1" : "0", hash);
    }
  }
  return `${messages.length}:${(hash >>> 0).toString(16)}`;
}

function _collectChatNodes() {
  return Array.from(els.chatInner?.childNodes || []).filter((node) => node !== els.emptyHint);
}

function updateSessionViewCache(sessionId, { signature } = {}) {
  if (!sessionId || !els.chatInner || !els.messages) return;
  const nodes = _collectChatNodes();
  state.sessionViewCache.set(sessionId, {
    nodes,
    scrollTop: els.messages.scrollTop,
    hasMessages: nodes.some((node) => node.nodeType === Node.ELEMENT_NODE && node.classList?.contains("msg")),
    signature: signature ?? state.sessionMessageSignatures.get(sessionId) ?? null,
  });
}

function restoreSessionView(sessionId) {
  if (!sessionId || !els.chatInner || !els.messages) return false;
  const cached = state.sessionViewCache.get(sessionId);
  if (!cached) return false;

  clearMessages();
  if (cached.nodes?.length) {
    const frag = document.createDocumentFragment();
    for (const node of cached.nodes) {
      frag.appendChild(node);
    }
    els.chatInner.appendChild(frag);
  }

  syncIntroMode(!!cached.hasMessages);
  els.messages.scrollTop = cached.hasMessages
    ? Math.min(cached.scrollTop || 0, Math.max(0, els.messages.scrollHeight - els.messages.clientHeight))
    : 0;
  scheduleMinimapRebuild();
  return true;
}

function ensureSessionViewAttached(sessionId) {
  const cached = state.sessionViewCache.get(sessionId);
  if (!cached?.nodes?.length) return false;
  if (cached.nodes.every((node) => node.parentNode === els.chatInner)) return true;
  return restoreSessionView(sessionId);
}

let sessionListRenderHandle = null;
function scheduleSessionListRender() {
  if (sessionListRenderHandle) return;
  sessionListRenderHandle = window.requestAnimationFrame(() => {
    sessionListRenderHandle = null;
    renderSessionList();
  });
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
      <span class="thinking-label">已处理</span>
      <span class="thinking-count">${tools.length} 个工具调用</span>
      <span class="caret">▾</span>
    </div>
    <div class="thinking-body">${items}</div>
  </div>`;
}

async function refreshMessages() {
  try {
    const requestSeq = ++state.messageRenderSeq;
    const requestedSessionId = state.sessionId;
    const query = requestedSessionId ? `?session_id=${encodeURIComponent(requestedSessionId)}` : "";
    const data = await api(`/api/messages${query}`);
    if (requestSeq !== state.messageRenderSeq) return;
    if (requestedSessionId && requestedSessionId !== state.sessionId) return;
    applyState(data);
    const activeSessionId = state.sessionId;
    const messages = data.messages || [];
    const signature = buildMessageSignature(messages);
    state.sessionMessageSignatures.set(activeSessionId, signature);
    const liveBubble = state.liveBubbles.get(activeSessionId);
    const cached = state.sessionViewCache.get(activeSessionId);
    if (cached && !liveBubble && cached.signature === signature) {
      if (!ensureSessionViewAttached(activeSessionId)) {
        clearMessages();
      }
      syncIntroMode(!!cached.hasMessages);
      if (!cached.hasMessages) {
        els.messages.scrollTop = 0;
      }
      scheduleMinimapRebuild();
      return;
    }
    clearMessages();
    syncIntroMode(messages.length > 0);
    const chunkSize = 6;
    for (let i = 0; i < messages.length; i += chunkSize) {
      if (requestSeq !== state.messageRenderSeq || activeSessionId !== state.sessionId) return;
      const frag = document.createDocumentFragment();
      for (const message of messages.slice(i, i + chunkSize)) {
        const node = buildHistoryMessageNode(message);
        if (node) frag.appendChild(node);
      }
      els.chatInner.appendChild(frag);
      await nextPaint();
    }
    const visibleLiveBubble = state.liveBubbles.get(activeSessionId);
    if (visibleLiveBubble) {
      if (!visibleLiveBubble.root.isConnected) {
        els.chatInner.appendChild(visibleLiveBubble.root);
      }
      for (const part of visibleLiveBubble.textParts || []) {
        if ((part.raw || "") !== (part.renderedRaw || "")) {
          renderStreamingTextPart(part);
        }
      }
    }
    applyToolMegaCollapse();
    if ((data.messages || []).length > 0) {
      els.messages.scrollTop = els.messages.scrollHeight;
    }
    updateSessionViewCache(activeSessionId, { signature });
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
  if (n == null || !Number.isFinite(Number(n))) return "--";
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

async function refreshSessions({ silent = false } = {}) {
  try {
    const data = await api("/api/sessions");
    state.sessions = data.sessions || [];
    applyState(data);
    refreshChatTitle();
    scheduleSessionListRender();
  } catch (err) {
    if (!silent) {
      agentStatus.set("error", "加载会话失败", err.message || "");
    }
  }
}

async function refreshFiles() {
  try {
    const data = await api("/api/files");
    applyState(data);
    state.fileGroups = data.groups || [];
    scheduleSessionListRender();
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

  const frag = document.createDocumentFragment();
  let lastGroup = null;
  for (const item of list) {
    const group = _sessionDateLabel(item.last_active);
    if (group !== lastGroup) {
      lastGroup = group;
      const hdr = document.createElement("div");
      hdr.className = "section-label";
      hdr.textContent = group;
      frag.appendChild(hdr);
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
    const usageTokens = Number(usage?.tokens);
    const usageLimit = Number(usage?.limit);
    const hasUsageLimit = Number.isFinite(usageLimit) && usageLimit > 0;
    const hasUsageTokens = Number.isFinite(usageTokens) && usageTokens >= 0;
    const usageRatio = hasUsageLimit && hasUsageTokens ? usageTokens / usageLimit : 0;
    const usageTitle = hasUsageLimit
      ? `${hasUsageTokens ? usageTokens.toLocaleString() : "--"} / ${usageLimit.toLocaleString()} tokens`
      : "";
    const usageText = hasUsageTokens ? _fmtTokens(usageTokens) : "--";
    const usageLimitText = hasUsageLimit ? _fmtTokens(usageLimit) : "--";
    const tokBarHTML = hasUsageLimit ? `
      <div class="tok-bar" title="${usageTitle}">
        <div class="tok-track"><div class="tok-fill${usageRatio >= 0.75 ? " warn" : ""}" style="width: ${Math.min(100, usageRatio * 100)}%"></div></div>
        <div class="tok-text">${escapeHtml(usageText)}<span>/${escapeHtml(usageLimitText)}</span></div>
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
        scheduleSessionListRender();
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

    frag.appendChild(convo);
  }
  els.sessionList.replaceChildren(frag);
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
    state.sessionViewCache.delete(sessionId);
    state.sessionMessageSignatures.delete(sessionId);
    state.liveBubbles.delete(sessionId);
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
  shell.root.classList.add("tools-only");
  return {
    root: shell.root,
    body: shell.body,
    copyBtn: shell.copyBtn,
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
    group.querySelector(".thinking-label").textContent = "已处理";
    group.querySelector(".thinking-count").textContent =
      n > 1 ? `${n} 个工具调用` : n === 1 ? "1 个工具调用" : "";
  }
}

function _endOtherBlocks(bubble, keep) {
  if (keep !== "text") bubble.currentText = null;
  if (keep !== "reasoning" && bubble._currentReasoning) {
    scheduleReasoningRender(bubble._currentReasoning, { force: true });
    bubble._currentReasoning = null;
  }
  if (keep !== "tool") finalizeToolGroup(bubble);
}

function appendTextDelta(bubble, delta) {
  removeCursor(bubble);
  _endOtherBlocks(bubble, "text");
  bubble.root.classList.remove("tools-only");
  bubble.body.classList.add("rendered");
  if (!bubble.currentText) {
    appendStreamingPart(bubble);
  }
  let part = bubble.textParts[bubble.textParts.length - 1];
  part.raw += delta;
  setCopyButtonState(
    bubble.copyBtn,
    bubble.textParts.map((p) => p.raw).join(""),
  );
  part = maybeSplitStreamingPart(bubble, part);
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
    bubble._currentReasoning = {
      el: block.querySelector(".reasoning-text"),
      raw: "",
      renderedRaw: "",
      renderHandle: null,
    };
  }
  bubble._currentReasoning.raw += delta;
  scheduleReasoningRender(bubble._currentReasoning);
}

function startReasoningPart(bubble) {
  if (bubble._currentReasoning) {
    scheduleReasoningRender(bubble._currentReasoning, { force: true });
  }
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
        <span class="thinking-label">处理中</span>
        <span class="thinking-count">0 个工具调用</span>
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
    group._toolCount > 1 ? `${group._toolCount} 个工具调用` : "1 个工具调用";

  const wrap = document.createElement("div");
  wrap.className = "tool-block";
  wrap.innerHTML = `
    <div class="tool-head">
      <span class="badge">TOOL</span>
      <span class="tool-name"></span>
      <span class="tool-status">构造参数中…</span>
    </div>
    <div class="tool-body">
      <div class="tool-label">INPUT</div>
      <pre class="tool-input"></pre>
    </div>
  `;
  wrap._inputRaw = "";
  wrap.querySelector(".tool-name").textContent = name || "tool";
  wrap.querySelector(".tool-input").textContent = _toolInputPendingText(name || "tool");
  group.querySelector(".thinking-body").appendChild(wrap);
  bubble.toolBlocks[call_id] = wrap;
  autoScrollIfNear();
  return wrap;
}

function appendToolInputDelta(bubble, { call_id, name, delta, arguments: rawArguments }) {
  let wrap = bubble.toolBlocks[call_id];
  if (!wrap) wrap = addToolBlock(bubble, { call_id, name });
  wrap.querySelector(".tool-name").textContent = name || "tool";
  wrap._inputRaw = typeof rawArguments === "string"
    ? rawArguments
    : `${wrap._inputRaw || ""}${delta || ""}`;
  const toolInput = wrap.querySelector(".tool-input");
  toolInput.textContent = wrap._inputRaw || _toolInputPendingText(name || "tool");
  wrap.querySelector(".tool-status").textContent = "构造参数中…";
  autoScrollIfNear();
}

function finalizeToolInput(bubble, { call_id, id, name, input }) {
  let wrap = bubble.toolBlocks[call_id];
  if (!wrap) wrap = addToolBlock(bubble, { call_id, name });
  wrap.querySelector(".tool-name").textContent = name || "tool";
  wrap._inputRaw = JSON.stringify(input || {}, null, 2);
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

// ─── SSE Chat Stream ───
async function streamChat(text, files = []) {
  const launchedSessionId = state.sessionId;
  const bubble = createAssistantBubble();
  bubble._sawInjected = false;
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
      case "tool_use_delta":
        if (canRenderStream()) {
          appendToolInputDelta(bubble, evt);
          agentStatus.set("tool", `调用工具: ${evt.name || "unknown"}`, "模型正在逐步生成工具参数…");
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
          if (bubble._currentReasoning) {
            scheduleReasoningRender(bubble._currentReasoning, { force: true });
            bubble._currentReasoning = null;
          }
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
            bubble.textParts.map((p) => p.raw).join("") || evt.text || "",
          );
          applyToolMegaCollapse(bubble.body);
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
          bubble._sawInjected = true;
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
    if (bubble._currentReasoning) {
      scheduleReasoningRender(bubble._currentReasoning, { force: true });
      bubble._currentReasoning = null;
    }
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
    if (bubble._sawInjected && state.sessionId === launchedSessionId) {
      await refreshMessages();
    }
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

async function sendImageGeneration(text) {
  state.imageGenerating = true;
  updateRunningUI();
  agentStatus.set("busy", "开始图片生成", `${state.imageModel} 正在生成图片…`);
  try {
    const refPaths = state.imageReference?.path && _modelSupportsReference()
      ? [state.imageReference.path]
      : [];
    const body = {
      text,
      session_id: state.sessionId,
      aspect_ratio: state.imageAspectRatio,
      model: state.imageModel,
    };
    if (_resolutionsForCurrentModel().length) body.resolution = state.imageResolution;
    if (refPaths.length) body.reference_image_paths = refPaths;
    const data = await api("/api/image/generate", { method: "POST", body });
    if (data.reply?.model) state.imageModel = data.reply.model;
    applyState(data);
    appendMessage("assistant", data.reply?.text || "", {
      attachments: data.reply?.attachments || [],
    });
    await Promise.all([refreshSessions(), refreshFiles()]);
    const imageCount = Array.isArray(data.reply?.attachments)
      ? data.reply.attachments.filter((item) => item?.kind === "image").length
      : 0;
    agentStatus.set("idle", "图片已生成", imageCount ? `已返回 ${imageCount} 张图片` : "图片已返回");
  } finally {
    state.imageGenerating = false;
    updateRunningUI();
  }
}

async function sendMessage(text) {
  if (state.imageGenerating) return;
  if (!text.trim() && !state.pendingFiles.length) return;
  const launchedSessionId = state.sessionId;

  if (launchedSessionId && state.runningSessions.has(launchedSessionId)) {
    if (state.imageMode) {
      appendMessage("system", "图片生成模式下，当前会话正在运行中。请先停止本轮文本会话，再生成图片。");
      agentStatus.set("error", "无法生成图片", "当前会话仍在运行中，请先点击停止或等待本轮完成。");
      return;
    }
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

  if (state.imageMode && state.pendingFiles.length) {
    appendMessage("system", "图片生成模式暂不支持附件。请先移除附件，再输入图片提示词。");
    agentStatus.set("error", "无法生成图片", "图片生成模式当前只支持文本提示词。");
    return;
  }

  const pendingFiles = [...state.pendingFiles];
  const filePaths = pendingFiles.map((f) => f.serverPath);
  const attachments = buildPendingMessageAttachments(pendingFiles);
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

  appendMessage("user", composed, { attachments });
  if (state.imageMode) {
    try {
      await sendImageGeneration(composed);
    } catch (err) {
      appendMessage("system", `图片生成失败: ${err.message}`);
      agentStatus.set("error", "图片生成失败", err.message || "unknown");
    }
    return;
  }
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
    updateSessionViewCache(state.sessionId);
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
    updateSessionViewCache(state.sessionId);
    const data = await api("/api/session/switch", {
      method: "POST",
      body: { session_id_prefix: prefix, session_id: state.sessionId },
    });
    applyState(data);
    scheduleSessionListRender();
    refreshChatTitle();
    restoreSessionView(state.sessionId);
    await refreshMessages();
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
    syncComposerOffset();
    return;
  }
  els.replyCtx.classList.remove("hidden");
  const snippet = (ctx.text || "").replace(/\s+/g, " ").trim().slice(0, 60);
  els.replyCtxText.textContent = `引用 ${ctx.who}: ${snippet}${snippet.length >= 60 ? "…" : ""}`;
  syncComposerOffset();
  els.input.focus();
}

function clearReplyCtx() {
  setReplyCtx(null);
}

els.replyCtxClear?.addEventListener("click", clearReplyCtx);

function _selectionNodeToElement(node) {
  if (!node) return null;
  return node.nodeType === Node.ELEMENT_NODE ? node : node.parentElement;
}

function _whoForRole(role) {
  if (role === "user") return "你";
  if (role === "assistant") return "Pooh Code";
  return "系统";
}

function hideSelectionQuoteAction() {
  state.selectionQuote = null;
  if (!els.selectionQuote) return;
  els.selectionQuote.classList.add("hidden");
  els.selectionQuote.setAttribute("aria-hidden", "true");
}

function getSelectionQuoteCandidate() {
  const sel = window.getSelection?.();
  if (!sel || sel.rangeCount === 0 || sel.isCollapsed) return null;
  const rawText = sel.toString();
  const text = rawText.replace(/\s+/g, " ").trim();
  if (!text) return null;

  const range = sel.getRangeAt(0);
  const startEl = _selectionNodeToElement(range.startContainer);
  const endEl = _selectionNodeToElement(range.endContainer);
  if (!startEl || !endEl) return null;
  if (els.input?.contains(startEl) || els.input?.contains(endEl)) return null;

  const startMsg = startEl.closest(".msg");
  const endMsg = endEl.closest(".msg");
  if (!startMsg || startMsg !== endMsg) return null;
  if (!els.messages?.contains(startMsg)) return null;
  if (startEl.closest(".msg-tools") || endEl.closest(".msg-tools")) return null;

  const rect = range.getBoundingClientRect();
  if (!rect || (!rect.width && !rect.height)) return null;

  return {
    text,
    who: _whoForRole(startMsg.getAttribute("data-role") || ""),
    rect,
  };
}

function showSelectionQuoteAction(candidate) {
  if (!els.selectionQuote || !candidate) return;
  state.selectionQuote = { who: candidate.who, text: candidate.text };
  els.selectionQuote.classList.remove("hidden");
  els.selectionQuote.setAttribute("aria-hidden", "false");

  const rect = candidate.rect;
  const pop = els.selectionQuote;
  const width = pop.offsetWidth || 180;
  const height = pop.offsetHeight || 44;
  const centerX = rect.left + rect.width / 2;
  const minX = 16 + width / 2;
  const maxX = window.innerWidth - 16 - width / 2;
  const left = Math.max(minX, Math.min(maxX, centerX));
  const showAbove = rect.top > height + 24;

  pop.style.left = `${left}px`;
  if (showAbove) {
    pop.dataset.place = "top";
    pop.style.top = `${Math.max(12, rect.top - 12)}px`;
  } else {
    pop.dataset.place = "bottom";
    pop.style.top = `${Math.min(window.innerHeight - height - 12, rect.bottom + 12)}px`;
  }
}

function syncSelectionQuoteAction() {
  if (state.selectionDragging) return;
  const candidate = getSelectionQuoteCandidate();
  if (!candidate) {
    hideSelectionQuoteAction();
    return;
  }
  showSelectionQuoteAction(candidate);
}

els.selectionQuoteBtn?.addEventListener("click", () => {
  if (!state.selectionQuote) return;
  setReplyCtx(state.selectionQuote);
  hideSelectionQuoteAction();
  try {
    window.getSelection?.().removeAllRanges();
  } catch (_) {}
});
els.selectionQuoteBtn?.addEventListener("mousedown", (e) => e.preventDefault());

// ─── Minimap ───
let minimapRebuildHandle = null;
function scheduleMinimapRebuild() {
  if (els.app?.classList.contains("right-collapsed")) return;
  const flush = () => {
    minimapRebuildHandle = null;
    rebuildMinimap();
  };
  if (minimapRebuildHandle) return;
  if (typeof window.requestIdleCallback === "function") {
    minimapRebuildHandle = window.requestIdleCallback(flush, { timeout: 180 });
    return;
  }
  minimapRebuildHandle = window.requestAnimationFrame(flush);
}

function rebuildMinimap() {
  if (!els.mmCanvas) return;
  const scroller = els.messages;
  if (!scroller) return;
  if (els.app?.classList.contains("right-collapsed")) return;
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
      thumb.src = f.previewUrl || URL.createObjectURL(f.file);
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
  syncComposerOffset();
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
        size: saved[i].size || fileList[i].size || 0,
        previewUrl: fileList[i].type.startsWith("image/") ? URL.createObjectURL(fileList[i]) : "",
      });
    }
    renderFilePreview();
  } catch (err) {
    appendMessage("system", `文件上传失败: ${err.message}`);
  }
}

els.btnAttach?.addEventListener("click", () => els.fileInput.click());
els.btnImageMode?.addEventListener("click", () => {
  setImageMode(!state.imageMode);
  els.input?.focus();
});
els.aspectSelect?.addEventListener("change", () => {
  const value = els.aspectSelect.value;
  if (_ratiosForCurrentModel().includes(value)) {
    state.imageAspectRatio = value;
    saveSessionImagePrefs();
  }
});
els.imageModelSelect?.addEventListener("change", async () => {
  const value = els.imageModelSelect.value;
  if (!value || !(state.imageModels || []).includes(value)) return;
  const prev = state.imageModel;
  state.imageModel = value;
  if (!_modelSupportsReference()) state.imageReference = null;
  syncAspectSelect();
  syncResolutionSelect();
  const hasResolutions = _resolutionsForCurrentModel().length > 0;
  els.resolutionWrap?.classList.toggle("hidden", !state.imageMode || !hasResolutions);
  refreshDisplayedModel();
  refreshReferenceBar();
  saveSessionImagePrefs();
  const caps = state.imageCapabilities?.[value];
  if (caps?.kind === "apimart" && prev !== value) {
    const ok = await openConfirmDialog({
      title: "切换到 " + value,
      body: [
        "该模型支持以上一张生成的图作为下一次的参考（图生图）。",
        "建议新开一个会话单独管理这条修改链路，便于记忆。",
      ],
      confirmText: "新建会话",
      cancelText: "继续在当前会话",
    });
    if (ok) {
      try {
        await newSession();
        // 新会话后服务器返回的 image_generation.model 是配置默认值，
        // 这里把用户刚选的模型还原回去，并刷新对应的下拉/能力 UI，
        // 同时把这一组偏好持久化到新 session 的 localStorage 里，避免刷新又被打回默认
        state.imageModel = value;
        syncImageModelSelect();
        syncAspectSelect();
        syncResolutionSelect();
        const ok2 = _resolutionsForCurrentModel().length > 0;
        els.resolutionWrap?.classList.toggle("hidden", !state.imageMode || !ok2);
        refreshDisplayedModel();
        refreshReferenceBar();
        saveSessionImagePrefs();
      } catch (err) {
        agentStatus.set("error", "新建会话失败", err.message);
      }
    }
  }
});

els.resolutionSelect?.addEventListener("change", () => {
  const value = els.resolutionSelect.value;
  if (!value) return;
  if (_resolutionsForCurrentModel().includes(value)) {
    state.imageResolution = value;
    saveSessionImagePrefs();
  }
});

els.referenceClear?.addEventListener("click", () => clearImageReference());
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
  syncComposerOffset();
}
els.input?.addEventListener("input", autosize);

function syncComposerOffset() {
  if (!els.messages || !els.composer) return;
  const wrap = els.composer.closest(".composer-wrap") || els.composer.parentElement;
  const height = wrap ? wrap.offsetHeight : els.composer.offsetHeight;
  const bottomPad = Math.max(170, Math.ceil(height + 28));
  els.messages.style.paddingBottom = `${bottomPad}px`;
  if (els.scrollBtn) {
    els.scrollBtn.style.bottom = `${Math.max(132, bottomPad - 24)}px`;
  }
}

if (typeof ResizeObserver !== "undefined" && els.composer) {
  const composerObserver = new ResizeObserver(() => syncComposerOffset());
  composerObserver.observe(els.composer);
  const wrap = els.composer.closest(".composer-wrap") || els.composer.parentElement;
  if (wrap) composerObserver.observe(wrap);
}

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

els.imageLightboxClose?.addEventListener("click", closeImageLightbox);
els.imageLightbox?.addEventListener("click", (e) => {
  if (e.target === els.imageLightbox) closeImageLightbox();
});
els.imageLightboxDialog?.addEventListener("click", (e) => e.stopPropagation());

els.messages?.addEventListener("scroll", () => {
  hideSelectionQuoteAction();
  const gap = els.messages.scrollHeight - els.messages.scrollTop - els.messages.clientHeight;
  els.scrollBtn?.classList.toggle("hidden", gap < 200);
});

els.messages?.addEventListener("pointerdown", (e) => {
  if (e.button !== 0) return;
  state.selectionDragging = true;
  hideSelectionQuoteAction();
});

document.addEventListener("selectionchange", () => {
  if (state.selectionDragging) return;
  window.requestAnimationFrame(syncSelectionQuoteAction);
});

document.addEventListener("pointerup", () => {
  if (!state.selectionDragging) return;
  state.selectionDragging = false;
  window.setTimeout(syncSelectionQuoteAction, 0);
});

window.addEventListener("resize", hideSelectionQuoteAction);

els.sessionSearch?.addEventListener("input", () => {
  state.sessionFilter = els.sessionSearch.value;
  scheduleSessionListRender();
});

document.querySelectorAll(".chip[data-cmd]").forEach((chip) => {
  chip.addEventListener("click", () => {
    const cmd = chip.dataset.cmd;
    if (!cmd) return;
    if (els.input) {
      els.input.value = "";
      autosize();
    }
    sendMessage(cmd);
  });
});

// Keyboard shortcuts
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && els.selectionQuote && !els.selectionQuote.classList.contains("hidden")) {
    e.preventDefault();
    hideSelectionQuoteAction();
    try {
      window.getSelection?.().removeAllRanges();
    } catch (_) {}
    return;
  }
  if (e.key === "Escape" && els.imageLightbox && !els.imageLightbox.classList.contains("hidden")) {
    e.preventDefault();
    closeImageLightbox();
    return;
  }
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

// Pane collapse
els.btnCollapseLeft?.addEventListener("click", () => togglePaneCollapsed("left"));
els.btnCollapseRight?.addEventListener("click", () => togglePaneCollapsed("right"));
els.btnExpandLeft?.addEventListener("click", () => setPaneCollapsed("left", false));
els.btnExpandRight?.addEventListener("click", () => setPaneCollapsed("right", false));
loadCollapse();

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
  syncComposerOffset();
  els.input?.focus();
})();
