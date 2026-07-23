import { el, toast, busy, confirmDialog } from "../ui.js";
import { store, mutate } from "../store.js";

export const id = "raw-config";
export const title = "Raw config";
export const glyph = "code";

let editor;
let loadedFrom = null;

export function mount(root) {
  editor = el("textarea", { rows: 22, spellcheck: "false" });
  root.append(
    el(
      "div",
      { class: "card" },
      el(
        "p",
        { class: "hint" },
        "The full config as JSON. Apply replaces the whole config after server-side validation (",
        el("code", {}, "PUT /config"),
        ").",
      ),
      editor,
      el(
        "div",
        { class: "actions" },
        el(
          "button",
          {
            class: "primary",
            onclick: (event) =>
              busy(event.target, async () => {
                let parsed;
                try {
                  parsed = JSON.parse(editor.value);
                } catch {
                  toast("Config is not valid JSON", "error");
                  return;
                }
                const ok = await confirmDialog({
                  title: "Replace entire config?",
                  message:
                    "This overwrites the whole runtime config and persists to config.yml.",
                  confirmLabel: "Replace config",
                  danger: true,
                });
                if (!ok) return;
                await mutate("/config", { method: "PUT", body: parsed });
                toast("Config replaced");
              }),
          },
          "Apply full config",
        ),
        el(
          "button",
          {
            class: "ghost",
            onclick: () => {
              loadedFrom = null;
              onStore();
            },
          },
          "Reset to live config",
        ),
      ),
    ),
  );
}

export function onStore() {
  if (!store.config) return;
  const from = JSON.stringify(store.config, null, 2);
  if (loadedFrom === from) return;
  loadedFrom = from;
  editor.value = from;
}
