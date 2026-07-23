import { el, toast, busy } from "../ui.js";
import { store, mutate } from "../store.js";

export const id = "policy";
export const title = "Failure policy";
export const glyph = "♻";

let fields = {};
let loadedFrom = null;

export function mount(root) {
  fields = {
    retries: el("input", { type: "number", min: 0, step: 1 }),
    backoff: el("input", { type: "number", min: 0, step: 0.5 }),
    threshold: el("input", { type: "number", min: 1, step: 1 }),
    cooldown: el("input", { type: "number", min: 1, step: 10 }),
  };
  root.append(
    el(
      "div",
      { class: "card" },
      el("h2", {}, "Failure policy"),
      el(
        "p",
        { class: "hint" },
        "Retry, fallback, and cooldown behavior of the router.",
      ),
      el(
        "div",
        { class: "row" },
        el(
          "label",
          { class: "field" },
          el("span", {}, "Transient retries"),
          fields.retries,
        ),
        el(
          "label",
          { class: "field" },
          el("span", {}, "Backoff base (s)"),
          fields.backoff,
        ),
        el(
          "label",
          { class: "field" },
          el("span", {}, "Failure threshold"),
          fields.threshold,
        ),
        el(
          "label",
          { class: "field" },
          el("span", {}, "Cooldown (s)"),
          fields.cooldown,
        ),
      ),
      el(
        "div",
        { class: "actions" },
        el(
          "button",
          {
            class: "primary",
            onclick: (event) =>
              busy(event.target, async () => {
                await mutate("/config/failure-policy", {
                  method: "PUT",
                  body: {
                    transient_retries: Number(fields.retries.value),
                    backoff_base_seconds: Number(fields.backoff.value),
                    failure_threshold: Number(fields.threshold.value),
                    cooldown_seconds: Number(fields.cooldown.value),
                  },
                });
                toast("Failure policy saved");
              }),
          },
          "Save failure policy",
        ),
      ),
    ),
  );
}

export function onStore() {
  const policy = store.config?.failure_policy;
  if (!policy) return;
  const from = JSON.stringify(policy);
  if (loadedFrom === from) return;
  loadedFrom = from;
  fields.retries.value = policy.transient_retries;
  fields.backoff.value = policy.backoff_base_seconds;
  fields.threshold.value = policy.failure_threshold;
  fields.cooldown.value = policy.cooldown_seconds;
}
