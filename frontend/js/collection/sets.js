// The Sets view of the Vault: a grid of set tiles with completion, and the
// checklist of one set (owned cards in color, missing cards dimmed).
//
// A set counts each card name once. A set can hold more owned names than it
// has catalog names (tokens): the percent and the bar stop at 100%, and the
// count still shows the true numbers. A set with no catalog names shows only
// the owned count.
//
// Server text goes in with textContent only (h()).

import { h } from "../shared/dom.js";
import { cardImg } from "../shared/images.js";
import { formatCardPrice, formatCount } from "./numbers.js";
import { vaultTile } from "./tile.js";

const num = (value) => {
  const n = Number(value);
  return Number.isFinite(n) && n > 0 ? n : 0;
};

/** The completion of a set from 0 to 1. A set with no total has 0. */
export function completion(set) {
  const total = num(set && set.total);
  if (!total) return 0;
  return Math.min(1, num(set.owned) / total);
}

/** The whole percent (rounded down) of a set, from 0 to 100. */
export function percentOf(set) {
  return Math.floor(completion(set) * 100);
}

const nameOf = (set) => String((set && (set.name || set.code)) || "");

// The name of a set when it adds to the code. The index gives the code for a set it has no name for.
const shownName = (set) => {
  const name = String((set && set.name) || "");
  return name.toLowerCase() === String((set && set.code) || "").toLowerCase() ? "" : name;
};

/** The sets that match a search text (a part of the name or of the code). */
export function filterSets(sets, q) {
  const needle = String(q || "").trim().toLowerCase();
  if (!needle) return sets.slice();
  return sets.filter((set) => String(set.name || "").toLowerCase().includes(needle)
    || String(set.code || "").toLowerCase().includes(needle));
}

/** A sorted copy: "pct" (% complete), "owned" (most owned), or "name". */
export function sortSets(sets, sort) {
  const byName = (a, b) => nameOf(a).localeCompare(nameOf(b));
  const compare = {
    pct: (a, b) => Boolean(!num(a.total)) - Boolean(!num(b.total)) || completion(b) - completion(a) || num(b.owned) - num(a.owned) || byName(a, b),
    owned: (a, b) => num(b.owned) - num(a.owned) || byName(a, b),
    name: byName,
  }[sort] || byName;
  return sets.slice().sort(compare);
}

function bar(ratio, className) {
  const fill = h("i");
  fill.style.transform = `scaleX(${Math.round(ratio * 1000) / 1000})`;
  return h("span", { class: className, "aria-hidden": "true" }, fill);
}

// A set with no total (a token-only code) has no ratio, no percent, and no bar.
const hasTotal = (set) => num(set && set.total) > 0;

function countText(set) {
  if (!hasTotal(set)) return `${formatCount(set.owned)} owned`;
  return `owned ${formatCount(set.owned)} / ${formatCount(set.total)}`;
}

/** One set tile. onOpen runs with the set on a click. */
export function setTile(set, onOpen) {
  const code = String(set.code || "").toUpperCase();
  const pct = percentOf(set);
  const complete = hasTotal(set) ? `${pct}% complete, ` : "";
  const label = `${code}, ${nameOf(set)}, ${countText(set)}, ${complete}${formatCardPrice(set.value)}`;
  const tile = h("button", {
    type: "button", class: `vault-set${pct >= 100 ? " is-complete" : ""}`, "data-code": String(set.code || ""),
    "aria-label": label,
  },
  set.art_id ? h("span", { class: "vault-set-art", "aria-hidden": "true" },
    cardImg({ scryfall_id: set.art_id, image_url: `/api/images/${set.art_id}/front`, name: "" },
      { size: "small", className: "vault-set-img" })) : null,
  h("span", { class: "vault-set-code", text: code }),
  h("span", { class: "vault-set-name", text: shownName(set) }),
  h("span", { class: "vault-set-count" },
    h("b", { text: countText(set) }), hasTotal(set) ? h("em", { text: `${pct}%` }) : null),
  hasTotal(set) ? bar(completion(set), "vault-set-bar") : null,
  h("span", { class: "vault-set-value", text: formatCardPrice(set.value) }));
  tile.addEventListener("click", () => onOpen(set, tile));
  return tile;
}

/** A message with an optional Try again button. */
export function renderSetsMessage(root, title, hint, onRetry) {
  root.replaceChildren(h("div", { class: "vault-empty vault-sets-empty" },
    h("p", { class: "vault-empty-title", text: title }),
    hint ? h("p", { class: "vault-empty-hint", text: hint }) : null,
    onRetry ? h("button", { type: "button", class: "btn btn-secondary vault-retry", text: "Try again", onclick: onRetry }) : null));
}

/**
 * Fill root with the grid of set tiles.
 *
 * @param {HTMLElement} root
 * @param {Object[]} sets The sets, already filtered and sorted.
 * @param {function(Object, HTMLElement)} onOpen
 */
export function renderSetGrid(root, sets, onOpen) {
  if (!sets.length) {
    renderSetsMessage(root, "No set matches that.", "Search by set name or code.");
    return;
  }
  root.replaceChildren(h("div", { class: "vault-sets-grid" }, ...sets.map((set) => setTile(set, onOpen))));
}

// The cards of a checklist, with a quantity of 0 for a missing card.
function normalize(cards) {
  return (cards || []).map((card) => ({ ...card, quantity: num(card.quantity) }));
}

function checkTile(card, onOpen) {
  const tile = vaultTile(card, { onOpen });
  if (!card.quantity) {
    tile.classList.add("is-missing");
    tile.setAttribute("aria-label", `${tile.getAttribute("aria-label")}, not in your collection`);
  }
  return tile;
}

/**
 * Fill root with the checklist of one set.
 *
 * @param {HTMLElement} root
 * @param {Object} data The answer of setCards.
 * @param {Object} options
 * @param {function} options.onBack Runs on "Back to sets".
 * @param {function(Object[], number)} options.onOpenCard Opens a card of the
 *   shown list in the drawer.
 * @param {function(HTMLElement)} [options.onGrid] Called with each new card grid.
 */
export function renderChecklist(root, data, { onBack, onOpenCard, onGrid }) {
  const cards = normalize(data.cards);
  const set = { owned: data.owned, total: data.total };
  let missingOnly = false;

  const back = h("button", { type: "button", class: "btn btn-secondary btn-compact vault-check-back", text: "Back to sets", onclick: onBack });
  const toggle = h("button", {
    type: "button", class: "btn btn-secondary btn-compact vault-check-missing", "aria-pressed": "false", text: "Missing only",
  });
  const grid = h("div", { class: "vault-grid vault-checklist", "aria-label": "Set checklist" });
  if (onGrid) onGrid(grid);

  const draw = () => {
    const shown = missingOnly ? cards.filter((c) => !c.quantity) : cards;
    const open = (card) => onOpenCard(shown, shown.indexOf(card));
    if (!shown.length) {
      grid.replaceChildren(h("p", { class: "vault-empty-title vault-check-none", text: cards.length
        ? "Nothing is missing. This set is complete." : "This set has no cards." }));
      return;
    }
    grid.replaceChildren(...shown.map((card) => checkTile(card, open)));
  };
  toggle.addEventListener("click", () => {
    missingOnly = !missingOnly;
    toggle.setAttribute("aria-pressed", String(missingOnly));
    draw();
  });

  const head = h("header", { class: "vault-check-head" },
    h("div", { class: "vault-check-bar" }, back, toggle),
    h("div", { class: "vault-check-id" },
      h("span", { class: "vault-check-code", text: String(data.code || "").toUpperCase() }),
      h("div", { class: "vault-check-text" },
        h("h2", { class: "vault-check-title", text: shownName(data) || "Set checklist" }),
        h("p", { class: "vault-check-stats" },
          h("span", { class: "vault-check-count", text: countText(set) }),
          hasTotal(set) ? h("span", { class: "vault-check-pct", text: ` · ${percentOf(set)}% complete` }) : null),
        hasTotal(set) ? bar(completion(set), "vault-set-bar vault-check-meter") : null)));
  draw();
  root.replaceChildren(head, grid);
  back.focus();
}
