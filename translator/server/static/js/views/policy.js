import { el, toast, busy } from "../ui.js";
import { store, mutate } from "../store.js";
import { schemaForm } from "../schema-form.js";

export const id = "policy";
export const title = "Failure policy";
export const glyph = "policy";

let box;
let form = null;
let loadedFrom = null;

export function mount(root) {
  box = el("div", {});
  root.append(
    el(
      "p",
      { class: "hint" },
      "Retry, fallback, and cooldown behavior of the router.",
    ),
    box,
    el(
      "div",
      { class: "actions" },
      el(
        "button",
        {
          class: "primary",
          onclick: (event) =>
            busy(event.target, async () => {
              if (!form) return;
              await mutate("/config/failure-policy", {
                method: "PUT",
                body: form.collect(),
              });
              toast("Failure policy saved");
            }),
        },
        "Save failure policy",
      ),
    ),
  );
}

export function onStore() {
  const policy = store.config?.failure_policy;
  if (!policy) return;
  // Labels, help text and bounds all come from the FailurePolicy schema.
  const from = JSON.stringify([policy, store.schema.failure_policy]);
  if (loadedFrom === from) return;
  loadedFrom = from;
  form = schemaForm(store.schema.failure_policy, policy);
  box.replaceChildren(
    el(
      "div",
      { class: "card" },
      el(
        "div",
        { class: "policy-grid" },
        ...form.rows.map((row) => el("div", { class: "policy-field" }, row)),
      ),
    ),
  );
}
