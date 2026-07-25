import { inactiveEngineIds, mutate, store } from "../store.js";
import { busy, dropdown, el, toast } from "../ui.js";

export const id = "routing";
export const title = "Routing lanes";
export const glyph = "routing";

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
      "p",
      { class: "hint" },
      "Priority order per request type — drag to reorder; the router walks the lane and uses the first engine that is enabled, keyed, and not cooling down. Engines without a working key are hidden but keep their slot.",
    ),
    lanesBox,
    el("div", { class: "actions" }, saveBtn, discardBtn, dirtyNote),
  );
}

function laneItem(ids, index, commit) {
  const name = ids[index];
  const item = el(
    "div",
    { class: "lane-item", draggable: "true" },
    el(
      "span",
      { class: "handle", title: "Drag to reorder", "aria-hidden": "true" },
      "⠿",
    ),
    el("span", { class: "pos" }, String(index + 1)),
    el("span", { class: "name mono" }, name),
    el(
      "span",
      { class: "arrows" },
      el(
        "button",
        {
          class: "ghost small",
          "aria-label": `Move ${name} up`,
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
          "aria-label": `Move ${name} down`,
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
          "aria-label": `Remove ${name} from lane`,
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
        ariaLabel: `Add engine to ${LANE_LABELS[lane]}`,
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
      // A hidden engine is either turned off in config or missing its key —
      // distinct states that must not share the "waiting for a key" label.
      const isDisabled = (i) =>
        config.engines.find((e) => e.id === i)?.enabled === false;
      const disabledIds = hidden.filter(isDisabled);
      const unkeyedIds = hidden.filter((i) => !isDisabled(i));
      const note = (text) => el("p", { class: "meta" }, text);
      return el(
        "div",
        { class: "lane" },
        el("h3", { style: "margin-top:0" }, LANE_LABELS[lane]),
        ids.length
          ? list
          : el("p", { class: "meta" }, "empty — nothing routes here"),
        unused.length ? addSelect.root : "",
        unkeyedIds.length
          ? note(
              `${unkeyedIds.length} more waiting for an API key: ${unkeyedIds.join(", ")}`,
            )
          : "",
        disabledIds.length
          ? note(`${disabledIds.length} disabled: ${disabledIds.join(", ")}`)
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
