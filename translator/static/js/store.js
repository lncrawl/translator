import { api } from "./api.js";

export const store = {
  config: null,
  engines: [],
  health: null,
  reachable: true,
  updatedAt: null,
};

const listeners = new Set();

export function subscribe(fn) {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

function notify() {
  for (const fn of listeners) fn();
}

export async function refreshAll() {
  const [config, engines, health] = await Promise.allSettled([
    api("/config"),
    api("/engines"),
    api("/health"),
  ]);
  if (config.status === "fulfilled") store.config = config.value;
  if (engines.status === "fulfilled") store.engines = engines.value.engines;
  if (health.status === "fulfilled") store.health = health.value;
  store.reachable = health.status === "fulfilled";
  store.updatedAt = new Date();
  notify();
}

// Every write goes through here so the whole UI refreshes afterwards.
export async function mutate(path, opts) {
  const result = await api(path, opts);
  await refreshAll();
  return result;
}

export function liveEngine(id) {
  return store.engines.find((e) => e.id === id);
}

export function inactiveEngineIds() {
  return new Set(
    store.engines.filter((e) => e.status === "disabled").map((e) => e.id),
  );
}

export function keyState(provider) {
  if (provider.api_key) return "set";
  if (provider.kind === "nllb" || provider.requires_key === false)
    return "none-needed";
  return "missing";
}
