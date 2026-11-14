// Combos section of the editor's stats panel: the deck's last Commander
// Spellbook check. Find combos sends only the card names; the server keeps the
// answer in the deck. Server text goes in with textContent only.

import { h } from "../shared/dom.js";

const SHOWN = 6;

function comboItem(combo, missing) {
  const cards = (combo.cards || []).join(" + ");
  const result = (combo.produces || []).slice(0, 2).join(", ");
  const tag = combo.tag_label ? h("span", { class: `combo-tag combo-tag-${String(combo.tag || "").toLowerCase()}`,
    text: combo.tag_label }) : "";
  const title = combo.url
    ? h("a", { class: "combo-cards", href: combo.url, target: "_blank", rel: "noopener noreferrer", text: cards })
    : h("span", { class: "combo-cards", text: cards });
  const parts = [title, tag];
  if (missing) {
    parts.unshift(h("span", { class: "combo-missing", text: `Add ${(combo.missing || []).join(" and ")}: ` }));
  }
  if (result) parts.push(h("span", { class: "combo-result", text: result }));
  return h("li", { class: "combo-item", title: combo.description || "" }, ...parts);
}

function list(combos, missing) {
  const items = combos.slice(0, SHOWN).map((c) => comboItem(c, missing));
  if (combos.length > SHOWN) {
    items.push(h("li", { class: "combo-more", text: `and ${combos.length - SHOWN} more` }));
  }
  return h("ul", { class: "combo-list" }, ...items);
}

function checkedText(iso) {
  const date = iso ? new Date(iso) : null;
  return date && !Number.isNaN(date.getTime())
    ? date.toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" }) : "";
}

/**
 * Render the combos section.
 *
 * @param {HTMLElement} root
 * @param {Object|null} combos The deck's "combos" ({checked, included, almost}), or null.
 * @param {{stale: boolean, busy: boolean, onFind: function()}} options
 */
export function renderCombos(root, combos, { stale = false, busy = false, onFind } = {}) {
  const button = h("button", {
    type: "button", class: "btn btn-secondary btn-compact combo-find",
    text: busy ? "Asking Commander Spellbook…" : combos ? "Find combos again" : "Find combos",
    onclick: () => { if (onFind) onFind(); },
  });
  button.disabled = busy;
  const parts = [];
  if (!combos) {
    parts.push(h("p", { class: "combo-note", text: "Ask Commander Spellbook which combos this deck holds. Grimoire sends only the card names." }));
  } else {
    const included = combos.included || [];
    const almost = combos.almost || [];
    const when = checkedText(combos.checked);
    parts.push(h("p", { class: "combo-note",
      text: `${included.length} ${included.length === 1 ? "combo" : "combos"} in the deck${when ? ` (checked ${when})` : ""}.` }));
    if (stale) parts.push(h("p", { class: "combo-stale", text: "The deck changed after this check." }));
    if (included.length) parts.push(list(included, false));
    if (almost.length) {
      parts.push(h("p", { class: "combo-subtitle", text: "One card away" }), list(almost, true));
    }
  }
  root.replaceChildren(...parts, button);
}
