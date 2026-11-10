// The vault card tile: a card face with a glare, a foil shine, stacked backs
// for copies, a gold quantity badge, and a caption. attachTilt makes the tiles
// of a root tilt toward the pointer.
//
// Server text goes in with textContent only. The mana cost goes through manaNode.

import { h, manaNode } from "../shared/dom.js";
import { cardImg } from "../shared/images.js";
import { formatCardPrice } from "./numbers.js";
import { reducedMotion } from "../shared/motion.js";

const MAX_TILT = 9; // degrees at the edge of the face
const LIFT = 14; // px toward the viewer while the face tilts
// A missing card of a checklist (is-missing) does not tilt.
const TILE = ".vault-tile:not(.is-missing)";
const FACE = ".vault-face";
const FRAME = ".vault-frame";
// Below the face (over the caption), the tilt fades to flat over this part of the face height.
const FALLOFF = 0.3;
const POINTER_PROPS = ["--mx", "--my", "--hx", "--hy"];

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

function label(card, copies, price) {
  const parts = [String(card.name || "")];
  if (card.foil) parts.push("foil");
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
  face.append(cardImg(card, { className: "vault-img" }), h("span", { class: "vault-glare", "aria-hidden": "true" }));
  if (foil) {
    face.append(
      h("span", { class: "vault-holo", "aria-hidden": "true" }),
      h("span", { class: "vault-foil-tag", "aria-hidden": "true", text: "FOIL" }),
    );
  }

  const caption = h("div", { class: "vault-cap" },
    h("span", { class: "vault-name", text: String(card.name || "") }),
    card.new ? h("span", { class: "vault-new", "aria-hidden": "true", text: "NEW" }) : null,
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

const coarsePointer = () => Boolean(typeof window !== "undefined" && window.matchMedia
  && window.matchMedia("(pointer: coarse)").matches);

const clamp = (value) => Math.min(1, Math.max(0, value));
// Two decimals, and never "-0".
const round = (value) => Math.round(value * 100) / 100 + 0;
const percent = (value) => `${round(value * 100)}%`;

// The roots that already tilt.
const tilting = new WeakSet();

/**
 * Make the vault tiles inside root tilt toward the pointer: up to 9 degrees on
 * each axis and a lift of 14 px. The glare and the foil shine follow the
 * pointer through the --mx, --my, --hx and --hy properties of the face.
 * One set of listeners on root serves every tile, and one animation frame
 * applies the newest pointer position. The face returns flat when the pointer
 * leaves the tile.
 *
 * Under reduced motion, or with a coarse (touch) primary pointer, no listener
 * goes on. A second call for the same root does nothing.
 */
export function attachTilt(root) {
  if (!root || tilting.has(root) || reducedMotion() || coarsePointer()) return;
  tilting.add(root);

  let active = null; // the tile that tilts now
  let point = null; // the newest pointer position: {tile, x, y}
  let frame = 0;

  const flatten = (tile) => {
    const face = tile.querySelector(FACE);
    tile.classList.remove("is-tilting");
    if (!face) return;
    face.style.transform = "";
    POINTER_PROPS.forEach((name) => face.style.removeProperty(name));
  };

  const reset = () => {
    if (frame) cancelAnimationFrame(frame);
    frame = 0;
    point = null;
    if (active) flatten(active);
    active = null;
  };

  const apply = () => {
    frame = 0;
    const next = point;
    point = null;
    if (!next || !next.tile.isConnected) return;
    const { tile, x, y } = next;
    const face = tile.querySelector(FACE);
    if (!face) return;
    if (tile !== active) {
      if (active) flatten(active);
      active = null;
      // The preference can change after attach.
      if (reducedMotion()) return;
      active = tile;
      // The class swaps the slow return for a short linear transition that
      // smooths the first pose and the steps between frames.
      tile.classList.add("is-tilting");
    }
    // The frame does not turn, so its box stays true while the face tilts.
    const frameEl = tile.querySelector(FRAME);
    const box = (frameEl || tile).getBoundingClientRect();
    if (!box.width || !box.height) return;
    const rawX = (x - box.left) / box.width;
    const rawY = (y - box.top) / box.height;
    const px = clamp(rawX);
    const py = clamp(rawY);
    // Outside the face (the caption, the badge), the tilt fades out with the distance.
    const outside = Math.max(Math.abs(rawX - px), Math.abs(rawY - py));
    const fade = Math.max(0, 1 - outside / FALLOFF);
    const rx = round((0.5 - py) * 2 * MAX_TILT * fade);
    const ry = round((px - 0.5) * 2 * MAX_TILT * fade);
    face.style.transform = `rotateX(${rx}deg) rotateY(${ry}deg) translateZ(${LIFT}px)`;
    face.style.setProperty("--mx", percent(px));
    face.style.setProperty("--my", percent(py));
    face.style.setProperty("--hx", percent(px));
    face.style.setProperty("--hy", percent(py));
  };

  const tileOf = (target) => (target && typeof target.closest === "function"
    ? target.closest(TILE) : null);

  root.addEventListener("pointermove", (event) => {
    if (event.pointerType === "touch") return;
    const tile = tileOf(event.target);
    if (!tile || !root.contains(tile)) {
      if (active) reset();
      return;
    }
    point = { tile, x: event.clientX, y: event.clientY };
    if (!frame) frame = requestAnimationFrame(apply);
  });

  root.addEventListener("pointerout", (event) => {
    const tile = tileOf(event.target);
    if (!tile || tile.contains(event.relatedTarget)) return;
    if (tile === active || (point && point.tile === tile)) reset();
  });

  root.addEventListener("pointerleave", reset);
}
