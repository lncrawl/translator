export const $ = (sel) => document.querySelector(sel);

export function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (key === "class") node.className = value;
    else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
    else if (value !== undefined && value !== null)
      node.setAttribute(key, value);
  }
  for (const child of children.flat()) {
    if (child === null || child === undefined || child === false) continue;
    node.append(child.nodeType ? child : document.createTextNode(child));
  }
  return node;
}

export function toast(message, kind = "success") {
  const glyph = kind === "error" ? "✕ " : "✓ ";
  const node = el("div", { class: `toast ${kind}` }, glyph + message);
  $("#toast").append(node);
  setTimeout(() => node.remove(), kind === "error" ? 7000 : 3500);
}

export function reportError(err) {
  let message = `${err.code || "error"}: ${err.message}`;
  if (err.retryAfter) message += ` (retry in ${err.retryAfter}s)`;
  toast(message, "error");
}

export async function busy(button, fn) {
  const original = button.textContent;
  button.disabled = true;
  button.innerHTML = '<span class="spin">◌</span> working…';
  try {
    return await fn();
  } catch (err) {
    reportError(err);
    return undefined;
  } finally {
    button.disabled = false;
    button.textContent = original;
  }
}

export function lines(textarea) {
  return textarea.value
    .split("\n")
    .map((s) => s.trim())
    .filter(Boolean);
}

export function numberOrNull(input) {
  return input.value.trim() === "" ? null : Number(input.value);
}

export function statusPill(status) {
  return el("span", { class: `status-${status}` }, status.replace("_", " "));
}

export function glossaryEditor(root) {
  const rowsBox = el("div", { class: "glossary-rows" });
  const addButton = el(
    "button",
    { class: "ghost small", onclick: () => addRow() },
    "Add term",
  );
  root.append(rowsBox, addButton);

  function addRow(term = "", translation = "") {
    const termInput = el("input", {
      type: "text",
      placeholder: "源词 (source term)",
      value: term,
    });
    const transInput = el("input", {
      type: "text",
      placeholder: "Translation",
      value: translation,
    });
    const row = el(
      "div",
      { class: "row" },
      termInput,
      transInput,
      el("button", { class: "danger small", onclick: () => row.remove() }, "✕"),
    );
    rowsBox.append(row);
  }

  return {
    addRow,
    get() {
      const glossary = {};
      for (const row of rowsBox.children) {
        const [termInput, transInput] = row.querySelectorAll("input");
        if (termInput.value.trim())
          glossary[termInput.value.trim()] = transInput.value.trim();
      }
      return glossary;
    },
    set(glossary) {
      rowsBox.replaceChildren();
      for (const [term, translation] of Object.entries(glossary))
        addRow(term, translation);
    },
    merge(terms) {
      const current = this.get();
      for (const [term, translation] of Object.entries(terms))
        if (!(term in current)) this.addRow(term, translation);
    },
  };
}

export function newTermsBlock(newTerms, glossary) {
  if (!newTerms || !Object.keys(newTerms).length) return null;
  const items = Object.entries(newTerms).map(([term, translation]) =>
    el("li", {}, el("span", { class: "mono" }, term), " → ", translation),
  );
  return el(
    "div",
    { style: "margin-top:12px" },
    el("h3", {}, "New glossary terms"),
    el("ul", {}, items),
    el(
      "button",
      {
        class: "ghost small",
        onclick: (event) => {
          glossary.merge(newTerms);
          event.target.disabled = true;
        },
      },
      "Merge into glossary",
    ),
  );
}

export function dataTable(headers, rows, { scroll = true } = {}) {
  const table = el(
    "table",
    {},
    el("thead", {}, el("tr", {}, ...headers.map((h) => el("th", {}, h)))),
    el("tbody", {}, rows),
  );
  return scroll ? el("div", { class: "table-scroll" }, table) : table;
}

export function dropdown({ options = [], value, onChange } = {}) {
  const label = el("span", { class: "dd-label" });
  const button = el(
    "button",
    {
      type: "button",
      class: "dd-btn",
      "aria-haspopup": "listbox",
      "aria-expanded": "false",
    },
    label,
    el("span", { class: "dd-chev" }, "▾"),
  );
  const list = el("div", { class: "dd-list", role: "listbox" });
  const root = el("div", { class: "dd" }, button, list);

  let items = [];
  let current = "";
  let open = false;
  let activeIndex = -1;
  let typed = "";
  let typedAt = 0;

  function renderLabel() {
    label.textContent = items.find((i) => i.value === current)?.label ?? "";
  }

  function renderList() {
    list.replaceChildren(
      ...items.map((item, index) =>
        el(
          "div",
          {
            class:
              "dd-opt" +
              (item.value === current ? " selected" : "") +
              (index === activeIndex ? " active" : ""),
            role: "option",
            "aria-selected": item.value === current ? "true" : "false",
            onclick: (event) => {
              event.preventDefault();
              choose(index);
            },
          },
          el("span", { class: "dd-check" }, item.value === current ? "✓" : ""),
          item.label,
        ),
      ),
    );
  }

  function setActive(index) {
    activeIndex = Math.max(0, Math.min(items.length - 1, index));
    renderList();
    list.children[activeIndex]?.scrollIntoView({ block: "nearest" });
  }

  function openList() {
    if (open || !items.length) return;
    open = true;
    root.classList.add("open");
    button.setAttribute("aria-expanded", "true");
    activeIndex = Math.max(
      0,
      items.findIndex((i) => i.value === current),
    );
    renderList();
    const rect = root.getBoundingClientRect();
    const below = window.innerHeight - rect.bottom;
    root.classList.toggle(
      "up",
      below < Math.min(list.scrollHeight, 280) + 10 && rect.top > below,
    );
    list.children[activeIndex]?.scrollIntoView({ block: "nearest" });
    document.addEventListener("pointerdown", onOutside);
  }

  function close() {
    if (!open) return;
    open = false;
    activeIndex = -1;
    root.classList.remove("open");
    button.setAttribute("aria-expanded", "false");
    document.removeEventListener("pointerdown", onOutside);
  }

  function onOutside(event) {
    if (!root.contains(event.target)) close();
  }

  function choose(index) {
    const item = items[index];
    if (!item) return;
    const changed = item.value !== current;
    current = item.value;
    renderLabel();
    close();
    button.focus();
    if (changed) onChange?.(current);
  }

  function typeahead(key) {
    const now = Date.now();
    typed = (now - typedAt < 700 ? typed : "") + key.toLowerCase();
    typedAt = now;
    const index = items.findIndex((i) =>
      i.label.toLowerCase().startsWith(typed),
    );
    if (index < 0) return;
    if (open) setActive(index);
    else choose(index);
  }

  button.addEventListener("click", () => (open ? close() : openList()));
  button.addEventListener("keydown", (event) => {
    const { key } = event;
    if (key === "ArrowDown" || key === "ArrowUp") {
      event.preventDefault();
      if (!open) openList();
      else setActive(activeIndex + (key === "ArrowDown" ? 1 : -1));
    } else if (key === "Enter" || key === " ") {
      if (open) {
        event.preventDefault();
        choose(activeIndex);
      }
    } else if (key === "Escape" && open) {
      event.preventDefault();
      close();
    } else if (key === "Home" && open) {
      event.preventDefault();
      setActive(0);
    } else if (key === "End" && open) {
      event.preventDefault();
      setActive(items.length - 1);
    } else if (/^[\p{L}\p{N}]$/u.test(key)) {
      typeahead(key);
    }
  });

  const api = {
    root,
    setOptions(next) {
      items = next;
      if (!items.some((i) => i.value === current))
        current = items[0]?.value ?? "";
      renderLabel();
      if (open) renderList();
    },
    get value() {
      return current;
    },
    set value(v) {
      current = items.some((i) => i.value === v) ? v : (items[0]?.value ?? "");
      renderLabel();
      if (open) renderList();
    },
  };
  api.setOptions(options);
  if (value !== undefined) api.value = value;
  return api;
}

const LANGS = [
  ["en", "English"],
  ["zh", "Chinese (Simplified)"],
  ["zh-Hant", "Chinese (Traditional)"],
  ["ja", "Japanese"],
  ["ko", "Korean"],
  ["es", "Spanish"],
  ["fr", "French"],
  ["de", "German"],
  ["ru", "Russian"],
  ["pt-BR", "Portuguese (Brazil)"],
  ["id", "Indonesian"],
  ["vi", "Vietnamese"],
  ["th", "Thai"],
  ["tr", "Turkish"],
  ["ar", "Arabic"],
  ["hi", "Hindi"],
  ["bn", "Bengali"],
];
const LANG_CODES = new Set(LANGS.map(([code]) => code));

export function langSelect({ auto = false, value = "" } = {}) {
  const custom = el("input", {
    type: "text",
    placeholder: "BCP 47 tag, e.g. pt-PT",
    style: "margin-top:6px;display:none",
  });
  const dd = dropdown({
    options: [
      ...(auto ? [{ value: "", label: "Auto-detect" }] : []),
      ...LANGS.map(([code, name]) => ({
        value: code,
        label: `${name} — ${code}`,
      })),
      { value: "__custom", label: "Other code…" },
    ],
    value: auto ? "" : "en",
    onChange: (v) => {
      const isCustom = v === "__custom";
      custom.style.display = isCustom ? "" : "none";
      if (isCustom) custom.focus();
    },
  });
  const api = {
    root: el("div", {}, dd.root, custom),
    get value() {
      return dd.value === "__custom" ? custom.value.trim() : dd.value;
    },
    set value(v) {
      if (!v) {
        dd.value = auto ? "" : "en";
      } else if (LANG_CODES.has(v)) {
        dd.value = v;
      } else {
        dd.value = "__custom";
        custom.value = v;
      }
      custom.style.display = dd.value === "__custom" ? "" : "none";
    },
  };
  api.value = value;
  return api;
}

export function routeParts() {
  const [path, query] = location.hash.replace(/^#\//, "").split("?");
  return { path, params: new URLSearchParams(query || "") };
}

let prevHash = "";
window.addEventListener("hashchange", (event) => {
  prevHash = new URL(event.oldURL).hash;
});

export function goBack(fallback) {
  location.hash = prevHash && prevHash !== location.hash ? prevHash : fallback;
}
