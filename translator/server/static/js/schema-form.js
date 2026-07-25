// Renders a JSON Schema object into a form. The server generates those
// schemas from the same Pydantic models it validates against (`GET /schema`),
// so adding a field to a provider, an engine, or an engine kind reaches this
// UI with no change here.

import { SECRET_PLACEHOLDER } from "./store.js";
import { dropdown, el, numberOrNull } from "./ui.js";

// Optional fields arrive as anyOf: [{type: "string"}, {type: "null"}], and
// nested models as a $ref into the root schema's $defs.
function resolve(prop, defs) {
  let spec = prop;
  if (spec.$ref) spec = { ...lookup(spec.$ref, defs), ...omitRef(spec) };
  const branches = spec.anyOf || spec.oneOf;
  if (branches) {
    let real = branches.find((b) => b.type !== "null") || {};
    if (real.$ref) real = lookup(real.$ref, defs);
    spec = { ...real, ...omitBranches(spec) };
  }
  return spec;
}

function lookup(ref, defs) {
  const name = ref.split("/").pop();
  return defs?.[name] || {};
}

function omitRef({ $ref, ...rest }) {
  return rest;
}

function omitBranches({ anyOf, oneOf, ...rest }) {
  return rest;
}

function isNullable(prop) {
  const branches = prop.anyOf || prop.oneOf;
  return branches ? branches.some((b) => b.type === "null") : false;
}

// A nested model (its own properties) versus a free-form mapping such as
// extra_body, which has no declared shape and stays a JSON blob.
function isNestedModel(spec) {
  return spec.type === "object" && !!spec.properties;
}

// Numeric bounds: JSON Schema splits inclusive/exclusive, HTML has only `min`.
function minFor(spec) {
  if (spec.minimum !== undefined) return String(spec.minimum);
  if (spec.exclusiveMinimum !== undefined) return String(spec.exclusiveMinimum);
  return null;
}

function stepFor(spec) {
  if (spec.multipleOf !== undefined) return String(spec.multipleOf);
  return spec.type === "integer" ? "1" : "any";
}

// What to show in an empty box: the inherited/global value when the field is an
// override, otherwise the schema default.
function placeholderFor(spec, fallback) {
  if (fallback !== undefined && fallback !== null) return String(fallback);
  if (spec.default !== undefined && spec.default !== null)
    return String(spec.default);
  return "";
}

// One control. Each returns { node, read(), initial() } so the caller can
// collect values and compare for dirty state without knowing the field's type.
function buildControl(name, spec, value, ctx) {
  const fire = () => ctx.onChange && ctx.onChange();
  const fallback = ctx.placeholders?.[name];

  if (spec.enum) {
    const node = dropdown({
      ariaLabel: spec.title || name,
      options: spec.enum.map((v) => ({ value: v, label: String(v) })),
      value: value ?? spec.default ?? spec.enum[0],
      onChange: fire,
    });
    return { node, read: () => node.value, initial: () => node.value };
  }

  if (spec.type === "boolean") {
    const node = el("input", {
      type: "checkbox",
      checked: (value ?? spec.default ?? false) ? "" : null,
      style: "width:auto;margin:0",
      onchange: fire,
    });
    return {
      node,
      inline: true,
      read: () => node.checked,
      initial: () => node.checked,
    };
  }

  if (spec.type === "integer" || spec.type === "number") {
    const node = el("input", {
      type: "number",
      min: minFor(spec),
      step: stepFor(spec),
      value: value ?? "",
      placeholder: placeholderFor(spec, fallback),
      oninput: fire,
    });
    return { node, read: () => numberOrNull(node), initial: () => node.value };
  }

  if (spec.type === "array") {
    // Only arrays of scalars occur here (language allowlists). A kind that
    // declares a default — baidu's fixed catalog — shows it, so "blank" does
    // not read as "unrestricted" where it is not.
    const fallbackList = Array.isArray(fallback)
      ? fallback
      : Array.isArray(spec.default)
        ? spec.default
        : null;
    const node = el("input", {
      type: "text",
      value: Array.isArray(value) ? value.join(", ") : "",
      placeholder: fallbackList
        ? fallbackList.join(", ")
        : "comma separated — blank for any",
      oninput: fire,
    });
    return {
      node,
      read: () => {
        const parts = node.value
          .split(",")
          .map((s) => s.trim())
          .filter(Boolean);
        return parts.length ? parts : null;
      },
      initial: () => node.value,
    };
  }

  if (isNestedModel(spec)) {
    // A model of its own — render its fields inline rather than as JSON.
    const inner = schemaForm(spec, value ?? {}, {
      onChange: ctx.onChange,
      defs: ctx.defs,
      placeholders: ctx.placeholders?.[name],
    });
    const node = el("div", { class: "subform" }, ...inner.rows);
    return {
      node,
      block: true,
      read: () => inner.collect(),
      initial: () => inner.snapshot(),
    };
  }

  if (spec.type === "object") {
    const node = el("textarea", {
      rows: "3",
      placeholder: "{}",
      oninput: fire,
    });
    node.value =
      value && Object.keys(value).length ? JSON.stringify(value, null, 2) : "";
    return {
      node,
      read: () => {
        const raw = node.value.trim();
        if (!raw) return {};
        // Throwing here is caught by the caller and shown as a form error.
        return JSON.parse(raw);
      },
      initial: () => node.value,
    };
  }

  // string, and anything unrecognised
  const node = el("input", {
    type: "text",
    value: value ?? "",
    placeholder: spec.examples?.[0] ?? placeholderFor(spec, fallback),
    oninput: fire,
  });
  return {
    node,
    read: () => node.value.trim() || (isNullable(spec) ? null : ""),
    initial: () => node.value,
  };
}

// Secrets are write-only: the server only ever sends the placeholder back, so
// the box starts empty. Blank means "keep the stored value", typing replaces
// it, and Remove clears it. Plain text, not masked — the box only ever holds
// what the user just typed, so masking would hide their own input without
// protecting anything stored.
function buildSecret(name, spec, stored, ctx) {
  const saved = !!stored;
  const state = { cleared: false };
  const input = el("input", {
    type: "text",
    value: "",
    autocomplete: "off",
    placeholder: saved ? "saved — leave blank to keep" : "paste token",
    style: "flex:1",
    oninput: () => {
      state.cleared = false;
      ctx.onChange && ctx.onChange();
    },
  });
  const remove = saved
    ? el(
        "button",
        {
          type: "button",
          class: "ghost",
          onclick: () => {
            state.cleared = true;
            input.value = "";
            input.placeholder = "will be removed on save";
            ctx.onChange && ctx.onChange();
          },
        },
        "Remove",
      )
    : null;
  const node = el(
    "div",
    { style: "display:flex;gap:6px;align-items:center" },
    input,
    remove,
  );
  return {
    node,
    read: () => {
      const typed = input.value.trim();
      if (typed) return typed;
      if (state.cleared) return null;
      return saved ? SECRET_PLACEHOLDER : null;
    },
    initial: () => `${input.value}|${state.cleared}`,
  };
}

function row(name, spec, control) {
  const label = spec.title || name;
  const hint = spec.description
    ? el("p", { class: "field-hint" }, spec.description)
    : null;
  if (control.inline) {
    // Checkboxes read as "[x] label", not a label stacked above a lone box.
    return el(
      "div",
      { class: "field-block" },
      el(
        "label",
        { class: "field check" },
        control.node,
        el("span", {}, label),
      ),
      hint,
    );
  }
  if (control.block) {
    return el(
      "div",
      { class: "field-block" },
      el("span", { class: "field-legend" }, label),
      hint,
      control.node,
    );
  }
  return el(
    "div",
    { class: "field-block" },
    el("label", { class: "field" }, el("span", {}, label), control.node),
    hint,
  );
}

/**
 * Render `schema.properties` into rows.
 *
 * @param schema  a JSON Schema object node (its `$defs` are used for `$ref`s)
 * @param values  current values, keyed by field name
 * @param opts.onChange      called on every edit (for dirty tracking)
 * @param opts.omit          field names to skip
 * @param opts.defs          `$defs` from an outer schema, for nested calls
 * @param opts.placeholders  values to show as greyed-out placeholders, i.e.
 *   what an unset override would inherit
 * @returns {{rows, fields, collect, snapshot}} — `collect()` may throw on
 *   malformed JSON in a free-form object field; callers surface that as a form
 *   error. `fields` exposes each row so callers can show or hide it.
 */
export function schemaForm(schema, values = {}, opts = {}) {
  const { onChange, omit = [], placeholders } = opts;
  const defs = { ...(schema?.$defs || {}), ...(opts.defs || {}) };
  const ctx = { onChange, defs, placeholders };
  const skip = new Set(omit);
  const fields = [];
  for (const [name, prop] of Object.entries(schema?.properties || {})) {
    if (skip.has(name)) continue;
    const spec = resolve(prop, defs);
    const control = spec.secret
      ? buildSecret(name, spec, values[name], ctx)
      : buildControl(name, spec, values[name], ctx);
    fields.push({
      name,
      spec,
      control,
      row: row(name, spec, control),
      credential: spec.credential === true,
      secret: spec.secret === true,
      // Only a field the model allows to be null can be *sent* as null.
      nullable: isNullable(prop),
    });
  }
  return {
    fields,
    rows: fields.map((f) => f.row),
    field(name) {
      return fields.find((f) => f.name === name) || null;
    },
    collect() {
      const out = {};
      for (const f of fields) {
        const value = f.control.read();
        // An empty box on a non-nullable field means "leave it alone", not
        // "set it to null" — omitting the key lets the model's default apply
        // on create and keeps the stored value on a PATCH.
        if ((value === null || value === "") && !f.nullable) continue;
        out[f.name] = value;
      }
      return out;
    },
    snapshot() {
      return JSON.stringify(fields.map((f) => [f.name, f.control.initial()]));
    },
  };
}

/**
 * One kind's settings as two forms over the same values: the fields the kind
 * adds, and the ones it inherits from `base` (`GET /schema`'s `provider` or
 * `engine`). A kind that *narrows* an inherited field still renders in the
 * inherited group, since membership follows the base's field names.
 *
 * @returns {{own, shared}} — both are `schemaForm` results
 */
export function splitForm(schema, base, values, opts = {}) {
  const inherited = Object.keys(base?.properties || {});
  const added = Object.keys(schema?.properties || {}).filter(
    (name) => !inherited.includes(name),
  );
  return {
    own: schemaForm(schema, values, { ...opts, omit: inherited }),
    shared: schemaForm(schema, values, { ...opts, omit: added }),
  };
}
