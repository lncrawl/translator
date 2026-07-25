import { el, toast, busy, routeParts, goBack, dropdown } from "../ui.js";
import { store, mutate, kindSchema, kindNames } from "../store.js";
import { schemaForm } from "../schema-form.js";

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

  const onChange = () => {};
  const settingsBox = el("div", {});
  let own = null; // fields this kind adds
  let shared = null; // the ProviderSettings base every kind inherits
  let credentialNote = null;

  // The base's field names, so inherited account-level settings can be grouped
  // apart from the endpoint and credentials the kind itself declares.
  const sharedNames = Object.keys(store.schema.provider?.properties || {});

  function renderSettings() {
    const kind = kindSchema(kindSelect.value);
    const schema = kind?.provider_settings;
    const values = provider?.settings ?? {};
    own = schemaForm(schema, values, { onChange, omit: sharedNames });
    shared = schemaForm(schema, values, {
      onChange: () => {
        onChange();
        applyKeyless();
      },
      omit: Object.keys(schema?.properties || {}).filter(
        (n) => !sharedNames.includes(n),
      ),
      // An empty override box shows the value it would inherit.
      placeholders: {
        failure_policy: store.config.failure_policy,
      },
    });
    const credentials = own.fields.filter((f) => f.credential);
    const endpoint = own.fields.filter((f) => !f.credential);
    credentialNote = el(
      "p",
      { class: "hint", style: "margin:6px 0 0" },
      "Credentials are stored in the config file and are write-only: once saved they are never shown again. Engines on this provider stay disabled until they are set.",
    );
    // "Requires an API key" only means something for a kind that has one, so
    // for a kind like bing it is left out entirely rather than shown as a
    // toggle that changes nothing. Its control still collects (the row is
    // simply never appended), so the stored value round-trips untouched.
    const gated = credentials.length
      ? [
          shared.field("requires_key").row,
          ...credentials.map((f) => f.row),
          credentialNote,
        ]
      : [];
    const limits = shared.fields
      .filter((f) => f.name !== "requires_key")
      .map((f) => f.row);

    settingsBox.replaceChildren(
      ...[
        el("h3", { style: "margin:18px 0 8px" }, "Settings"),
        ...endpoint.map((f) => f.row),
        ...gated,
        el("h3", { style: "margin:18px 0 8px" }, "Account limits"),
        ...limits,
      ].filter(Boolean),
    );
    applyKeyless();
  }

  // A keyless host has nothing to authenticate with, so hide the credential
  // inputs — and the note explaining them — rather than leaving boxes that can
  // never matter next to advice that does not apply.
  function applyKeyless() {
    const wanted = shared.field("requires_key")?.control.read() !== false;
    for (const f of own.fields) {
      if (f.credential) f.row.hidden = !wanted;
    }
    if (credentialNote) credentialNote.hidden = !wanted;
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
