import { api } from "./api.js";

// Sentinel for stored secrets: responses replace every saved secret with this
// value, and sending it back means "keep the stored secret". Secrets are never
// readable through the API. The server confirms it in GET /schema; this is the
// value used until that first fetch lands.
export const SECRET_PLACEHOLDER = "__secret__";

// GET /schema, generated from the server's own models. Forms render from it,
// so field lists live in exactly one place.
export const store = {
  config: null,
  engines: [],
  health: null,
  schema: {
    provider: {},
    engine: {},
    failure_policy: {},
    kinds: [],
    lanes: [],
  },
  reachable: true,
  updatedAt: null,
};

export function kindSchema(kind) {
  return store.schema.kinds.find((k) => k.kind === kind) || null;
}

export function kindNames() {
  return store.schema.kinds.map((k) => k.kind);
}

export function lanes() {
  return store.schema.lanes;
}

const listeners = new Set();

export function subscribe(fn) {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

function notify() {
  for (const fn of listeners) fn();
}

export async function refreshAll() {
  const [config, engines, health, schema] = await Promise.allSettled([
    api("/config"),
    api("/engines"),
    api("/health"),
    api("/schema"),
  ]);
  if (config.status === "fulfilled") store.config = config.value;
  if (engines.status === "fulfilled") store.engines = engines.value.engines;
  if (health.status === "fulfilled") store.health = health.value;
  if (schema.status === "fulfilled") store.schema = schema.value;
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

// Mirrors the server's availability gate (engines.registry.is_configured),
// using the credential declarations the server sends.
export function keyState(provider) {
  const settings = provider.settings || {};
  const fields = kindSchema(provider.kind)?.credentials || [];
  if (fields.length === 0 || settings.requires_key === false)
    return "none-needed";
  const required = fields.filter((f) => f.required);
  return required.every((f) => settings[f.key]) ? "set" : "missing";
}
