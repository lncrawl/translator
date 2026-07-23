import { el, toast, busy, confirmDialog } from "../ui.js";
import { store, mutate, keyState } from "../store.js";

export const id = "providers";
export const title = "Providers";
export const glyph = "providers";

let cardsBox;

export function mount(root) {
  cardsBox = el("div", { class: "provider-grid" });
  root.append(
    el(
      "div",
      { class: "page-actions" },
      el(
        "button",
        {
          class: "primary",
          onclick: () => (location.hash = "#/provider-edit"),
        },
        "Add provider",
      ),
    ),
    el(
      "div",
      { class: "card" },
      el(
        "p",
        { class: "hint" },
        "An API account: base URL, API key, and account-wide rate limits shared by all of its engines. Engines stay disabled until their provider's key is set.",
      ),
      cardsBox,
    ),
  );
}

function keyPill(provider) {
  const state = keyState(provider);
  if (state === "set") return el("span", { class: "status-ok" }, "✓ key set");
  if (state === "none-needed")
    return el("span", { class: "status-ok" }, "✓ no key needed");
  return el("span", { class: "status-warn" }, "⚠ key missing");
}

function openEngines(providerId) {
  location.hash = `#/engines?provider=${encodeURIComponent(providerId)}`;
}

export function onStore() {
  const { config } = store;
  if (!config) return;
  const sorted = [...config.providers].sort((a, b) => {
    const rank = (p) => (keyState(p) === "missing" ? 1 : 0);
    return rank(a) - rank(b) || a.id.localeCompare(b.id);
  });
  cardsBox.replaceChildren(
    ...sorted.map((provider) => {
      const limits = [
        provider.rps ? `${provider.rps} req/s` : null,
        provider.rpm ? `${provider.rpm} req/min` : null,
        `concurrency ${provider.max_concurrency}`,
        provider.monthly_chars
          ? `${provider.monthly_chars.toLocaleString()} chars/mo`
          : null,
      ]
        .filter(Boolean)
        .join(" · ");
      const engines = config.engines.filter((e) => e.provider === provider.id);
      const state = keyState(provider) === "missing" ? "missing" : "ok";
      return el(
        "div",
        {
          class: `p-card state-${state}`,
          tabindex: "0",
          role: "link",
          title: `View engines on ${provider.id}`,
          onclick: () => openEngines(provider.id),
          onkeydown: (event) => {
            if (event.key === "Enter" || event.key === " ") {
              event.preventDefault();
              openEngines(provider.id);
            }
          },
        },
        el(
          "div",
          { class: "head" },
          el("span", { class: "name" }, provider.id),
          el("span", { class: "chip" }, provider.kind),
          keyPill(provider),
        ),
        provider.base_url
          ? el("div", { class: "url" }, provider.base_url)
          : null,
        el("div", { class: "facts" }, limits),
        el(
          "div",
          { class: "facts" },
          `${engines.length} engine${engines.length === 1 ? "" : "s"} `,
          el("span", { class: "chev" }, "→"),
        ),
        el(
          "div",
          { class: "foot" },
          el(
            "button",
            {
              class: "ghost small",
              onclick: (event) => {
                event.stopPropagation();
                location.hash = `#/provider-edit?id=${encodeURIComponent(provider.id)}`;
              },
            },
            "Edit",
          ),
          el("span", { class: "spacer" }),
          el(
            "button",
            {
              class: "danger small",
              onclick: (event) => {
                event.stopPropagation();
                remove(event.target, provider);
              },
            },
            "Delete",
          ),
        ),
      );
    }),
  );
}

async function remove(button, provider) {
  const ok = await confirmDialog({
    title: "Delete provider?",
    message: `"${provider.id}" and its account settings will be removed. Its engines stay but lose their key.`,
    confirmLabel: "Delete",
    danger: true,
  });
  if (!ok) return;
  await busy(button, async () => {
    await mutate(`/providers/${encodeURIComponent(provider.id)}`, {
      method: "DELETE",
    });
    toast(`Provider ${provider.id} deleted`);
  });
}
