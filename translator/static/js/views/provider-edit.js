import {
  el,
  toast,
  busy,
  numberOrNull,
  routeParts,
  goBack,
  dropdown,
} from "../ui.js";
import { icon } from "../icons.js";
import { store, mutate } from "../store.js";

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
        el(
          "div",
          { class: "inline-note" },
          `Provider "${wanted}" no longer exists.`,
        ),
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
    options: ["openai", "deepl", "bing", "baidu"].map((k) => ({
      value: k,
      label: k,
    })),
    value: provider?.kind || "openai",
    onChange: () => renderCreds(),
  });
  const baseUrlInput = el("input", {
    type: "text",
    value: provider?.base_url || "",
    placeholder: "https://api.example.com/v1",
  });
  const reqKeyInput = el("input", {
    type: "checkbox",
    checked: (provider ? provider.requires_key !== false : true) ? "" : null,
    style: "width:auto;margin-right:6px",
    onchange: () => renderCreds(),
  });
  const rpsInput = el("input", {
    type: "number",
    min: "0",
    step: "0.1",
    value: provider?.rps ?? "",
  });
  const rpmInput = el("input", {
    type: "number",
    min: "0",
    step: "1",
    value: provider?.rpm ?? "",
  });
  const concInput = el("input", {
    type: "number",
    min: "1",
    step: "1",
    value: provider?.max_concurrency ?? 1,
  });
  const monthlyInput = el("input", {
    type: "number",
    min: "0",
    step: "1000",
    value: provider?.monthly_chars ?? "",
  });

  // Credentials are declared per kind by the backend (/credential-schema) and
  // rendered dynamically; the eye toggle reveals a secret input.
  const reqKeyRow = el(
    "label",
    { class: "field" },
    el(
      "span",
      {},
      reqKeyInput,
      "Requires an API key (uncheck for keyless local servers)",
    ),
  );
  const credsBox = el("div", {});
  let credInputs = {};

  const schemaFields = () => store.credentialSchema[kindSelect.value] || [];

  function initialValue(key) {
    if (!provider) return "";
    if (key === "api_key") return provider.api_key || "";
    return provider.options?.[key] || "";
  }

  function secretControl(input) {
    const button = el(
      "button",
      {
        type: "button",
        class: "ghost small",
        "aria-label": "Show value",
        onclick: () => {
          const reveal = input.type === "password";
          input.type = reveal ? "text" : "password";
          button.replaceChildren(icon(reveal ? "eye-off" : "eye", 16));
          button.setAttribute(
            "aria-label",
            reveal ? "Hide value" : "Show value",
          );
        },
      },
      icon("eye", 16),
    );
    return el(
      "div",
      { style: "display:flex;gap:6px;align-items:center" },
      input,
      button,
    );
  }

  function renderCreds() {
    const fields = schemaFields();
    reqKeyRow.style.display = fields.length ? "" : "none";
    credInputs = {};
    if (!fields.length || !reqKeyInput.checked) {
      credsBox.replaceChildren();
      return;
    }
    credsBox.replaceChildren(
      ...fields.map((f) => {
        const input = el("input", {
          type: f.secret ? "password" : "text",
          value: initialValue(f.key),
          autocomplete: "off",
          placeholder: f.secret ? "paste token" : "",
          style: "flex:1;min-width:0",
        });
        credInputs[f.key] = input;
        return el(
          "label",
          { class: "field" },
          el("span", {}, f.label),
          f.secret ? secretControl(input) : input,
          f.description ? el("small", { class: "hint" }, f.description) : null,
        );
      }),
    );
  }

  renderCreds();

  const collect = () =>
    JSON.stringify([
      idInput.value,
      kindSelect.value,
      baseUrlInput.value,
      reqKeyInput.checked,
      rpsInput.value,
      rpmInput.value,
      concInput.value,
      monthlyInput.value,
      Object.fromEntries(
        Object.entries(credInputs).map(([k, input]) => [k, input.value]),
      ),
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
          const options = {};
          let apiKey = null;
          for (const f of schemaFields()) {
            const value = (credInputs[f.key]?.value || "").trim();
            if (f.key === "api_key") apiKey = value || null;
            else if (value) options[f.key] = value;
          }
          const payload = {
            kind: kindSelect.value,
            base_url: baseUrlInput.value.trim() || null,
            api_key: apiKey,
            options,
            requires_key: reqKeyInput.checked,
            rps: numberOrNull(rpsInput),
            rpm: numberOrNull(rpmInput),
            max_concurrency: numberOrNull(concInput) ?? 1,
            monthly_chars: numberOrNull(monthlyInput),
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
        "An API account: base URL, API key, and account-wide rate limits shared by all of its engines.",
      ),
      el(
        "div",
        { class: "row" },
        field("Id", idInput),
        field("Kind", kindSelect.root),
      ),
      el(
        "div",
        { style: "margin-top:10px" },
        field("Base URL (openai kind)", baseUrlInput),
      ),
      reqKeyRow,
      credsBox,
      el(
        "p",
        { class: "hint", style: "margin:6px 0 0" },
        "Credentials are stored in the config file; engines on this provider stay disabled until they are set.",
      ),
      el(
        "div",
        { class: "row", style: "margin-top:10px" },
        field("Req/s", rpsInput),
        field("Req/min", rpmInput),
        field("Max concurrency", concInput),
        field("Monthly chars", monthlyInput),
      ),
      el(
        "div",
        { class: "actions" },
        save,
        el("button", { class: "ghost", onclick: () => leave() }, "Cancel"),
      ),
    ),
  );
}
