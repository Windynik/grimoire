// Sample hand of the editor: deal 7 cards from the main section, take a
// mulligan, or draw one more. Card names go in with textContent only. The hand
// is kept per root, so an editor re-render does not deal again.

import { h } from "../shared/dom.js";
import { drawHand, entryKey } from "./model.js";

const HAND_SIZE = 7;

const hands = new WeakMap();

function mainCount(state) {
  return (state.sections.main || []).reduce((sum, entry) => sum + entry.count, 0);
}

// Main entries minus the copies already in the hand.
function libraryEntries(state, cards) {
  const inHand = new Map();
  cards.forEach((card) => {
    const key = entryKey(card);
    inHand.set(key, (inHand.get(key) || 0) + 1);
  });
  return (state.sections.main || [])
    .map((entry) => ({ ...entry, count: entry.count - (inHand.get(entryKey(entry)) || 0) }))
    .filter((entry) => entry.count > 0);
}

function faceNode(card) {
  const face = h("span", { class: "hand-face hand-face-front" });
  if (card.image_url) {
    face.append(h("img", { src: card.image_url, alt: card.name, loading: "lazy" }));
  } else {
    face.classList.add("is-text");
    face.textContent = card.name;
  }
  return face;
}

function cardNode(card, index, dealIndex) {
  const inner = h("span", { class: "hand-card-inner" },
    faceNode(card), h("span", { class: "hand-face hand-face-back", "aria-hidden": "true" }));
  const node = h("li", { class: "hand-card", tabindex: "0", "aria-label": card.name }, inner);
  if (dealIndex !== null) {
    node.classList.add("is-dealing");
    node.style.setProperty("--slot", String(index));
    node.style.setProperty("--deal-delay", `${dealIndex * 60}ms`);
  }
  return node;
}

function build(root, state) {
  const buttons = {
    deal: h("button", { type: "button", class: "btn btn-primary btn-compact" }, "Draw 7"),
    mulligan: h("button", { type: "button", class: "btn btn-secondary btn-compact" }, "Mulligan"),
    draw: h("button", { type: "button", class: "btn btn-secondary btn-compact" }, "Draw"),
  };
  const info = h("span", { class: "hand-info", role: "status", "aria-live": "polite" });
  const list = h("ol", { class: "hand-cards", "aria-label": "Sample hand" });
  const empty = h("p", { class: "hand-empty", text: "Add cards to the main deck to draw a hand." });
  const table = h("div", { class: "hand-table" },
    h("span", { class: "hand-stack", "aria-hidden": "true" }), list);
  root.replaceChildren(
    h("div", { class: "hand-tools" }, buttons.deal, buttons.mulligan, buttons.draw, info),
    table, empty);

  const hand = { cards: [], buttons, info, list, empty, table };

  // Show the cards from index "from" on as newly dealt.
  function paint(from) {
    list.replaceChildren(...hand.cards.map((card, i) => cardNode(card, i, i >= from ? i - from : null)));
    hand.update(state);
  }

  function deal() {
    hand.cards = drawHand(state.sections.main, Math.random, HAND_SIZE);
    paint(0);
  }

  buttons.deal.addEventListener("click", deal);
  buttons.mulligan.addEventListener("click", deal);
  buttons.draw.addEventListener("click", () => {
    const [card] = drawHand(libraryEntries(state, hand.cards), Math.random, 1);
    if (!card) return;
    hand.cards = hand.cards.concat(card);
    paint(hand.cards.length - 1);
  });

  hand.update = (current) => {
    const total = mainCount(current);
    const dealt = hand.cards.length > 0;
    const left = libraryEntries(current, hand.cards).reduce((sum, e) => sum + e.count, 0);
    buttons.deal.hidden = dealt;
    buttons.mulligan.hidden = !dealt;
    buttons.draw.hidden = !dealt;
    buttons.deal.disabled = total === 0;
    buttons.mulligan.disabled = total === 0;
    buttons.draw.disabled = left === 0;
    empty.hidden = total > 0;
    table.hidden = total === 0;
    info.textContent = dealt ? `${hand.cards.length} in hand, ${left} left in the deck` : "";
  };
  return hand;
}

/**
 * Render the sample hand into root. The first call builds it; later calls
 * only refresh the button states and the counts.
 *
 * @param {HTMLElement} root
 * @param {{sections: Object}} state Editor state; the hand reads sections.main.
 */
export function renderHand(root, state) {
  let hand = hands.get(root);
  if (!hand || !root.contains(hand.table)) {
    hand = build(root, state);
    hands.set(root, hand);
  }
  hand.update(state);
}
