// The List view of the Decks screen: a compact table with one row per deck.
// A click on a row, or on the name button, opens the deck. The last cell has
// the More menu (Duplicate, Delete).
//
// Deck names and server text go in with textContent only.

import { h, manaNode } from "../shared/dom.js";
import { formatDay, formatPrice } from "../shared/format.js";
import { commanderName } from "./filter.js";
import { deckMenu } from "./tile.js";

const COLOR_WORDS = { W: "White", U: "Blue", B: "Black", R: "Red", G: "Green" };

// [key, heading, class]. The class "num" right-aligns a number column.
const COLUMNS = [
  ["name", "Name", "col-name"],
  ["commander", "Commander", "col-commander"],
  ["format", "Format", "col-format"],
  ["colors", "Colors", "col-colors"],
  ["cards", "Cards", "col-cards num"],
  ["owned", "Owned", "col-owned num"],
  ["price", "Price", "col-price num"],
  ["updated", "Last change", "col-updated"],
];

// The color symbols of a deck. A deck with no analysis yet (colors null) gets nothing.
function colorsOf(deck) {
  if (!Array.isArray(deck.colors)) return null;
  const colors = deck.colors.filter((c) => COLOR_WORDS[c]);
  const cost = colors.length ? colors.map((c) => `{${c}}`).join("") : "{C}";
  const label = colors.length ? colors.map((c) => COLOR_WORDS[c]).join(", ") : "Colorless";
  const symbols = manaNode(cost, "deck-colors-symbols");
  symbols.setAttribute("aria-hidden", "true");
  return h("span", { class: "deck-colors", role: "img", "aria-label": label }, symbols);
}

function rowOf(deck, { onOpen, onDuplicate, onDelete, formatName }) {
  const cell = (key, className, ...children) => h("td", { class: className, "data-col": key }, ...children);
  const owned = Number.isInteger(deck.owned_percent) ? `${deck.owned_percent}%` : "";
  const price = typeof deck.price === "number" ? formatPrice(deck.price) : "";
  const name = h("button", { type: "button", class: "deck-name", text: deck.name, onclick: onOpen });
  const row = h("tr", { class: "deck-list-row" },
    h("th", { scope: "row", class: "col-name", "data-col": "name" }, name),
    cell("commander", "col-commander", commanderName(deck)),
    cell("format", "col-format", formatName(deck.format)),
    cell("colors", "col-colors", colorsOf(deck)),
    cell("cards", "col-cards num", String(Number(deck.count) || 0)),
    cell("owned", "col-owned num", owned),
    cell("price", "col-price num", price),
    cell("updated", "col-updated", formatDay(deck.updated)),
    cell("actions", "col-actions", deckMenu(deck, { onDuplicate, onDelete })));
  // A click on the row opens the deck. The name button and the menu do their own work.
  row.addEventListener("click", (event) => {
    if (event.target.closest("button, summary, details, a")) return;
    onOpen();
  });
  return row;
}

/**
 * Build the deck table.
 *
 * @param {Object[]} decks Summaries from GET /api/decks, in the order to show.
 * @param {Object} options
 * @param {function(Object): void} options.onOpen
 * @param {function(Object): void} options.onDuplicate
 * @param {function(Object): void} options.onDelete
 * @param {function(string): string} options.formatName Maps a format key to its name.
 * @returns {HTMLTableElement}
 */
export function deckTable(decks, { onOpen, onDuplicate, onDelete, formatName }) {
  const head = h("tr", {},
    COLUMNS.map(([key, label, className]) => h("th", { scope: "col", class: className, "data-col": key, text: label })),
    h("th", { scope: "col", class: "col-actions", "data-col": "actions" },
      h("span", { class: "decks-sr", text: "Actions" })));
  const body = h("tbody", {}, decks.map((deck) => rowOf(deck, {
    onOpen: () => onOpen(deck),
    onDuplicate: () => onDuplicate(deck),
    onDelete: () => onDelete(deck),
    formatName,
  })));
  return h("table", { class: "decks-table" }, h("thead", {}, head), body);
}
