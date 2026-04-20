try {
  self.importScripts("/static/vendor/marked.min.js");
} catch (_) {}

if (typeof self.marked !== "undefined" && self.marked.setOptions) {
  self.marked.setOptions({ gfm: true, breaks: true });
}

function escapeHtml(text) {
  return String(text || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/\"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function fallbackMarkdown(text) {
  return escapeHtml(text).replace(/\n/g, "<br>");
}

self.addEventListener("message", (event) => {
  const { id, text } = event.data || {};
  const source = typeof text === "string" ? text : "";
  let html = "";
  try {
    if (typeof self.marked !== "undefined" && self.marked.parse) {
      html = self.marked.parse(source);
    } else {
      html = fallbackMarkdown(source);
    }
  } catch (_) {
    html = fallbackMarkdown(source);
  }
  self.postMessage({ id, html });
});
