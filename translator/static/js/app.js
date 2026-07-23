import { $, el } from "./ui.js";
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
            onclick: closeDrawer,
          },
          el("span", { class: "glyph" }, view.glyph),
          view.title,
        ),
      ),
    ]),
  );
}

function showView() {
  const active = currentViewId();
  const view = VIEWS.find((v) => v.id === active);
  for (const [id, node] of mounted)
    node.style.display = id === active ? "" : "none";
  if (!mounted.has(active)) {
    const node = el("div");
    $("#views").append(node);
    mounted.set(active, node);
    view.mount(node);
    if (store.config) view.onStore();
  }
  $("#page-title").textContent = view.title;
  view.onShow?.();
  renderNav();
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
  if (health.version) $("#version").textContent = "v" + health.version;
}

/* Theme: auto -> light -> dark */
const THEME_ICONS = { "": "◐", light: "☀", dark: "☾" };
let theme = localStorage.getItem("theme") || "";

function applyTheme() {
  if (theme) document.documentElement.dataset.theme = theme;
  else delete document.documentElement.dataset.theme;
  const btn = $("#theme-btn");
  btn.textContent = THEME_ICONS[theme];
  btn.title = `Theme: ${theme || "auto"}`;
}
$("#theme-btn").addEventListener("click", () => {
  theme = theme === "" ? "light" : theme === "light" ? "dark" : "";
  if (theme) localStorage.setItem("theme", theme);
  else localStorage.removeItem("theme");
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
  for (const [id, node] of mounted) {
    void node;
    VIEWS.find((v) => v.id === id).onStore();
  }
});
window.addEventListener("hashchange", showView);

showView();
refreshAll();
setInterval(refreshAll, 30000);
