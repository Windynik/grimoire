// The collection card tile: a card face with stacked backs for copies, a
// quantity badge, a FOIL tag, and a caption.
//
// Server text goes in with textContent only. The mana cost goes through manaNode.

import { h, manaNode } from "../shared/dom.js";
import { cardImg } from "../shared/images.js";
import { formatCardPrice } from "./numbers.js";

// The US dollar price keys of each finish, best first (backend/core/prices.py).
// EUR and MTGO ticket prices are other units, so they never count.
const PRICE_ORDER = {
  normal: ["usd", "usd_foil"],
  foil: ["usd_foil", "usd"],
  etched: ["usd_etched", "usd_foil", "usd"],
};

/** The finish of a stored foil value: "normal", "foil" or "etched". */
function finishOf(foil) {
  if (typeof foil === "boolean") return foil ? "foil" : "normal";
  const text = String(foil || "").trim().toLowerCase();
  if (text.includes("etch")) return "etched";
  return ["", "none", "normal", "false"].includes(text) ? "normal" : "foil";
}

/**
 * The US dollar price of one copy in its finish: the first number above 0, else 0.
 * `foil` is the stored value ("normal", "foil", "etched") or a boolean.
 */
export function unitPrice(prices, foil) {
  const order = PRICE_ORDER[finishOf(foil)];
  for (const key of order) {
    const value = parseFloat(prices && prices[key]);
    if (Number.isFinite(value) && value > 0) return value;
  }
  return 0;
}

const copiesOf = (card) => {
  const value = Math.floor(Number(card.quantity));
  return Number.isFinite(value) && value > 0 ? value : 0;
};

// The card flags, as a tile and the drawer name them.
export const FLAG_LABELS = { trade: "For trade", sell: "To sell", keep: "Keep", lent: "Lent out" };

function flagMark(card) {
  const first = (card.flags || [])[0];
  return first ? h("span", { class: `vault-flag vault-flag-${first}`, "aria-hidden": "true",
    text: (FLAG_LABELS[first] || first).toUpperCase() }) : null;
}

/** Show the card's flags on its tiles (the same printing and finish) after a change. */
export function syncTileFlags(root, card) {
  if (!root || !card || !card.scryfall_id) return;
  root.querySelectorAll(".vault-tile").forEach((tile) => {
    if (tile.dataset.cardId !== card.scryfall_id || tile.classList.contains("is-foil") !== Boolean(card.foil)) return;
    tile.querySelectorAll(".vault-flag").forEach((mark) => mark.remove());
    const mark = flagMark(card);
    const price = tile.querySelector(".vault-price");
    if (mark && price) price.before(mark);
  });
}

function label(card, copies, price) {
  const parts = [String(card.name || "")];
  if (card.foil) parts.push("foil");
  (card.flags || []).forEach((flag) => { if (FLAG_LABELS[flag]) parts.push(FLAG_LABELS[flag].toLowerCase()); });
  if (copies > 1) parts.push(`${copies} copies`);
  if (card.new) parts.push("new");
  if (price) parts.push(formatCardPrice(price));
  return parts.join(", ");
}

/**
 * Build one vault tile.
 *
 * @param {Object} card A card of the collection search (or the archive).
 * @param {Object} [options]
 * @param {number} [options.index] The position in the first page. A number
 *   makes the tile rise in with a stagger; leave it out for no entrance.
 * @param {function(Object, HTMLElement)} [options.onOpen] Called with the card
 *   and the tile on a click, Enter, or Space.
 * @returns {HTMLElement}
 */
export function vaultTile(card, { index, onOpen } = {}) {
  const copies = copiesOf(card);
  const foil = Boolean(card.foil);
  const price = typeof card.price === "number" ? card.price : unitPrice(card.prices, card.foil);

  const face = h("div", { class: "vault-face" });
  if (copies > 1) face.append(h("span", { class: "vault-stack s1", "aria-hidden": "true" }));
  if (copies > 2) face.append(h("span", { class: "vault-stack s2", "aria-hidden": "true" }));
  face.append(cardImg(card, { className: "vault-img" }));
  if (foil) face.append(h("span", { class: "vault-foil-tag", "aria-hidden": "true", text: "FOIL" }));

  const caption = h("div", { class: "vault-cap" },
    h("span", { class: "vault-name", text: String(card.name || "") }),
    card.new ? h("span", { class: "vault-new", "aria-hidden": "true", text: "NEW" }) : null,
    flagMark(card),
    h("span", { class: "vault-price", text: formatCardPrice(price) }));
  const cost = manaNode(card.mana_cost, "vault-cost");
  cost.setAttribute("aria-hidden", "true");

  const tile = h("div", {
    class: "vault-tile", "data-card-id": card.scryfall_id, tabindex: "0", role: "button", "aria-label": label(card, copies, price),
  },
  copies > 1 ? h("span", { class: "vault-qty", "aria-hidden": "true", text: `×${copies}` }) : null,
  h("div", { class: "vault-frame" }, face), caption, cost);
  if (foil) tile.classList.add("is-foil");
  if (card.new) tile.classList.add("is-new");
  if (Number.isInteger(index) && index >= 0) {
    tile.classList.add("is-rising");
    tile.style.setProperty("--tile-i", String(index));
  }

  const open = () => {
    if (typeof onOpen === "function") onOpen(card, tile);
  };
  tile.addEventListener("click", open);
  tile.addEventListener("keydown", (event) => {
    if (event.target !== tile || event.repeat) return;
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      open();
    }
  });
  return tile;
}
