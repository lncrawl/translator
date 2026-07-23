import { el, toast, busy, dropdown } from "../ui.js";
import { store, mutate, inactiveEngineIds } from "../store.js";

export const id = "routing";
export const title = "Routing lanes";
export const glyph = "⇶";

const LANE_LABELS = { chapter: "Chapter lane", short_text: "Short-text lane" };

let draft = null;
let draftFrom = null;
let lanesBox;
let saveBtn;
let discardBtn;
let dirtyNote;

export function mount(root) {
  lanesBox = el("div", { class: "grid two" });
  saveBtn = el(
    "button",
    {
      class: "primary",
      onclick: async (event) => {
        await busy(event.target, async () => {
          await mutate("/routing", { method: "PUT", body: draft });
          toast("Routing saved");
        });
        render(); // busy() re-enables the button; restore the dirty state
      },
    },
    "Save routing",
  );
  discardBtn = el(
    "button",
    {
      class: "ghost",
      onclick: () => {
        draft = null;
        render();
      },
    },
    "Discard changes",
  );
  dirtyNote = el("span", { class: "meta" });
  root.append(
    el(
      "div",
      { class: "card" },
      el("h2", {}, "Routing lanes"),
      el(
        "p",
        { class: "hint" },
        "Priority order per request type — drag to reorder; the router walks the lane and uses the first engine that is enabled, keyed, and not cooling down. Engines without a working key are hidden but keep their slot.",
      ),
      lanesBox,
      el("div", { class: "actions" }, saveBtn, discardBtn, dirtyNote),
    ),
  );
}

function laneItem(ids, index, commit) {
  const item = el(
    "div",
    { class: "lane-item", draggable: "true" },
    el("span", { class: "handle", title: "Drag to reorder" }, "⠿"),
    el("span", { class: "pos" }, String(index + 1)),
    el("span", { class: "name mono" }, ids[index]),
    el(
      "span",
      { class: "arrows" },
      el(
        "button",
        {
          class: "ghost small",
          disabled: index === 0 ? "" : null,
          onclick: () => {
            [ids[index - 1], ids[index]] = [ids[index], ids[index - 1]];
            commit();
          },
        },
        "↑",
      ),
      el(
        "button",
        {
          class: "ghost small",
          disabled: index === ids.length - 1 ? "" : null,
          onclick: () => {
            [ids[index + 1], ids[index]] = [ids[index], ids[index + 1]];
            commit();
          },
        },
        "↓",
      ),
      el(
        "button",
        {
          class: "danger small",
          onclick: () => {
            ids.splice(index, 1);
            commit();
          },
        },
        "✕",
      ),
    ),
  );
  return item;
}

function makeDraggable(list, ids, commit) {
  let fromIndex = null;
  const items = [...list.children];
  items.forEach((item, index) => {
    item.addEventListener("dragstart", (event) => {
      fromIndex = index;
      item.classList.add("dragging");
      event.dataTransfer.effectAllowed = "move";
    });
    item.addEventListener("dragend", () => {
      fromIndex = null;
      item.classList.remove("dragging");
      items.forEach((i) => i.classList.remove("drag-over"));
    });
    item.addEventListener("dragover", (event) => {
      if (fromIndex === null || fromIndex === index) return;
      event.preventDefault();
      event.dataTransfer.dropEffect = "move";
      item.classList.add("drag-over");
    });
    item.addEventListener("dragleave", () =>
      item.classList.remove("drag-over"),
    );
    item.addEventListener("drop", (event) => {
      if (fromIndex === null || fromIndex === index) return;
      event.preventDefault();
      const [moved] = ids.splice(fromIndex, 1);
      ids.splice(index, 0, moved);
      commit();
    });
  });
}

function render() {
  const { config } = store;
  if (!config) return;
  const fromServer = JSON.stringify(config.routing);
  if (!draft || draftFrom !== fromServer) {
    draft = JSON.parse(fromServer);
    draftFrom = fromServer;
  }
  const inactive = inactiveEngineIds();

  lanesBox.replaceChildren(
    ...["chapter", "short_text"].map((lane) => {
      const ids = draft[lane].filter((i) => !inactive.has(i));
      const hidden = draft[lane].filter((i) => inactive.has(i));
      const commit = () => {
        draft[lane] = ids.concat(hidden);
        render();
      };
      const list = el(
        "div",
        { class: "lane-list" },
        ids.map((_, index) => laneItem(ids, index, commit)),
      );
      makeDraggable(list, ids, commit);
      const unused = config.engines
        .map((e) => e.id)
        .filter((i) => !draft[lane].includes(i) && !inactive.has(i));
      const addSelect = dropdown({
        options: [
          { value: "", label: "add engine…" },
          ...unused.map((i) => ({ value: i, label: i })),
        ],
        onChange: (value) => {
          if (value) {
            ids.push(value);
            commit();
          }
        },
      });
      addSelect.root.style.maxWidth = "240px";
      return el(
        "div",
        { class: "lane" },
        el("h3", { style: "margin-top:0" }, LANE_LABELS[lane]),
        ids.length
          ? list
          : el("p", { class: "meta" }, "empty — nothing routes here"),
        unused.length ? addSelect.root : "",
        hidden.length
          ? el(
              "p",
              { class: "meta" },
              `${hidden.length} more waiting for an API key: ${hidden.join(", ")}`,
            )
          : "",
      );
    }),
  );

  const dirty = JSON.stringify(draft) !== draftFrom;
  saveBtn.disabled = !dirty;
  discardBtn.disabled = !dirty;
  dirtyNote.textContent = dirty ? "unsaved changes" : "";
}

export function onStore() {
  render();
}
