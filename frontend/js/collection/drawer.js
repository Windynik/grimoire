// The card drawer of the Vault: a panel on the right with the large card
// image, the card facts, the legality grid, and the decks that hold the card.
// It moves through a list of cards with the arrow keys.
//
// Server text goes in with textContent only. The mana cost and the oracle text
// go through manaNode and renderOracleText, the one path that sets innerHTML.

import { h, manaNode } from "../shared/dom.js";
import { cardImage, cardImg } from "../shared/images.js";
import { renderOracleText } from "../shared/mana.js";
import { animate, reducedMotion } from "../shared/motion.js";
import * as api from "./api.js";
import { editable, trapTab } from "./keys.js";
import { formatCardPrice, formatMoney } from "./numbers.js";
import { unitPrice } from "./tile.js";

const FORMATS = ["commander", "standard", "pioneer", "modern", "legacy", "vintage", "pauper", "brawl"];
const MAX_TILT = 8; // degrees at the edge of the image
const LEGAL = new Set(["legal", "restricted"]);

const state = {
  els: null, // {scrim, root, ...}
  cards: [],
  index: 0,
  back: false,
  options: {},
  trigger: null,
  token: 0, // grows with every card shown; late answers check it
  flipping: false,
};

const coarsePointer = () => Boolean(window.matchMedia && window.matchMedia("(pointer: coarse)").matches);
const isOpen = () => Boolean(state.els && state.els.root.classList.contains("is-open"));
const current = () => state.cards[state.index];
const capital = (s) => s.charAt(0).toUpperCase() + s.slice(1);

// ---- build -----------------------------------------------------------------

function build() {
  const scrim = h("div", { class: "vault-dscrim", "aria-hidden": "true" });
  const close = h("button", { type: "button", class: "vault-dclose", "aria-label": "Close" }, "✕");
  const face = h("div", { class: "vault-dface" });
  const head = h("div", { class: "vault-dhead" }, face);
  const flip = h("button", {
    type: "button", class: "vault-dflip", "aria-pressed": "false", "aria-keyshortcuts": "F",
  }, "Flip");
  const body = h("div", { class: "vault-dbody" });
  const prev = h("button", { type: "button", class: "vault-dprev", "aria-label": "Previous card" }, "← previous");
  const next = h("button", { type: "button", class: "vault-dnext", "aria-label": "Next card" }, "next →");
  const pos = h("span", { class: "vault-dpos", "aria-live": "polite" });
  const nav = h("div", { class: "vault-dnav" }, prev, pos, next);
  const root = h("aside", {
    class: "vault-drawer", role: "dialog", "aria-modal": "true", "aria-label": "Card details", tabindex: "-1",
  }, close, head, flip, body, nav);
  root.inert = true;
  document.body.append(scrim, root);

  scrim.addEventListener("click", closeDrawer);
  close.addEventListener("click", closeDrawer);
  prev.addEventListener("click", () => go(-1));
  next.addEventListener("click", () => go(1));
  flip.addEventListener("click", flipCard);
  root.addEventListener("click", (event) => {
    if (event.target.closest(".vault-decks a")) closeDrawer(false);
  });
  attachTilt(head, face);
  state.els = { scrim, root, close, face, head, flip, body, prev, next, pos };
}

function attachTilt(head, face) {
  head.addEventListener("pointermove", (event) => {
    if (event.pointerType === "touch" || reducedMotion() || coarsePointer()) return;
    const box = face.getBoundingClientRect();
    if (!box.width || !box.height) return;
    const px = Math.min(1, Math.max(0, (event.clientX - box.left) / box.width));
    const py = Math.min(1, Math.max(0, (event.clientY - box.top) / box.height));
    face.classList.add("is-tilting");
    face.style.transform = `rotateX(${Math.round((0.5 - py) * 2 * MAX_TILT * 100) / 100}deg) `
      + `rotateY(${Math.round((px - 0.5) * 2 * MAX_TILT * 100) / 100}deg)`;
  });
  const flat = () => {
    face.classList.remove("is-tilting");
    face.style.transform = "";
  };
  head.addEventListener("pointerleave", flat);
  head.addEventListener("pointercancel", flat);
}

// ---- content ---------------------------------------------------------------

function image(card, back) {
  if (!cardImage(card, back ? "back" : "front")) {
    return h("div", { class: "vault-dnoimg" }, h("span", { text: String(card.name || "") }));
  }
  return cardImg(card, {
    face: back ? "back" : "front", alt: back ? `${card.name} (back)` : String(card.name || ""),
    className: "vault-dimg", priority: "high",
  });
}

function fact(label, value) {
  return h("div", null, h("b", { text: label }), h("span", { text: value }));
}

function factsOf(card) {
  const copies = Math.floor(Number(card.quantity));
  const owned = Number.isFinite(copies) && copies > 0;
  const price = typeof card.price === "number" ? card.price : unitPrice(card.prices, Boolean(card.foil));
  const nodes = [];
  if (owned) {
    nodes.push(fact("Owned", `×${copies}${card.foil ? " foil" : ""}`));
    nodes.push(fact("Price", formatCardPrice(price)));
    const value = typeof card.value === "number" ? card.value : price * copies;
    nodes.push(fact("Value", price > 0 || card.value ? formatMoney(value) : "—"));
  } else {
    nodes.push(h("div", { class: "vault-notowned" }, h("b", { text: "Collection" }),
      h("span", { text: "Not in your collection" })));
    nodes.push(fact("Price", formatCardPrice(price)));
  }
  return nodes;
}

function legalGrid(card) {
  const legal = card.legalities || {};
  return FORMATS.map((name) => {
    const ok = LEGAL.has(legal[name]);
    const cell = h("span", { class: ok ? "" : "no", "aria-label": `${capital(name)}: ${ok ? "legal" : "not legal"}` },
      h("span", { text: capital(name), "aria-hidden": "true" }),
      h("span", { text: ok ? "✓" : "✕", "aria-hidden": "true" }));
    return cell;
  });
}

function typeLine(card) {
  return [card.type_line, card.set_name, card.rarity].filter(Boolean).join(" · ");
}

function show() {
  const card = current();
  const { els } = state;
  const token = ++state.token;
  state.back = false;
  els.face.replaceChildren(image(card, false));
  els.flip.hidden = !(cardImage(card, "front") && cardImage(card, "back"));
  els.flip.setAttribute("aria-pressed", "false");

  const name = h("h2", { class: "vault-dname", text: String(card.name || "") });
  const cost = card.mana_cost ? manaNode(card.mana_cost, "vault-dcost") : null;
  const oracle = card.oracle_text ? h("div", { class: "vault-oracle" }) : null;
  if (oracle) oracle.innerHTML = renderOracleText(card.oracle_text);
  const decks = h("div", { class: "vault-decks", hidden: true });
  const rank = Number.isFinite(Number(card.edhrec_rank)) && Number(card.edhrec_rank) > 0
    ? h("p", { class: "vault-rank", text: `EDHREC #${Math.round(Number(card.edhrec_rank)).toLocaleString("en-US")}` })
    : null;
  els.body.replaceChildren(...[
    h("div", { class: "vault-dtitle" }, name, cost),
    h("div", { class: "vault-dtype", text: typeLine(card) }),
    oracle,
    h("div", { class: "vault-facts" }, ...factsOf(card)),
    rank,
    h("div", { class: "vault-legal" }, ...legalGrid(card)),
    decks].filter(Boolean));

  els.pos.textContent = `${state.index + 1} of ${state.cards.length}`;
  els.prev.disabled = state.index <= 0;
  els.next.disabled = state.index >= state.cards.length - 1;
  loadDecks(card, decks, token);
}

async function loadDecks(card, box, token) {
  if (!card.scryfall_id) return;
  let usage;
  try {
    usage = await api.deckUsage([card.scryfall_id]);
  } catch (error) {
    return;
  }
  if (token !== state.token || !box.isConnected) return;
  const decks = (usage && usage[card.scryfall_id]) || [];
  if (!decks.length) return;
  box.hidden = false;
  box.replaceChildren(h("b", { text: "In your decks" }),
    h("ul", null, ...decks.map((deck) => h("li", null,
      h("a", { href: `#deck/${encodeURIComponent(deck.deck_id)}`, text: String(deck.name || "") })))));
}

// ---- actions ---------------------------------------------------------------

function go(step) {
  const next = state.index + step;
  if (next < 0 || next >= state.cards.length) return;
  state.index = next;
  show();
  if (typeof state.options.onNavigate === "function") state.options.onNavigate(current(), next);
}

// Turn the image to the other face: a quarter turn out, the swap, a quarter turn in.
async function flipCard() {
  const card = current();
  if (!card || state.els.flip.hidden || state.flipping) return;
  const { els } = state;
  const token = state.token;
  state.flipping = true;
  state.back = !state.back;
  els.flip.setAttribute("aria-pressed", String(state.back));
  const wanted = state.back;
  const view = () => els.face.firstElementChild;
  try {
    await animate(view(), [{ transform: "rotateY(0deg)" }, { transform: "rotateY(90deg)" }], {
      duration: "fast", easing: "ease-in",
    });
    if (token !== state.token) return;
    const next = image(card, wanted);
    els.face.replaceChildren(next);
    await animate(next, [{ transform: "rotateY(-90deg)" }, { transform: "rotateY(0deg)" }], { duration: "fast" });
  } finally {
    state.flipping = false;
  }
}

function onKey(event) {
  if (!isOpen() || event.defaultPrevented) return;
  if (event.key === "Tab") {
    trapTab(state.els.root, event);
    return;
  }
  if (event.altKey || event.metaKey || event.ctrlKey) return;
  if (event.key === "Escape") {
    event.preventDefault();
    closeDrawer();
  } else if (editable(event.target)) {
    // Typing is not a command.
  } else if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
    event.preventDefault();
    go(event.key === "ArrowRight" ? 1 : -1);
  } else if (event.key === "f" || event.key === "F") {
    event.preventDefault();
    flipCard();
  }
}

/**
 * Open the drawer on one card of a list.
 *
 * @param {Object[]} cards The cards the arrow keys move through.
 * @param {number} index The card to show.
 * @param {Object} [options]
 * @param {function(Object, number)} [options.onNavigate] Called with the card
 *   and its index after the arrows move to another card.
 */
export function openDrawer(cards, index, options = {}) {
  if (!Array.isArray(cards) || !cards[index]) return;
  if (!state.els) build();
  const { els } = state;
  if (!isOpen()) {
    state.trigger = document.activeElement && document.activeElement !== document.body
      ? document.activeElement : null;
    document.addEventListener("keydown", onKey, true);
  }
  state.cards = cards;
  state.index = index;
  state.options = options;
  show();
  els.root.inert = false;
  els.root.classList.add("is-open");
  els.scrim.classList.add("is-open");
  els.close.focus();
}

/** Close the drawer. The focus goes back to the control that opened it. */
export function closeDrawer(returnFocus = true) {
  if (!isOpen()) return;
  const { els } = state;
  state.token += 1;
  els.root.classList.remove("is-open");
  els.scrim.classList.remove("is-open");
  els.root.inert = true;
  document.removeEventListener("keydown", onKey, true);
  const trigger = state.trigger;
  state.trigger = null;
  if (returnFocus !== false && trigger && trigger.isConnected && typeof trigger.focus === "function") {
    trigger.focus();
  }
}
