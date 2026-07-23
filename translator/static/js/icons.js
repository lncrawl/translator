/* Line-icon set (24×24, currentColor stroke) — one consistent family for the
   sidebar so nav items read as a system instead of mixed Unicode glyphs. */
const PATHS = {
  dashboard:
    '<rect x="3" y="3" width="7" height="9" rx="1"/><rect x="14" y="3" width="7" height="5" rx="1"/><rect x="14" y="12" width="7" height="9" rx="1"/><rect x="3" y="16" width="7" height="5" rx="1"/>',
  text: '<path d="M4 5h7"/><path d="M7 5v3c0 3-1.5 6-4 8"/><path d="M6 11c1.5 2.5 3.5 4 6 5"/><path d="M13 19l4-9 4 9"/><path d="M14.5 16h5"/>',
  chapter:
    '<path d="M6 3h8l4 4v13a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1z"/><path d="M14 3v4h4"/><path d="M8 12h8M8 16h6"/>',
  detect:
    '<circle cx="12" cy="12" r="9"/><path d="M3 12h18"/><path d="M12 3a15 15 0 0 1 0 18a15 15 0 0 1 0-18z"/>',
  providers:
    '<ellipse cx="12" cy="6" rx="8" ry="3"/><path d="M4 6v12c0 1.66 3.58 3 8 3s8-1.34 8-3V6"/><path d="M4 12c0 1.66 3.58 3 8 3s8-1.34 8-3"/>',
  engines:
    '<rect x="6" y="6" width="12" height="12" rx="1.5"/><path d="M9 3v3M15 3v3M9 18v3M15 18v3M3 9h3M3 15h3M18 9h3M18 15h3"/>',
  routing:
    '<path d="M8 6h12M8 12h12M8 18h12"/><path d="M4 4v4M4 8l-1.4-1.4M4 8l1.4-1.4"/><path d="M4 20v-4M4 16l-1.4 1.4M4 16l1.4 1.4"/>',
  policy: '<path d="M21 12a9 9 0 1 1-2.64-6.36"/><path d="M21 3v6h-6"/>',
  code: '<path d="M8 4c-2 0-3 1-3 3v2c0 1.5-.5 2.5-2 3c1.5.5 2 1.5 2 3v2c0 2 1 3 3 3"/><path d="M16 4c2 0 3 1 3 3v2c0 1.5.5 2.5 2 3c-1.5.5-2 1.5-2 3v2c0 2-1 3-3 3"/>',
  chevron: '<path d="M6 9l6 6 6-6"/>',
};

export function icon(name, size = 18) {
  const markup =
    `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" ` +
    `width="${size}" height="${size}" fill="none" stroke="currentColor" ` +
    `stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" ` +
    `aria-hidden="true">${PATHS[name] || ""}</svg>`;
  const tpl = document.createElement("template");
  tpl.innerHTML = markup;
  return tpl.content.firstChild;
}
