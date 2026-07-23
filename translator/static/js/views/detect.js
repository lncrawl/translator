import { el, toast, busy, lines, dataTable } from "../ui.js";
import { api } from "../api.js";

export const id = "detect";
export const title = "Detect language";
export const glyph = "detect";

export function mount(root) {
  const input = el("textarea", {
    rows: 6,
    placeholder: "안녕하세요\n你好，世界\nこんにちは",
  });
  const results = el("div");

  async function detect() {
    const texts = lines(input);
    if (!texts.length) {
      toast("Enter at least one line of text", "error");
      return;
    }
    const body = await api("/detect", { method: "POST", body: { texts } });
    results.replaceChildren(
      dataTable(
        ["Text", "Language", "Confidence"],
        body.results.map((result, i) =>
          el(
            "tr",
            {},
            el("td", {}, texts[i]),
            el("td", {}, el("span", { class: "mono" }, result.language)),
            el(
              "td",
              {},
              el(
                "div",
                { class: "row", style: "align-items:center" },
                el(
                  "div",
                  { class: "bar" },
                  el("div", {
                    style: `width:${Math.round(result.confidence * 100)}%`,
                  }),
                ),
                `${(result.confidence * 100).toFixed(0)}%`,
              ),
            ),
          ),
        ),
        { scroll: false },
      ),
    );
  }

  root.append(
    el(
      "div",
      { class: "card" },
      el("h2", {}, "Language detection"),
      el(
        "p",
        { class: "hint" },
        "Local detection — costs no engine quota, one line per text (",
        el("code", {}, "POST /detect"),
        ").",
      ),
      el(
        "label",
        { class: "field" },
        el("span", {}, "Texts (one per line)"),
        input,
      ),
      el(
        "div",
        { class: "actions" },
        el(
          "button",
          { class: "primary", onclick: (event) => busy(event.target, detect) },
          "Detect",
        ),
        el(
          "button",
          {
            class: "ghost",
            onclick: () => {
              input.value = [
                "斗气大陆，没有花俏艳丽的魔法。",
                "目を覚ますと、そこは見知らぬ森の中だった。",
                "눈을 떴을 때, 김도윤은 자신의 옛 방 천장을 보고 있었다.",
                "The quick brown fox jumps over the lazy dog.",
              ].join("\n");
            },
          },
          "Load sample",
        ),
      ),
      results,
    ),
  );
}

export function onStore() {}
