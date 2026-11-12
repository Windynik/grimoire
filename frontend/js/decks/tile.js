// The deck tile. Decks shows the full tile. Home shows the compact tile.
//
// Deck names and server text go in with textContent only.

import { h } from "../shared/dom.js";
import { plural } from "../shared/format.js";
import { cardImg } from "../shared/images.js";

function formatDate(value) {
  const date = new Date(value);
  if (!value || Number.isNaN(date.getTime())) return "";
  return date.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

// The art card of a deck summary: image_url, image_id (its Scryfall id) and
// image_name. An older summary with no image_id falls back to the raw URL.
function artOf(deck, compact) {
  const art = h("div", { class: "deck-art", "aria-hidden": "true" });
  if (deck.image_url) {
    const card = { scryfall_id: deck.image_id, name: deck.image_name, image_url: deck.image_url };
    art.append(cardImg(card, { size: compact ? "small" : "normal" }));
  } else {
    art.classList.add("deck-art-empty");
  }
  return art;
}

/**
 * Build a deck tile.
 *
 * @param {Object} deck A summary from GET /api/decks.
 * @param {Object} options
 * @param {function(): void} options.onOpen
 * @param {function(): void} [options.onDuplicate] Full tile only.
 * @param {function(): void} [options.onDelete] Full tile only.
 * @param {boolean} [options.compact] Art, name, format and count. The tile is one button.
 * @param {function(string): string} [options.formatName] Maps a format key to its name.
 * @returns {HTMLElement}
 */
export function deckTile(deck, {
  onOpen, onDuplicate, onDelete, compact = false, formatName = (key) => key || "",
} = {}) {
  const meta = [formatName(deck.format), plural(deck.count || 0, "card"), deck.built ? "built" : ""]
    .filter(Boolean);

  if (compact) {
    return h("button", { type: "button", class: "deck-tile deck-tile-compact", onclick: onOpen },
      artOf(deck, true),
      h("span", { class: "deck-body" },
        h("span", { class: "deck-title", text: deck.name }),
        h("span", { class: "deck-meta", text: meta.join(" · ") })));
  }

  const updated = formatDate(deck.updated);
  if (updated) meta.push(`Updated ${updated}`);

  const open = h("button", {
    type: "button", class: "btn btn-primary btn-compact", onclick: onOpen,
  }, "Open");
  const duplicate = h("button", {
    type: "button", class: "btn btn-secondary btn-compact", onclick: onDuplicate,
  }, "Duplicate");
  const remove = h("button", {
    type: "button", class: "btn btn-danger btn-compact", onclick: onDelete,
  }, "Delete");

  const title = h("button", { type: "button", class: "deck-name", onclick: onOpen });
  title.textContent = deck.name;
  const body = h("div", { class: "deck-body" },
    h("h3", { class: "deck-title" }, title),
    deck.commander
      ? h("p", { class: "deck-commander", text: deck.commander.name || deck.commander }) : null,
    h("p", { class: "deck-meta", text: meta.join(" · ") }),
    h("div", { class: "deck-actions" }, open, duplicate, remove));
  return h("article", { class: "deck-tile" }, artOf(deck, false), body);
}
