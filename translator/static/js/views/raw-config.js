import { el, toast, busy, confirmDialog, copyText } from "../ui.js";
import { store, mutate } from "../store.js";

export const id = "raw-config";
export const title = "Raw config";
export const glyph = "code";

let editor;
let gutter;
let statusEl;
let dirtyEl;
let applyBtn;
let resetBtn;
let formatBtn;
let liveText = "";

export function mount(root) {
  editor = el("textarea", {
    class: "editor-input",
    spellcheck: "false",
    autocapitalize: "off",
    autocomplete: "off",
    wrap: "off",
    "aria-label": "Configuration JSON",
    oninput: onEdit,
    onscroll: () => (gutter.scrollTop = editor.scrollTop),
    onkeydown: onKey,
  });
  gutter = el("div", { class: "editor-gutter", "aria-hidden": "true" });
  statusEl = el("div", { class: "editor-status" });
  dirtyEl = el("span", { class: "chip", style: "opacity:0" }, "Unsaved");

  formatBtn = el("button", { class: "ghost small", onclick: format }, "Format");
  const copyBtn = el(
    "button",
    {
      class: "ghost small",
      onclick: () => copyText(editor.value, "Config copied"),
    },
    "Copy",
  );

  applyBtn = el(
    "button",
    { class: "primary", onclick: (event) => apply(event.target) },
    "Apply full config",
  );
  resetBtn = el(
    "button",
    { class: "ghost", onclick: reset },
    "Reset to live config",
  );

  root.append(
    el(
      "p",
      { class: "hint", style: "margin-top:0" },
      "The full runtime config as JSON. Apply validates on the server and " +
        "replaces the whole config, persisting to config.yml (",
      el("code", {}, "PUT /config"),
      "). Edits stay local until you apply them.",
    ),
    el(
      "div",
      { class: "field-toolbar" },
      el(
        "div",
        { class: "row", style: "gap:8px" },
        el("span", { class: "fl" }, "config.json"),
        dirtyEl,
      ),
      el("div", { class: "row", style: "gap:8px" }, formatBtn, copyBtn),
    ),
    el("div", { class: "editor" }, gutter, editor),
    statusEl,
    el("div", { class: "actions" }, applyBtn, resetBtn),
  );
}

/* Keep the editor in sync with the live config only while it is untouched, so
   the 30 s background refresh never clobbers in-progress edits. */
export function onStore() {
  if (!store.config) return;
  const next = JSON.stringify(store.config, null, 2);
  if (next === liveText) return;
  const wasClean = editor.value === liveText;
  liveText = next;
  if (wasClean) editor.value = liveText;
  refresh();
}

export function guardLeave() {
  if (editor && editor.value !== liveText)
    return "You have unapplied changes to the raw config.";
}

function onEdit() {
  refresh();
}

/* Tab indents (2 spaces); Shift+Tab outdents; Cmd/Ctrl+S applies. */
function onKey(event) {
  if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "s") {
    event.preventDefault();
    if (!applyBtn.disabled) apply(applyBtn);
    return;
  }
  if (event.key !== "Tab") return;
  event.preventDefault();
  const { selectionStart: start, selectionEnd: end, value } = editor;
  if (event.shiftKey) {
    const lineStart = value.lastIndexOf("\n", start - 1) + 1;
    if (value.slice(lineStart, lineStart + 2) === "  ") {
      editor.value = value.slice(0, lineStart) + value.slice(lineStart + 2);
      editor.selectionStart = editor.selectionEnd = Math.max(
        lineStart,
        start - 2,
      );
    }
  } else {
    editor.value = value.slice(0, start) + "  " + value.slice(end);
    editor.selectionStart = editor.selectionEnd = start + 2;
  }
  refresh();
}

function refresh() {
  const text = editor.value;
  const lines = text.split("\n").length;
  gutter.textContent = Array.from({ length: lines }, (_, i) => i + 1).join(
    "\n",
  );
  gutter.scrollTop = editor.scrollTop;

  const err = parseError(text);
  editor.parentElement.classList.toggle("invalid", !!err);
  if (err) {
    statusEl.className = "editor-status err";
    statusEl.textContent = `✕ ${err}`;
  } else {
    statusEl.className = "editor-status";
    statusEl.textContent = `✓ Valid JSON · ${lines} line${lines === 1 ? "" : "s"}`;
  }

  const dirty = text !== liveText;
  dirtyEl.style.opacity = dirty ? "1" : "0";
  applyBtn.disabled = !!err || !dirty;
  resetBtn.disabled = !dirty;
  formatBtn.disabled = !!err || !text.trim();
}

/* Turn a JSON.parse SyntaxError into a "line X, column Y: reason" message. */
function parseError(text) {
  if (!text.trim()) return "Config is empty";
  try {
    JSON.parse(text);
    return null;
  } catch (e) {
    const reason = e.message
      .replace(/ in JSON at position \d+.*/, "")
      .replace(/^JSON\.parse: /, "");
    const at = /position (\d+)/.exec(e.message);
    if (at) {
      const pos = Number(at[1]);
      const before = text.slice(0, pos);
      const line = before.split("\n").length;
      const col = pos - before.lastIndexOf("\n");
      return `Line ${line}, column ${col}: ${reason}`;
    }
    return reason;
  }
}

function format() {
  try {
    editor.value = JSON.stringify(JSON.parse(editor.value), null, 2);
    refresh();
  } catch {
    toast("Can't format — config is not valid JSON", "error");
  }
}

function reset() {
  editor.value = liveText;
  editor.scrollTop = 0;
  refresh();
}

async function apply(button) {
  let parsed;
  try {
    parsed = JSON.parse(editor.value);
  } catch {
    toast("Config is not valid JSON", "error");
    return;
  }
  const ok = await confirmDialog({
    title: "Replace entire config?",
    message:
      "This overwrites the whole runtime config and persists to config.yml.",
    confirmLabel: "Replace config",
    danger: true,
  });
  if (!ok) return;
  await busy(button, async () => {
    await mutate("/config", { method: "PUT", body: parsed });
    toast("Config replaced");
  });
}
