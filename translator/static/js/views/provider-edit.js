import {
  el,
  toast,
  busy,
  numberOrNull,
  routeParts,
  goBack,
  dropdown,
} from "../ui.js";
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
    options: ["openai", "deepl", "nllb"].map((k) => ({ value: k, label: k })),
    value: provider?.kind || "openai",
  });
  const baseUrlInput = el("input", {
    type: "text",
    value: provider?.base_url || "",
    placeholder: "https://api.example.com/v1",
  });
  const keyInput = el("input", {
    type: "password",
    value: provider?.api_key || "",
    autocomplete: "off",
    placeholder: "paste token",
  });
  const reqKeyInput = el("input", {
    type: "checkbox",
    checked: (provider ? provider.requires_key !== false : true) ? "" : null,
    style: "width:auto;margin-right:6px",
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

  const collect = () =>
    JSON.stringify([
      idInput.value,
      kindSelect.value,
      baseUrlInput.value,
      keyInput.value,
      reqKeyInput.checked,
      rpsInput.value,
      rpmInput.value,
      concInput.value,
      monthlyInput.value,
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
            base_url: baseUrlInput.value.trim() || null,
            api_key: keyInput.value.trim() || null,
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
      field("API key", keyInput),
      el(
        "label",
        { class: "field" },
        el(
          "span",
          {},
          reqKeyInput,
          "Requires an API key (uncheck for keyless local servers)",
        ),
      ),
      el(
        "p",
        { class: "hint", style: "margin:6px 0 0" },
        "The key is stored in the config file; engines on this provider stay disabled until it is set.",
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
