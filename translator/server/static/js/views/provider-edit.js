import { splitForm } from "../schema-form.js";
import { kindNames, kindSchema, mutate, store } from "../store.js";
import { busy, dropdown, el, goBack, routeParts, toast } from "../ui.js";

export const id = "provider-edit";
export const title = "Provider";
export const parent = "providers";
export const glyph = "providers";

let box;
let pending = false;
let getState = null;
let baseline = "";

export function guardLeave() {
  return getState && getState() !== baseline
    ? "You have unsaved changes to this provider."
    : null;
}

export function mount(root) {
  box = el("div", { class: "edit-page" });
  root.append(box);
}

export function onShow() {
  if (store.config) {
    pending = false;
    render();
  } else {
    pending = true;
    box.replaceChildren(el("div", { class: "inline-note" }, "Loading…"));
  }
}

export function onStore() {
  if (pending && store.config && routeParts().path === id) {
    pending = false;
    render();
  }
}

function field(label, input) {
  return el("label", { class: "field" }, el("span", {}, label), input);
}

function render() {
  getState = null;
  const wanted = routeParts().params.get("id") || "";
  const provider = store.config.providers.find((p) => p.id === wanted) || null;
  document.querySelector("#page-title").textContent = provider
    ? `Provider: ${provider.id}`
    : "New provider";

  if (wanted && !provider) {
    box.replaceChildren(
      el(
        "div",
        { class: "card" },
        el("h2", {}, "Not found"),
        el("p", { class: "hint" }, `No provider with id ${wanted}.`),
        el(
          "div",
          { class: "actions" },
          el("a", { class: "back-link", href: "#/providers" }, "← Providers"),
        ),
      ),
    );
    return;
  }

  const idInput = el("input", {
    type: "text",
    value: provider?.id ?? "",
    disabled: provider ? "" : null,
    placeholder: "e.g. openrouter",
  });
  const kindSelect = dropdown({
    ariaLabel: "Provider kind",
    options: kindNames().map((k) => ({ value: k, label: k })),
    value: provider?.kind || kindNames()[0] || "openai",
    onChange: () => renderSettings(),
  });

  const settingsBox = el("div", {});
  let own = null; // fields this kind adds
  let shared = null; // the ProviderSettings base every kind inherits

  function renderSettings() {
    ({ own, shared } = splitForm(
      kindSchema(kindSelect.value)?.provider_settings,
      store.schema.provider,
      provider?.settings ?? {},
      { placeholders: { failure_policy: store.config.failure_policy } },
    ));
    // "Requires an API key" sits with the credentials it gates, not with the
    // account limits it is declared among.
    const keyToggle = shared.field("requires_key");
    keyToggle?.control.node.addEventListener("change", applyKeyless);

    const credentials = own.fields.filter((f) => f.credential);
    const settings = own.fields.filter((f) => !f.credential).map((f) => f.row);
    if (credentials.length > 0) {
      settings.push(keyToggle.row, ...credentials.map((f) => f.row));
    }
    if (settings.length > 0) {
      settings.unshift(el("h3", { style: "margin:18px 0 8px" }, "Settings"));
    }

    const limits = shared.fields
      .filter((f) => f !== keyToggle)
      .map((f) => f.row);
    if (limits.length > 0) {
      limits.unshift(
        el("h3", { style: "margin:18px 0 8px" }, "Account limits"),
      );
    }

    settingsBox.replaceChildren(...settings, ...limits);
    applyKeyless();
  }

  // A keyless host has nothing to authenticate with, so hide the credential
  // inputs rather than leaving boxes that can never matter.
  function applyKeyless() {
    const wanted = shared.field("requires_key")?.control.read() !== false;
    for (const f of own.fields) {
      if (f.credential) f.row.hidden = !wanted;
    }
  }

  renderSettings();

  const collect = () =>
    JSON.stringify([
      idInput.value,
      kindSelect.value,
      own.snapshot(),
      shared.snapshot(),
    ]);
  baseline = collect();
  getState = collect;
  const leave = () => {
    getState = null; // navigating intentionally — don't trip the guard
    goBack("#/providers");
  };

  const save = el(
    "button",
    {
      class: "primary",
      onclick: (event) =>
        busy(event.target, async () => {
          const payload = {
            kind: kindSelect.value,
            settings: { ...own.collect(), ...shared.collect() },
          };
          if (provider) {
            await mutate(`/providers/${encodeURIComponent(provider.id)}`, {
              method: "PATCH",
              body: payload,
            });
            toast(`Provider ${provider.id} updated`);
          } else {
            const newId = idInput.value.trim();
            if (!newId) {
              toast("Provider id is required", "error");
              return;
            }
            await mutate("/providers", {
              method: "POST",
              body: { id: newId, ...payload },
            });
            toast(`Provider ${newId} created`);
          }
          leave();
        }),
    },
    "Save",
  );

  box.replaceChildren(
    el(
      "a",
      {
        class: "back-link",
        href: "#/providers",
        onclick: (event) => {
          event.preventDefault();
          leave();
        },
      },
      "← Back",
    ),
    el(
      "div",
      { class: "card" },
      el("h2", {}, provider ? `Edit ${provider.id}` : "New provider"),
      el(
        "p",
        { class: "hint" },
        "An API account: endpoint, credentials, and account-wide rate limits shared by all of its engines.",
      ),
      el(
        "div",
        { class: "row" },
        field("Id", idInput),
        field("Kind", kindSelect.root),
      ),
      settingsBox,
      el(
        "div",
        { class: "actions" },
        save,
        el("button", { class: "ghost", onclick: () => leave() }, "Cancel"),
      ),
    ),
  );
}
