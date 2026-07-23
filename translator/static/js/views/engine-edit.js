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
  });
  providerSelect.value =
    engine?.provider || params.get("provider") || providerSelect.value;
  const modelInput = el("input", {
    type: "text",
    value: engine?.model || "",
    placeholder: "glm-4.7-flash",
  });
  const maxTokensInput = el("input", {
    type: "number",
    min: "0",
    step: "1000",
    value: engine?.max_input_tokens ?? "",
  });
  const chunkTokensInput = el("input", {
    type: "number",
    min: "0",
    step: "100",
    value: engine?.chunk_tokens ?? "",
  });
  const enabledInput = el("input", {
    type: "checkbox",
    checked: (engine ? engine.enabled : true) ? "" : null,
    style: "width:auto;margin-right:6px",
  });
  const extraInput = el("textarea", {
    rows: "3",
    placeholder: '{"chat_template_kwargs": {"enable_thinking": false}}',
  });
  if (engine && Object.keys(engine.extra_body || {}).length)
    extraInput.value = JSON.stringify(engine.extra_body, null, 2);

  const collect = () =>
    JSON.stringify([
      idInput.value,
      providerSelect.value,
      modelInput.value,
      maxTokensInput.value,
      chunkTokensInput.value,
      enabledInput.checked,
      extraInput.value,
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
          let extraBody = {};
          if (extraInput.value.trim()) {
            try {
              extraBody = JSON.parse(extraInput.value);
            } catch {
              toast("Extra body is not valid JSON", "error");
              return;
            }
          }
          const payload = {
            provider: providerSelect.value,
            model: modelInput.value.trim() || null,
            enabled: enabledInput.checked,
            max_input_tokens: numberOrNull(maxTokensInput),
            chunk_tokens: numberOrNull(chunkTokensInput),
            extra_body: extraBody,
          };
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
      el("div", { style: "margin-top:10px" }, field("Model", modelInput)),
      el(
        "div",
        { class: "row", style: "margin-top:10px" },
        field("Max input tokens", maxTokensInput),
        field("Chunk tokens", chunkTokensInput),
      ),
      el(
        "label",
        { class: "field", style: "margin-top:10px" },
        el("span", {}, enabledInput, "Enabled"),
      ),
      field("Extra request body (JSON)", extraInput),
      el(
        "div",
        { class: "actions" },
        save,
        el("button", { class: "ghost", onclick: () => leave() }, "Cancel"),
      ),
    ),
  );
}
