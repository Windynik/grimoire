// Mana symbol markup. These functions return HTML strings. They escape
// their input first, so callers may set the result with innerHTML.

function escapeHtml(value) {
  return String(value == null ? "" : value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

// Symbols we have sprites for; anything else falls back to a text badge
const MANA_SPRITES = {
  w: "sw", u: "su", b: "sb", r: "sr", g: "sg",
  c: "sc", x: "sx", t: "st",
};
for (let i = 0; i <= 20; i++) MANA_SPRITES[String(i)] = `s${i}`;

/** Render one "{...}" token (e.g. "T", "G", "2", "W/U", "W/P", "E") as an icon. */
export function manaSymbol(symbol) {
  const label = escapeHtml(`{${symbol.toUpperCase()}}`);
  const cls = MANA_SPRITES[symbol.toLowerCase()];
  if (cls) {
    return `<i class="mana ${cls}" title="${label}"></i>`;
  }
  // Hybrid, Phyrexian, energy, snow, etc. have no sprite, so use a styled badge
  return `<span class="mana-text" title="${label}">${escapeHtml(symbol.toUpperCase())}</span>`;
}

/** Convert "{2}{U}{B}" into mana sprite icons. */
export function parseManaSymbols(manaCost) {
  if (!manaCost) return '<span class="mana-none">—</span>';
  return manaCost.replace(/\{([^}]+)\}/g, (_match, symbol) => manaSymbol(symbol));
}

/**
 * Escape oracle text, then turn its "{...}" tokens into icons.
 * Escaping first is safe: it never adds braces, so the token regex only
 * matches the original Scryfall symbols.
 */
export function renderOracleText(text) {
  if (!text) return "";
  return escapeHtml(text).replace(/\{([^}]+)\}/g, (_match, symbol) => manaSymbol(symbol));
}
