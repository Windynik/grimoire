// The deck tile. Decks shows the full tile. Home shows the compact tile.
//
// Deck names and server text go in with textContent only.

import { h } from "../shared/dom.js";
import { formatDay, plural } from "../shared/format.js";
import { cardImg } from "../shared/images.js";

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

// One listener for every More menu: a press outside an open menu closes it.
// (A click on a button does not move the focus in every browser, so a
// focusout alone cannot tell that the press was outside.)
let watchingPresses = false;
function closeMenusOnOutsidePress() {
  if (watchingPresses) return;
  watchingPresses = true;
  document.addEventListener("pointerdown", (event) => {
    document.querySelectorAll("details.deck-more[open]").forEach((menu) => {
      if (!menu.contains(event.target)) menu.open = false;
    });
  });
}

/**
 * The More menu of a deck: Duplicate, and Delete as a quiet danger action.
 * It closes on a choice, on Escape, on a press outside it, and when the
 * keyboard focus moves out of it.
 *
 * @param {Object} deck A summary from GET /api/decks.
 * @param {Object} options
 * @param {function(): void} options.onDuplicate
 * @param {function(): void} options.onDelete
 * @param {boolean} [options.up] Open the menu above the button (the tile clips below).
 * @returns {HTMLDetailsElement}
 */
export function deckMenu(deck, { onDuplicate, onDelete, up = false } = {}) {
  const details = h("details", { class: `deck-more${up ? " deck-more-up" : ""}` });
  const summary = h("summary", {
    class: "btn btn-secondary btn-compact", "aria-label": `More actions for ${deck.name}`, text: "More",
  });
  const item = (label, run, danger) => h("button", {
    type: "button", class: `deck-more-item${danger ? " is-danger" : ""}`, text: label,
    onclick: () => {
      details.open = false;
      // The focus goes back to More, so a dialog can give it back there.
      summary.focus();
      if (run) run();
    },
  });
  details.append(summary, h("div", { class: "deck-more-menu" },
    item("Duplicate", onDuplicate, false), item("Delete", onDelete, true)));
  details.addEventListener("keydown", (event) => {
    if (event.key !== "Escape" || !details.open) return;
    event.preventDefault();
    event.stopPropagation();
    details.open = false;
    summary.focus();
  });
  details.addEventListener("focusout", (event) => {
    if (event.relatedTarget && !details.contains(event.relatedTarget)) details.open = false;
  });
  closeMenusOnOutsidePress();
  // One menu at a time.
  details.addEventListener("toggle", () => {
    if (!details.open) return;
    document.querySelectorAll("details.deck-more[open]").forEach((other) => {
      if (other !== details) other.open = false;
    });
  });
  return details;
}

/**
 * Build a deck tile.
 *
 * @param {Object} deck A summary from GET /api/decks.
 * @param {Object} options
 * @param {function(): void} options.onOpen
 * @param {function(): void} [options.onDuplicate] Full tile only: in the More menu.
 * @param {function(): void} [options.onDelete] Full tile only: in the More menu.
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

  const updated = formatDay(deck.updated);
  if (updated) meta.push(`Updated ${updated}`);

  const open = h("button", {
    type: "button", class: "btn btn-primary btn-compact", onclick: onOpen,
  }, "Open");

  const title = h("button", { type: "button", class: "deck-name", onclick: onOpen });
  title.textContent = deck.name;
  const body = h("div", { class: "deck-body" },
    h("h3", { class: "deck-title" }, title),
    deck.commander
      ? h("p", { class: "deck-commander", text: deck.commander.name || deck.commander }) : null,
    h("p", { class: "deck-meta", text: meta.join(" · ") }),
    h("div", { class: "deck-actions" }, open, deckMenu(deck, { onDuplicate, onDelete, up: true })));
  return h("article", { class: "deck-tile" }, artOf(deck, false), body);
}
