import {
  el,
  toast,
  busy,
  glossaryEditor,
  newTermsBlock,
  langSelect,
  dropdown,
} from "../ui.js";
import { api } from "../api.js";
import { store } from "../store.js";

export const id = "translate-chapter";
export const title = "Translate chapter";
export const glyph = "☰";

const SAMPLES = {
  zh: {
    label: "Chinese",
    html: `<h1>第一章 陨落的天才</h1>
<p>"斗之力，三段！"</p>
<p>望着测验魔石碑上面闪亮得甚至有些刺眼的五个大字，少年面无表情，唇角有着一抹自嘲。</p>
<p>中年男子看着面前的少年，叹了一口气：<b>萧炎</b>，你可知道，三年前，你还是家族百年来最年轻的斗者？</p>
<p>少年缓缓抬头，露出一张清秀的脸庞，微微一笑："<i>三十年河东，三十年河西，莫欺少年穷。</i>"</p>
<p><img src="images/stone-tablet.jpg" alt=""/></p>
<p>乌坦城位于加玛帝国西北方，城中萧家，曾经也算得上是名门望族。斗气大陆，没有花俏艳丽的魔法，有的，仅仅是繁衍到巅峰的斗气！</p>`,
    novel: "斗破苍穹",
    chapter: "第一章 陨落的天才",
    synopsis:
      "A once-genius young fighter loses his talent and vows to reclaim it.",
    glossary: { 萧炎: "Xiao Yan", 斗之力: "Dou Force", 乌坦城: "Wutan City" },
  },
  ja: {
    label: "Japanese",
    html: `<h1>第一話　異世界への扉</h1>
<p>目を覚ますと、そこは見知らぬ森の中だった。</p>
<p>「ここは……どこだ？」</p>
<p>佐藤健一は頭を押さえながら立ち上がった。昨日までは東京の小さなアパートで暮らす、ごく普通の会社員だったはずだ。</p>
<p>空を見上げると、<b>二つの月</b>が浮かんでいた。それは明らかに、地球ではあり得ない光景だった。</p>
<p>「ステータス・オープン」</p>`,
    novel: "異世界への扉",
    chapter: "第一話　異世界への扉",
    synopsis: "An ordinary office worker wakes up in another world.",
    glossary: { 佐藤健一: "Kenichi Sato" },
  },
  ko: {
    label: "Korean",
    html: `<h1>1화 회귀자의 아침</h1>
<p>눈을 떴을 때, 김도윤은 자신의 옛 방 천장을 보고 있었다.</p>
<p>"……꿈인가?"</p>
<p>손을 들어 보았다. 주름 하나 없는 젊은 손. 이십 년 전, 스무 살의 몸이었다.</p>
<p>분명히 그는 마왕성 최상층에서 죽었다. 동료들의 시체 위에서, 마왕의 검에 심장을 꿰뚫린 채로. 그런데 지금, <b>회귀</b>한 것이다.</p>
<p>도윤은 주먹을 쥐었다. <i>이번에는 아무도 죽게 하지 않는다.</i></p>`,
    novel: "회귀자의 아침",
    chapter: "1화 회귀자의 아침",
    synopsis:
      "A hero who died to the Demon King wakes up twenty years in the past.",
    glossary: { 김도윤: "Kim Do-yoon", 마왕: "Demon King" },
  },
};

const FRAME_STYLE =
  "<style>body{font:16px/1.7 Georgia,serif;margin:16px;max-width:70ch}img{max-width:100%}</style>";

let glossary;
let engineSelect;
let f = {};

export function mount(root) {
  f = {
    input: el("textarea", {
      rows: 12,
      placeholder: "<h1>第一章</h1>\n<p>…</p>",
    }),
    source: langSelect({ auto: true }),
    target: langSelect({ value: "en" }),
    novel: el("input", { type: "text", placeholder: "e.g. 斗破苍穹" }),
    chapter: el("input", { type: "text", placeholder: "e.g. 第一章" }),
    synopsis: el("textarea", {
      rows: 2,
      placeholder: "One or two sentences of story context for the model",
    }),
    extract: el("input", {
      type: "checkbox",
      checked: "",
      style: "width:auto;margin-right:6px",
    }),
  };
  engineSelect = dropdown({
    options: [{ value: "", label: "auto (routing)" }],
  });
  const counter = el("div", { class: "counter" }, "0 characters");
  f.input.addEventListener("input", () => {
    const n = f.input.value.length;
    counter.textContent = `${n.toLocaleString()} character${n === 1 ? "" : "s"}`;
  });

  const swap = el(
    "button",
    {
      class: "icon-btn",
      title: "Swap languages",
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

  /* Results card */
  const resultsMeta = el("span", { class: "meta" });
  const warnings = el("div");
  const newTerms = el("div");
  const frameSource = el("iframe", { class: "preview-frame", sandbox: "" });
  const frameTarget = el("iframe", { class: "preview-frame", sandbox: "" });
  const rawPre = el("pre");
  const rendered = el(
    "div",
    { class: "result-pair" },
    el("div", {}, el("h3", {}, "Source"), frameSource),
    el("div", {}, el("h3", {}, "Translation"), frameTarget),
  );
  const raw = el("div", { style: "display:none" }, rawPre);
  let lastHtml = "";

  const segRendered = el(
    "button",
    {
      class: "active",
      onclick: () => {
        rendered.style.display = "";
        raw.style.display = "none";
        segRendered.classList.add("active");
        segRaw.classList.remove("active");
      },
    },
    "Rendered",
  );
  const segRaw = el(
    "button",
    {
      onclick: () => {
        rendered.style.display = "none";
        raw.style.display = "";
        segRaw.classList.add("active");
        segRendered.classList.remove("active");
      },
    },
    "Raw HTML",
  );
  const resultsCard = el(
    "div",
    { class: "card", style: "display:none" },
    el(
      "div",
      { class: "card-head" },
      el("h2", {}, "Results"),
      el(
        "div",
        { class: "row", style: "gap:8px" },
        el("span", { class: "seg" }, segRendered, segRaw),
        el(
          "button",
          {
            class: "ghost small",
            title: "Copy translated HTML",
            onclick: () =>
              navigator.clipboard
                .writeText(lastHtml)
                .then(() => toast("Copied translated HTML")),
          },
          "⧉ Copy HTML",
        ),
      ),
    ),
    resultsMeta,
    warnings,
    rendered,
    raw,
    newTerms,
  );

  function loadSample(key) {
    const sample = SAMPLES[key];
    f.input.value = sample.html;
    f.novel.value = sample.novel;
    f.chapter.value = sample.chapter;
    f.synopsis.value = sample.synopsis;
    glossary.set(sample.glossary);
    f.input.dispatchEvent(new Event("input"));
    resultsCard.style.display = "none";
  }

  async function translate() {
    const html = f.input.value.trim();
    if (!html) {
      toast("Enter some chapter HTML", "error");
      return;
    }
    const body = {
      html,
      target_lang: f.target.value || "en",
      extract_terms: f.extract.checked,
    };
    if (f.source.value) body.source_lang = f.source.value;
    if (engineSelect.value) body.engine = engineSelect.value;
    const terms = glossary.get();
    if (Object.keys(terms).length) body.glossary = terms;
    const context = {};
    if (f.novel.value.trim()) context.novel_title = f.novel.value.trim();
    if (f.chapter.value.trim()) context.chapter_title = f.chapter.value.trim();
    if (f.synopsis.value.trim()) context.synopsis = f.synopsis.value.trim();
    if (Object.keys(context).length) body.context = context;

    const started = performance.now();
    const result = await api("/translate/html", { method: "POST", body });
    const elapsed = ((performance.now() - started) / 1000).toFixed(1);
    lastHtml = result.html;

    const parts = [`engine: ${result.engine}`];
    if (result.detected_source_lang)
      parts.push(`detected: ${result.detected_source_lang}`);
    parts.push(`${elapsed}s`);
    resultsMeta.textContent = parts.join(" · ");

    warnings.replaceChildren(
      ...result.warnings.map((warning) =>
        el(
          "div",
          { class: "inline-note", style: "margin:8px 0" },
          "⚠ " + warning,
        ),
      ),
    );
    newTerms.replaceChildren(newTermsBlock(result.new_terms, glossary) || "");
    frameSource.srcdoc = FRAME_STYLE + html;
    frameTarget.srcdoc = FRAME_STYLE + result.html;
    rawPre.textContent = result.html;
    resultsCard.style.display = "";
    resultsCard.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }

  root.append(
    el(
      "div",
      { class: "card" },
      el("h2", {}, "Chapter (HTML) translation"),
      el(
        "p",
        { class: "hint" },
        "One chapter per call; markup is preserved and only human-readable text is translated. New glossary terms come back for reuse on the next chapter.",
      ),
      el(
        "div",
        { class: "field-toolbar" },
        el("span", { class: "fl" }, "Chapter HTML"),
        el(
          "span",
          { class: "row", style: "gap:6px;align-items:center" },
          el("span", { class: "meta", style: "margin:0" }, "Samples:"),
          ...Object.entries(SAMPLES).map(([key, sample]) =>
            el(
              "button",
              { class: "ghost small", onclick: () => loadSample(key) },
              sample.label,
            ),
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
          "Options",
          el(
            "span",
            { class: "meta", style: "margin:0" },
            "engine · story context · glossary",
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
            "div",
            { class: "row", style: "margin-top:10px" },
            el(
              "label",
              { class: "field" },
              el("span", {}, "Novel title"),
              f.novel,
            ),
            el(
              "label",
              { class: "field" },
              el("span", {}, "Chapter title"),
              f.chapter,
            ),
          ),
          el(
            "label",
            { class: "field", style: "margin-top:10px" },
            el("span", {}, "Synopsis (context)"),
            f.synopsis,
          ),
          el(
            "label",
            { class: "field" },
            el("span", {}, f.extract, "Extract new glossary terms"),
          ),
          el("h3", {}, "Glossary"),
          glossaryRoot,
        ),
      ),
      el(
        "div",
        { class: "actions" },
        el(
          "button",
          {
            class: "primary cta",
            onclick: (event) => busy(event.target, translate),
          },
          "Translate chapter",
        ),
      ),
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
