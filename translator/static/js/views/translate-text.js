import {
  el,
  toast,
  busy,
  copyText,
  glossaryEditor,
  newTermsBlock,
  dataTable,
  langSelect,
  dropdown,
} from "../ui.js";
import { icon } from "../icons.js";
import { api } from "../api.js";
import { store } from "../store.js";

export const id = "translate-text";
export const title = "Translate text";
export const glyph = "text";

const SAMPLE = [
  "斗破苍穹",
  "天蚕土豆",
  "玄幻",
  "热血",
  "这里是属于斗气的世界，没有花俏艳丽的魔法，有的，仅仅是繁衍到巅峰的斗气！",
];

let glossary;
let engineSelect;
let f = {};

function textLines() {
  return f.input.value
    .split("\n")
    .map((s) => s.trim())
    .filter(Boolean);
}

export function mount(root) {
  f = {
    input: el("textarea", {
      rows: 7,
      placeholder: "One item per line — titles, tags, author names…",
    }),
    source: langSelect({ auto: true, ariaLabel: "Source language" }),
    target: langSelect({ value: "en", ariaLabel: "Target language" }),
    context: el("textarea", {
      rows: 2,
      placeholder: "e.g. items from a xianxia novel about cultivation",
    }),
  };
  engineSelect = dropdown({
    ariaLabel: "Engine",
    options: [{ value: "", label: "auto (routing)" }],
  });
  const counter = el("div", { class: "counter" }, "0 lines");
  f.input.addEventListener("input", () => {
    const n = textLines().length;
    counter.textContent = `${n} line${n === 1 ? "" : "s"}${n > 500 ? " — over the 500 limit" : ""}`;
    counter.classList.toggle("over", n > 500);
  });

  const swap = el(
    "button",
    {
      class: "icon-btn",
      title: "Swap languages",
      "aria-label": "Swap source and target languages",
      onclick: () => {
        if (!f.source.value) {
          toast("Set a source language to swap", "error");
          return;
        }
        [f.source.value, f.target.value] = [f.target.value, f.source.value];
      },
    },
    "⇄",
  );

  const glossaryRoot = el("div");
  glossary = glossaryEditor(glossaryRoot);

  const resultsMeta = el("span", { class: "meta" });
  const resultsBody = el("div");
  const copyAll = el(
    "button",
    { class: "ghost small", onclick: () => copyTranslations() },
    "Copy all",
  );
  const resultsCard = el(
    "div",
    { class: "card", style: "display:none" },
    el("div", { class: "card-head" }, el("h2", {}, "Results"), copyAll),
    resultsMeta,
    resultsBody,
  );
  let lastTranslations = [];

  function copyTranslations() {
    copyText(lastTranslations.join("\n"), "Copied all translations");
  }

  async function translate() {
    const texts = textLines();
    if (!texts.length) {
      toast("Enter at least one line of text", "error");
      return;
    }
    const body = { texts, target_lang: f.target.value || "en" };
    if (f.source.value) body.source_lang = f.source.value;
    if (f.context.value.trim()) body.context = f.context.value.trim();
    if (engineSelect.value) body.engine = engineSelect.value;
    const terms = glossary.get();
    if (Object.keys(terms).length) body.glossary = terms;

    const started = performance.now();
    const result = await api("/translate/text", { method: "POST", body });
    const elapsed = ((performance.now() - started) / 1000).toFixed(1);
    lastTranslations = result.translations;

    const parts = [
      `${texts.length} item${texts.length === 1 ? "" : "s"}`,
      `engine: ${result.engine}`,
    ];
    if (result.detected_source_lang)
      parts.push(`detected: ${result.detected_source_lang}`);
    parts.push(`${elapsed}s`);
    resultsMeta.textContent = parts.join(" · ");

    resultsBody.replaceChildren(
      dataTable(
        ["Source", "Translation", ""],
        texts.map((text, i) =>
          el(
            "tr",
            {},
            el("td", {}, text),
            el("td", {}, result.translations[i] ?? ""),
            el(
              "td",
              { style: "white-space:nowrap" },
              el(
                "button",
                {
                  class: "ghost small",
                  title: "Copy translation",
                  "aria-label": "Copy translation",
                  onclick: () => copyText(result.translations[i] ?? ""),
                },
                "⧉",
              ),
            ),
          ),
        ),
        { scroll: false },
      ),
      newTermsBlock(result.new_terms, glossary) || "",
    );
    resultsCard.style.display = "";
    resultsCard.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }

  const translateBtn = el(
    "button",
    {
      class: "primary cta",
      onclick: (event) => busy(event.target, translate),
    },
    "Translate",
  );
  f.input.addEventListener("keydown", (event) => {
    if ((event.metaKey || event.ctrlKey) && event.key === "Enter") {
      event.preventDefault();
      busy(translateBtn, translate);
    }
  });

  root.append(
    el(
      "div",
      { class: "card" },
      el("h2", {}, "Short-text translation"),
      el(
        "p",
        { class: "hint" },
        "Batch-translate titles, tags, author names, or synopsis lines — one item per line, up to 500 per request.",
      ),
      el(
        "div",
        { class: "field-toolbar" },
        el("span", { class: "fl" }, "Texts (one per line)"),
        el(
          "span",
          { class: "row", style: "gap:6px" },
          el(
            "button",
            {
              class: "ghost small",
              onclick: () => {
                f.input.value = SAMPLE.join("\n");
                f.context.value = "Metadata of a Chinese xianxia web novel";
                glossary.set({
                  斗气: "Dou Qi",
                  斗破苍穹: "Battle Through the Heavens",
                });
                f.input.dispatchEvent(new Event("input"));
              },
            },
            "Load sample",
          ),
          el(
            "button",
            {
              class: "ghost small",
              onclick: () => {
                f.input.value = "";
                f.input.dispatchEvent(new Event("input"));
              },
            },
            "Clear",
          ),
        ),
      ),
      f.input,
      counter,
      el(
        "div",
        { class: "lang-row" },
        el(
          "label",
          { class: "field" },
          el("span", {}, "Source language"),
          f.source.root,
        ),
        swap,
        el(
          "label",
          { class: "field" },
          el("span", {}, "Target language"),
          f.target.root,
        ),
      ),
      el(
        "details",
        { class: "opts" },
        el(
          "summary",
          {},
          el("span", { class: "opts-chev", "aria-hidden": "true" }, icon("chevron", 15)),
          "Options",
          el(
            "span",
            { class: "meta", style: "margin:0" },
            "engine · context · glossary",
          ),
        ),
        el(
          "div",
          { class: "opts-body" },
          el(
            "label",
            { class: "field" },
            el("span", {}, "Engine"),
            engineSelect.root,
          ),
          el(
            "label",
            { class: "field" },
            el("span", {}, "Context (optional)"),
            f.context,
          ),
          el("h3", {}, "Glossary"),
          glossaryRoot,
        ),
      ),
      el("div", { class: "actions" }, translateBtn),
    ),
    resultsCard,
  );
}

export function onStore() {
  engineSelect.setOptions([
    { value: "", label: "auto (routing)" },
    ...store.engines
      .filter((engine) => engine.status !== "disabled")
      .map((engine) => ({
        value: engine.id,
        label:
          `${engine.id} · ${engine.provider}` +
          (engine.status === "ok" ? "" : ` — ${engine.status}`),
      })),
  ]);
}
