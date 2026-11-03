// The list view of the Vault: a header of sort buttons, then one focusable row
// per card (thumbnail, name, cost, type, set, rarity, quantity, finish, price).
// The header sits outside the role="list" body.
//
// Server text goes in with textContent only (h()).

import { h, manaNode } from "../shared/dom.js";
import { cardImg } from "../shared/images.js";
import { formatCardPrice } from "./numbers.js";

const COLUMNS = [
  ["Name", "name", "vault-row-name"],
  ["Cost", "mv", "vault-row-cost"],
  ["Type", null, "vault-row-type"],
  ["Set", "set", "vault-row-set"],
  ["Rarity", "rarity", "vault-row-rarity"],
  ["Qty", null, "vault-row-qty"],
  ["Finish", null, "vault-row-foil"],
  ["Price", "price", "vault-row-price"],
];

/**
 * One row of the list.
 *
 * @param {Object} card
 * @param {function(Object)} onOpen Runs on a click, Enter, or Space.
 */
export function listRow(card, onOpen) {
  const qty = Number(card.quantity) || 0;
  const price = typeof card.price === "number" ? card.price : parseFloat(card.price) || 0;
  const rarity = String(card.rarity || "").toLowerCase();
  const row = h("div", {
    class: `vault-row${card.foil ? " is-foil" : ""}`, role: "listitem", tabindex: "0",
    "aria-label": [card.name, card.foil ? "foil" : null, qty > 1 ? `${qty} copies` : null,
      price ? formatCardPrice(price) : null].filter(Boolean).join(", "),
  },
  cardImg(card, { className: "vault-row-thumb", size: "small" }),
  h("span", { class: "vault-row-name", text: String(card.name || "") }),
  manaNode(card.mana_cost, "vault-row-cost"),
  h("span", { class: "vault-row-type", text: String(card.type_line || "") }),
  h("span", { class: "vault-row-set", text: String(card.set || "").toUpperCase(), title: card.set_name || null }),
  h("span", { class: "vault-row-rarity", title: rarity || null },
    h("i", { class: `vault-gem vault-gem-${rarity || "none"}`, "aria-hidden": "true" })),
  h("span", { class: "vault-row-qty", text: qty > 0 ? `×${qty}` : "" }),
  h("span", { class: "vault-row-foil", text: card.foil ? "Foil" : "" }),
  h("span", { class: "vault-row-price", text: formatCardPrice(price) }));
  row.addEventListener("click", () => onOpen(card));
  row.addEventListener("keydown", (event) => {
    if (event.target !== row || event.repeat) return;
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      onOpen(card);
    }
  });
  return row;
}

/**
 * The header row. A column with a sort is a button; aria-pressed marks the
 * sorted column, and a hidden text names the direction.
 *
 * @param {{sort: string, sorts: string[], onSort: function(string)}} options
 *   onSort gets the next sort: Price toggles between "price" and "price_asc".
 */
export function listHead({ sort, sorts, onSort }) {
  const cells = COLUMNS.map(([name, key, className]) => {
    if (!key || !sorts.includes(key)) return h("span", { class: className, text: name });
    const active = sort === key || (key === "price" && sort === "price_asc");
    const shown = key === "price" && sort === "price" ? "descending" : "ascending";
    return h("button", {
      type: "button", class: `${className} vault-row-sort${active ? " is-on" : ""}`, "data-sort": key,
      "data-direction": active ? shown : null, "aria-pressed": String(active),
      onclick: () => onSort(key === "price" && sort === "price" ? "price_asc" : key),
    }, name, active ? h("span", { class: "vault-sr", text: ` sorted ${shown}` }) : null);
  });
  return h("div", { class: "vault-row-head" }, h("span", { class: "vault-row-thumb" }), cells);
}

/** Fill the list: the header, then a role="list" body with the rows. Returns the body. */
export function renderList(root, cards, { sort, sorts, onSort, onOpen }) {
  const body = h("div", { class: "vault-list-body", role: "list", "aria-label": "Cards" },
    cards.map((card) => listRow(card, onOpen)));
  root.replaceChildren(listHead({ sort, sorts, onSort }), body);
  return body;
}

/** ↑ and ↓ move the focus between the rows. */
export function onListKey(event) {
  if (event.key !== "ArrowDown" && event.key !== "ArrowUp") return;
  const row = event.target.closest && event.target.closest(".vault-row");
  if (!row) return;
  event.preventDefault();
  const target = event.key === "ArrowDown" ? row.nextElementSibling : row.previousElementSibling;
  if (target && target.classList.contains("vault-row")) target.focus();
}
