import { el, statusPill, dataTable } from "../ui.js";
import { store, keyState } from "../store.js";

export const id = "dashboard";
export const title = "Dashboard";
export const glyph = "◧";

let statsBox;
let enginesBox;
let noteBox;

export function mount(root) {
  statsBox = el("div", { class: "stats" });
  noteBox = el("div");
  enginesBox = el("div");
  root.append(
    noteBox,
    statsBox,
    el(
      "div",
      { class: "card" },
      el("h2", {}, "Engine status"),
      el(
        "p",
        { class: "hint" },
        "Live routing eligibility, cooldowns, and quota state.",
      ),
      enginesBox,
    ),
  );
}

function stat(label, value, sub, href) {
  return el(
    href ? "a" : "div",
    href ? { class: "stat link", href } : { class: "stat" },
    el("div", { class: "label" }, label),
    el("div", { class: "value" }, value),
    sub ? el("div", { class: "sub" }, sub) : null,
  );
}

export function onStore() {
  const { config, engines, health, reachable } = store;
  if (!config) return;

  const ready = engines.filter((e) => e.status === "ok");
  const keyed = config.providers.filter((p) => keyState(p) !== "missing");
  const service = !reachable
    ? "unreachable"
    : health?.status === "ok"
      ? "ok"
      : "unconfigured";

  statsBox.replaceChildren(
    stat("Service", service, health?.version ? `v${health.version}` : null),
    stat(
      "Engines ready",
      `${ready.length} / ${engines.length}`,
      null,
      "#/engines",
    ),
    stat(
      "Providers keyed",
      `${keyed.length} / ${config.providers.length}`,
      null,
      "#/providers",
    ),
    stat(
      "Chapter lane",
      config.routing.chapter.find((i) => ready.some((e) => e.id === i)) || "—",
      "first eligible engine",
      "#/routing",
    ),
    stat(
      "Short-text lane",
      config.routing.short_text.find((i) => ready.some((e) => e.id === i)) ||
        "—",
      "first eligible engine",
      "#/routing",
    ),
  );

  const missing = config.providers.filter((p) => keyState(p) === "missing");
  noteBox.replaceChildren(
    missing.length
      ? el(
          "div",
          { class: "inline-note", style: "margin-bottom:16px" },
          `${missing.length} provider${missing.length === 1 ? "" : "s"} ` +
            `waiting for an API key (${missing.map((p) => p.id).join(", ")}) — ` +
            "add keys on the ",
          el("a", { href: "#/providers" }, "Providers"),
          " page to unlock more engines.",
        )
      : "",
  );

  const rows = engines.map((engine) =>
    el(
      "tr",
      {},
      el("td", {}, el("span", { class: "mono" }, engine.id)),
      el("td", {}, engine.provider),
      el("td", {}, engine.model || "—"),
      el(
        "td",
        {},
        statusPill(engine.status),
        engine.retry_at
          ? el(
              "div",
              { class: "meta" },
              `retry ${new Date(engine.retry_at).toLocaleTimeString()}`,
            )
          : null,
      ),
    ),
  );
  enginesBox.replaceChildren(
    engines.length
      ? dataTable(["Engine", "Provider", "Model", "Status"], rows)
      : el("div", { class: "inline-note" }, "No engines configured."),
  );
}
