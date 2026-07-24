import { keyState, liveEngine, mutate, store } from "../store.js";
import {
  busy,
  confirmDialog,
  dropdown,
  el,
  routeParts,
  statusPill,
  toast,
} from "../ui.js";

export const id = "engines";
export const title = "Engines";
export const glyph = "engines";

let tableBox;
let filterSelect;
let filterProvider = "";

export function mount(root) {
  tableBox = el("div");
  filterSelect = dropdown({
    ariaLabel: "Filter engines by provider",
    options: [{ value: "", label: "All providers" }],
    onChange: (value) => {
      location.hash = value
        ? `#/engines?provider=${encodeURIComponent(value)}`
        : "#/engines";
    },
  });
  filterSelect.root.style.width = "190px";
  root.append(
    el(
      "div",
      { class: "spread" },
      el(
        "div",
        { class: "hint", style: "flex:1" },
        "One model on one provider — what the routing lanes reference. Status combines config, key presence, cooldowns, and quota state.",
      ),
      el(
        "div",
        { class: "page-actions", style: "flex-shrink: 0" },
        filterSelect.root,
        el(
          "button",
          {
            class: "primary",
            onclick: () => {
              if (!store.config?.providers.length) {
                toast("Create a provider first", "error");
                return;
              }
              location.hash = filterProvider
                ? `#/engine-edit?provider=${encodeURIComponent(filterProvider)}`
                : "#/engine-edit";
            },
          },
          "Add engine",
        ),
      ),
    ),
    tableBox,
  );
}

export function onShow() {
  const wanted = routeParts().params.get("provider") || "";
  if (wanted !== filterProvider) {
    filterProvider = wanted;
    onStore();
  }
}

function renderFilter() {
  filterSelect.setOptions([
    { value: "", label: "All providers" },
    ...store.config.providers.map((p) => ({
      value: p.id,
      label: `Provider: ${p.id}`,
    })),
  ]);
  filterSelect.value = store.config.providers.some(
    (p) => p.id === filterProvider,
  )
    ? filterProvider
    : "";
}

function cardState(status) {
  if (!status || status === "disabled") return "off";
  if (status === "ok") return "ok";
  return "attention";
}

export function onStore() {
  const { config } = store;
  if (!config) return;
  renderFilter();
  const visible = (
    filterProvider
      ? config.engines.filter((e) => e.provider === filterProvider)
      : [...config.engines]
  ).sort((a, b) => {
    const ready = (e) => (liveEngine(e.id)?.status === "ok" ? 0 : 1);
    return ready(a) - ready(b) || a.id.localeCompare(b.id);
  });
  const cards = visible.map((engine) => {
    const live = liveEngine(engine.id);
    const caps = live?.capabilities;
    const facts = [
      caps ? `html: ${caps.html}` : null,
      caps ? `glossary: ${caps.glossary ? "yes" : "no"}` : null,
      engine.max_input_tokens
        ? `≤ ${engine.max_input_tokens.toLocaleString()} tokens`
        : null,
    ]
      .filter(Boolean)
      .join(" · ");
    const provider = config.providers.find((p) => p.id === engine.provider);
    const providerReady = provider && keyState(provider) !== "missing";
    const toggle = providerReady
      ? el(
          "button",
          {
            class: "ghost small",
            onclick: (event) =>
              busy(event.target, async () => {
                await mutate(`/engines/${encodeURIComponent(engine.id)}`, {
                  method: "PATCH",
                  body: { enabled: !engine.enabled },
                });
                toast(
                  `${engine.id} ${engine.enabled ? "disabled" : "enabled"}`,
                );
              }),
          },
          engine.enabled ? "Disable" : "Enable",
        )
      : el(
          "a",
          {
            class: "facts",
            href: `#/provider-edit?id=${encodeURIComponent(engine.provider)}`,
            title: `Set the API key for ${engine.provider}`,
          },
          "⚠ missing key",
        );
    return el(
      "div",
      { class: `p-card static state-${cardState(live?.status)}` },
      el(
        "div",
        { class: "head" },
        el("span", { class: "name" }, engine.id),
        el("span", { class: "chip" }, engine.provider),
        live ? statusPill(live.status) : statusPill("disabled"),
      ),
      engine.model ? el("div", { class: "url" }, engine.model) : null,
      facts ? el("div", { class: "facts" }, facts) : null,
      live?.retry_at
        ? el(
            "div",
            { class: "facts" },
            `retries ${new Date(live.retry_at).toLocaleTimeString()}`,
          )
        : null,
      el(
        "div",
        { class: "foot" },
        toggle,
        el(
          "button",
          {
            class: "ghost small",
            onclick: () =>
              (location.hash = `#/engine-edit?id=${encodeURIComponent(engine.id)}`),
          },
          "Edit",
        ),
        el("span", { class: "spacer" }),
        el(
          "button",
          {
            class: "danger small",
            onclick: (event) => remove(event.target, engine),
          },
          "Delete",
        ),
      ),
    );
  });
  tableBox.replaceChildren(
    cards.length
      ? el("div", { class: "provider-grid" }, cards)
      : el(
          "div",
          { class: "inline-note" },
          filterProvider
            ? `No engines on provider "${filterProvider}" yet.`
            : "No engines configured.",
        ),
  );
}

async function remove(button, engine) {
  const ok = await confirmDialog({
    title: "Delete engine?",
    message: `"${engine.id}" will be removed and dropped from every routing lane.`,
    confirmLabel: "Delete",
    danger: true,
  });
  if (!ok) return;
  await busy(button, async () => {
    await mutate(`/engines/${encodeURIComponent(engine.id)}`, {
      method: "DELETE",
    });
    toast(`Engine ${engine.id} deleted`);
  });
}
