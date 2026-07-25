import { $, el, busy, confirmDialog } from "./ui.js";
import { icon } from "./icons.js";
import { store, subscribe, refreshAll } from "./store.js";
import * as dashboard from "./views/dashboard.js";
import * as translateText from "./views/translate-text.js";
import * as translateChapter from "./views/translate-chapter.js";
import * as detect from "./views/detect.js";
import * as providers from "./views/providers.js";
import * as providerEdit from "./views/provider-edit.js";
import * as engines from "./views/engines.js";
import * as engineEdit from "./views/engine-edit.js";
import * as routing from "./views/routing.js";
import * as policy from "./views/policy.js";
import * as rawConfig from "./views/raw-config.js";

const NAV = [
  { group: "Overview", views: [dashboard] },
  { group: "Test", views: [translateText, translateChapter, detect] },
  {
    group: "Configure",
    views: [providers, engines, routing, policy, rawConfig],
  },
];
// Edit pages are routable but not listed in the sidebar; `parent` marks
// which nav item stays highlighted while they are open.
const VIEWS = [
  ...NAV.flatMap((section) => section.views),
  providerEdit,
  engineEdit,
];

const mounted = new Map(); // view id -> container element

function currentViewId() {
  const hash = location.hash.replace(/^#\//, "").split("?")[0];
  return VIEWS.some((v) => v.id === hash) ? hash : "dashboard";
}

function renderNav() {
  const box = $("#nav");
  const activeView = VIEWS.find((v) => v.id === currentViewId());
  const active = activeView.parent || activeView.id;
  box.replaceChildren(
    ...NAV.flatMap((section) => [
      el("div", { class: "nav-group" }, section.group),
      ...section.views.map((view) =>
        el(
          "a",
          {
            class: `nav-item${view.id === active ? " active" : ""}`,
            href: `#/${view.id}`,
            "aria-current": view.id === active ? "page" : null,
            onclick: closeDrawer,
          },
          el("span", { class: "glyph" }, icon(view.glyph)),
          view.title,
        ),
      ),
    ]),
  );
}

function showView() {
  const active = currentViewId();
  const view = VIEWS.find((v) => v.id === active);
  if (!mounted.has(active)) {
    const node = el("div", { class: "view" });
    $("#views").append(node);
    mounted.set(active, node);
    view.mount(node);
    if (store.config) view.onStore();
  }
  $("#page-title").textContent = view.title;
  view.onShow?.();
  renderNav();
  applyVisibility({ animate: true });
}

/* Gate the views behind a loading / error state until the config is fetched,
   and surface a banner when a previously-loaded service becomes unreachable. */
let bootNode = null;

function applyVisibility({ animate = false } = {}) {
  renderBanner();
  const active = currentViewId();
  if (!store.config) {
    for (const node of mounted.values()) node.style.display = "none";
    showBoot();
    return;
  }
  if (bootNode) {
    bootNode.remove();
    bootNode = null;
  }
  for (const [id, node] of mounted)
    node.style.display = id === active ? "" : "none";
  if (animate) {
    const node = mounted.get(active);
    node.classList.remove("view-in");
    void node.offsetWidth; // reflow so the animation restarts
    node.classList.add("view-in");
  }
}

function showBoot() {
  if (!bootNode) {
    bootNode = el("div");
    $("#views").append(bootNode);
  }
  bootNode.style.display = "";
  const failed = store.updatedAt && !store.config;
  bootNode.replaceChildren(
    failed
      ? el(
          "div",
          { class: "boot" },
          el("div", { class: "boot-icon" }, "⚠"),
          el("h2", {}, "Can't reach the service"),
          el(
            "p",
            {},
            "The dashboard couldn't load its configuration. Check that the " +
              "translator service is running, then retry.",
          ),
          el(
            "button",
            {
              class: "primary",
              onclick: (event) => busy(event.target, refreshAll),
            },
            "Retry",
          ),
        )
      : el(
          "div",
          { class: "boot" },
          el("div", { class: "boot-icon spin" }, "◌"),
          el("h2", {}, "Loading…"),
        ),
  );
}

function renderBanner() {
  let banner = $("#conn-banner");
  const show = store.config && !store.reachable;
  if (show && !banner) {
    banner = el(
      "div",
      { id: "conn-banner", class: "conn-banner", role: "status" },
      "⚠ Lost connection to the service — showing the last known state.",
    );
    $("#views").before(banner);
  } else if (!show && banner) {
    banner.remove();
  }
}

function focusMain() {
  $("#views").focus({ preventScroll: true });
}

function renderHealth() {
  const badge = $("#health-badge");
  const { health, reachable } = store;
  if (!reachable) {
    badge.className = "badge bad";
    badge.textContent = "unreachable";
    return;
  }
  if (!health) return;
  const n = health.engines_enabled.length;
  if (health.status === "ok") {
    badge.className = "badge ok";
    badge.textContent = `OK · ${n} engine${n === 1 ? "" : "s"}`;
  } else {
    badge.className = "badge warn";
    badge.textContent = "unconfigured";
  }
  if (health.version) {
    $("#version").textContent = "v" + health.version;
  }
}

/* Theme: 2-state light <-> dark. No stored choice falls back to the OS
   preference; toggling always resolves to an explicit theme and persists it. */
const systemDark = () => matchMedia("(prefers-color-scheme: dark)").matches;
let theme =
  localStorage.getItem("theme") === "light" ||
  localStorage.getItem("theme") === "dark"
    ? localStorage.getItem("theme")
    : systemDark()
      ? "dark"
      : "light";

function applyTheme() {
  document.documentElement.dataset.theme = theme;
  const btn = $("#theme-btn");
  const next = theme === "dark" ? "light" : "dark";
  btn.replaceChildren(icon(theme === "dark" ? "moon" : "sun", 16));
  btn.title = `Switch to ${next} theme`;
}
$("#theme-btn").addEventListener("click", () => {
  theme = theme === "dark" ? "light" : "dark";
  localStorage.setItem("theme", theme);
  applyTheme();
});
applyTheme();

/* Mobile drawer */
function closeDrawer() {
  $("#sidebar").classList.remove("open");
  $("#backdrop").classList.remove("show");
}
$("#menu-btn").addEventListener("click", () => {
  $("#sidebar").classList.toggle("open");
  $("#backdrop").classList.toggle("show");
});
$("#backdrop").addEventListener("click", closeDrawer);

/* Wiring */
subscribe(() => {
  renderHealth();
  if (store.config)
    for (const id of mounted.keys()) VIEWS.find((v) => v.id === id).onStore();
  applyVisibility();
});

/* Navigation, with an unsaved-changes guard when leaving an edit page. */
let activeId = currentViewId();
let lastHash = location.hash;
let restoring = false;

window.addEventListener("hashchange", async () => {
  if (restoring) {
    restoring = false;
    lastHash = location.hash;
    return;
  }
  const next = currentViewId();
  if (next !== activeId) {
    const message = VIEWS.find((v) => v.id === activeId)?.guardLeave?.();
    if (message) {
      const ok = await confirmDialog({
        title: "Discard changes?",
        message,
        confirmLabel: "Discard",
        cancelLabel: "Keep editing",
        danger: true,
      });
      if (!ok) {
        restoring = true;
        location.hash = lastHash;
        return;
      }
    }
  }
  activeId = next;
  lastHash = location.hash;
  showView();
  focusMain();
});

showView();
refreshAll();
setInterval(refreshAll, 30000);
