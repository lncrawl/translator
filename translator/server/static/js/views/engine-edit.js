import { el, toast, busy, routeParts, goBack, dropdown } from "../ui.js";
import { store, mutate, kindSchema } from "../store.js";
import { schemaForm, splitForm } from "../schema-form.js";

export const id = "engine-edit";
export const title = "Engine";
export const parent = "engines";
export const glyph = "engines";

let box;
let pending = false;
let getState = null;
let baseline = "";

export function guardLeave() {
  return getState && getState() !== baseline
    ? "You have unsaved changes to this engine."
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
  const params = routeParts().params;
  const wanted = params.get("id") || "";
  const engine = store.config.engines.find((e) => e.id === wanted) || null;
  document.querySelector("#page-title").textContent = engine
    ? `Engine: ${engine.id}`
    : "New engine";
  if (wanted && !engine) {
    box.replaceChildren(
      el(
        "div",
        { class: "card" },
        el(
          "div",
          { class: "inline-note" },
          `Engine "${wanted}" no longer exists.`,
        ),
        el(
          "div",
          { class: "actions" },
          el("a", { class: "back-link", href: "#/engines" }, "← Engines"),
        ),
      ),
    );
    return;
  }
  if (!store.config.providers.length) {
    box.replaceChildren(
      el(
        "div",
        { class: "card" },
        el(
          "div",
          { class: "inline-note" },
          "Create a provider first — every engine runs on one.",
        ),
        el(
          "div",
          { class: "actions" },
          el(
            "a",
            { class: "back-link", href: "#/provider-edit" },
            "→ New provider",
          ),
        ),
      ),
    );
    return;
  }

  const idInput = el("input", {
    type: "text",
    value: engine?.id ?? "",
    disabled: engine ? "" : null,
    placeholder: "e.g. glm-flash",
  });
  const providerSelect = dropdown({
    ariaLabel: "Provider",
    options: store.config.providers.map((p) => ({ value: p.id, label: p.id })),
    onChange: () => renderSettings(),
  });
  providerSelect.value =
    engine?.provider || params.get("provider") || providerSelect.value;

  const settingsBox = el("div", {});
  let own = null; // settings this kind adds
  let shared = null; // the EngineSettings base every kind inherits

  function selectedProvider() {
    return store.config.providers.find((p) => p.id === providerSelect.value);
  }

  // An empty override box shows what it would inherit: the provider's own
  // override where it has one, otherwise the global policy.
  function inheritedPolicy() {
    const fromProvider = selectedProvider()?.settings?.failure_policy || {};
    return {
      ...store.config.failure_policy,
      ...Object.fromEntries(
        Object.entries(fromProvider).filter(([, v]) => v != null),
      ),
    };
  }

  function renderSettings() {
    ({ own, shared } = splitForm(
      kindSchema(selectedProvider()?.kind)?.engine_settings,
      store.schema.engine,
      engine?.settings ?? {},
      { placeholders: { failure_policy: inheritedPolicy() } },
    ));
    settingsBox.replaceChildren(
      ...own.rows,
      el("h3", { style: "margin:18px 0 8px" }, "Limits and routing"),
      ...shared.rows,
    );
  }

  const entry = schemaForm(store.schema.engine_entry, engine ?? {});
  renderSettings();

  const collect = () =>
    JSON.stringify([
      idInput.value,
      providerSelect.value,
      entry.snapshot(),
      own.snapshot(),
      shared.snapshot(),
    ]);
  baseline = collect();
  getState = collect;
  const leave = () => {
    getState = null; // navigating intentionally — don't trip the guard
    goBack("#/engines");
  };

  const save = el(
    "button",
    {
      class: "primary",
      onclick: (event) =>
        busy(event.target, async () => {
          let payload;
          try {
            payload = {
              ...entry.collect(),
              provider: providerSelect.value,
              settings: { ...own.collect(), ...shared.collect() },
            };
          } catch {
            toast("A JSON field is not valid JSON", "error");
            return;
          }
          if (engine) {
            await mutate(`/engines/${encodeURIComponent(engine.id)}`, {
              method: "PATCH",
              body: payload,
            });
            toast(`Engine ${engine.id} updated`);
          } else {
            const newId = idInput.value.trim();
            if (!newId) {
              toast("Engine id is required", "error");
              return;
            }
            await mutate("/engines", {
              method: "POST",
              body: { id: newId, ...payload },
            });
            toast(`Engine ${newId} created`);
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
        href: "#/engines",
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
      el("h2", {}, engine ? `Edit ${engine.id}` : "New engine"),
      el(
        "p",
        { class: "hint" },
        "One model on one provider — what the routing lanes reference.",
      ),
      el(
        "div",
        { class: "row" },
        field("Id", idInput),
        field("Provider", providerSelect.root),
      ),
      ...entry.rows,
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
