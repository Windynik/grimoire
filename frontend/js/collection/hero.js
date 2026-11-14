// The hero of the Vault: the collection switcher, the lede, the ledger with
// its counters, the color orbs, the fanned hand, and the shelves under it.
//
// Server text goes in with textContent only. Mana symbols are sprite classes.

import { h } from "../shared/dom.js";
import { cardImg } from "../shared/images.js";
import { DURATION, reducedMotion } from "../shared/motion.js";
import { attachTilt, vaultTile } from "./tile.js";
import {
  formatCardPrice, formatCount, formatMoney, longDate, shortDate,
} from "./numbers.js";

export const COLOR_NAMES = {
  W: "White", U: "Blue", B: "Black", R: "Red", G: "Green", C: "Colorless", M: "Multicolor",
};
const ORB_ORDER = ["W", "U", "B", "R", "G", "C", "M"];
const COUNTED_KEY = "grimoire.vault.counted";

export { formatCount, formatMoney, longDate, shortDate };

// ---- the switcher ----------------------------------------------------------

/**
 * Fill the switcher menu: every collection (newest first, as the server gives
 * them), then the archive. onPick(jobId or null) runs on a choice.
 */
export function renderSwitcher(menu, collections, current, onPick) {
  const item = (source, name, meta) => {
    const checked = source === current;
    return h("button", {
      type: "button", class: "vault-switch-item", role: "menuitemradio",
      "aria-checked": String(checked), "data-source": source || "archive",
      onclick: () => onPick(source),
    },
    h("span", { class: "vault-switch-name", text: name }),
    h("span", { class: "vault-switch-meta", text: meta }));
  };
  const rows = collections.map((c) => {
    const date = shortDate(c.created);
    const count = `${formatCount(c.card_count)} ${Number(c.card_count) === 1 ? "card" : "cards"}`;
    return item(c.job_id, String(c.name || "Collection"), date ? `${count} · ${date}` : count);
  });
  rows.push(item(null, "All cards (archive)", "Every card in the card data"));
  menu.replaceChildren(...rows);
}

// ---- the counters ----------------------------------------------------------

let countFrame = 0;

function counted() {
  try {
    return sessionStorage.getItem(COUNTED_KEY) === "1";
  } catch (e) {
    return true;
  }
}

function markCounted() {
  try {
    sessionStorage.setItem(COUNTED_KEY, "1");
  } catch (e) {
    // Without storage the counters count up on each visit.
  }
}

/**
 * Show the final values of the counters. The first time in a session (and
 * not under reduced motion), they count up from 0 with an ease-out.
 *
 * @param {Array<{el: HTMLElement, to: number, format: function(number): string}>} items
 */
export function countUp(items) {
  if (countFrame) cancelAnimationFrame(countFrame);
  countFrame = 0;
  const finish = () => items.forEach((item) => { item.el.textContent = item.format(item.to); });
  if (counted() || reducedMotion() || typeof requestAnimationFrame !== "function") {
    finish();
    return;
  }
  markCounted();
  const length = DURATION.slow * 2;
  const start = performance.now();
  items.forEach((item) => { item.el.textContent = item.format(0); });
  const step = () => {
    const t = Math.min(1, (performance.now() - start) / length);
    if (t >= 1) {
      countFrame = 0;
      finish();
      return;
    }
    const eased = 1 - (1 - t) ** 4;
    items.forEach((item) => { item.el.textContent = item.format(item.to * eased); });
    countFrame = requestAnimationFrame(step);
  };
  countFrame = requestAnimationFrame(step);
}

// ---- the hero --------------------------------------------------------------

function ledgerItem(key, label, note, gold) {
  const value = h("span", { class: "vault-ledger-value" });
  const el = h("div", { class: `vault-ledger-item${gold ? " is-gold" : ""}`, "data-key": key },
    value,
    h("span", { class: "vault-ledger-label", text: label }),
    h("span", { class: "vault-ledger-note", text: note }));
  return { el, value };
}

function orbSymbol(color) {
  if (color === "M") return h("span", { class: "vault-orb-glyph", text: "✦" });
  return h("i", { class: `mana s${color.toLowerCase()}` });
}

/**
 * Fill the lede, the ledger, and the color orbs from an insights response.
 *
 * @param {{lede: HTMLElement, ledger: HTMLElement, orbs: HTMLElement}} parts
 * @param {Object} insights
 * @param {{selected: string[], onOrb: function(string)}} options
 */
export function renderHero(parts, insights, { selected = [], onOrb } = {}) {
  const data = insights || {};
  const date = longDate(data.created);
  parts.lede.textContent = `${formatCount(data.cards)} ${Number(data.cards) === 1 ? "card" : "cards"}, `
    + `${formatCount(data.unique)} of them unique${date ? ` — gathered on ${date}` : ""}.`;

  const rarity = data.rarity || {};
  // The prices are those of the chosen provider (TCGplayer from the card data by default).
  const priceDate = shortDate(data.price_date || data.card_data_date);
  const source = data.price_label ? `${data.price_label} prices` : "Scryfall prices";
  const items = [
    [ledgerItem("value", "Estimated value",
      priceDate ? `Estimate · ${source} from ${priceDate}` : `Estimate · ${source}`, true),
    Number(data.value) || 0, formatMoney],
    [ledgerItem("rares", "Rares & mythics", `${formatCount(rarity.mythic)} mythic`),
      (Number(rarity.rare) || 0) + (Number(rarity.mythic) || 0), formatCount],
    [ledgerItem("foils", "Foils", "the shiny ones"), Number(data.foils) || 0, formatCount],
    [ledgerItem("sets", "Sets", "across your binders"), Number(data.sets) || 0, formatCount],
  ];
  // The value over time, when there are two card-data downloads or more.
  const spark = sparkline(data.history);
  if (spark) {
    const trend = trendText(data.history);
    items[0][0].el.append(spark, h("span", { class: "vault-ledger-trend", text: trend }));
  }
  parts.ledger.replaceChildren(...items.map(([item]) => item.el));
  countUp(items.map(([item, to, format]) => ({ el: item.value, to, format })));

  const colors = data.colors || {};
  const total = ORB_ORDER.reduce((sum, c) => sum + (Number(colors[c]) || 0), 0);
  const most = Math.max(1, ...ORB_ORDER.map((c) => Number(colors[c]) || 0));
  parts.orbs.replaceChildren(...ORB_ORDER.map((color) => {
    const count = Number(colors[color]) || 0;
    const pct = total ? Math.round((count / total) * 100) : 0;
    const bar = h("b");
    bar.style.transform = `scaleX(${Math.round((count / most) * 1000) / 1000})`;
    const on = selected.includes(color);
    return h("button", {
      type: "button", class: `vault-orb vault-orb-${color.toLowerCase()}${on ? " is-on" : ""}`,
      "data-color": color, "aria-pressed": String(on), title: COLOR_NAMES[color],
      "aria-label": `${COLOR_NAMES[color]}: ${pct}% of the cards (${formatCount(count)})`,
      onclick: () => onOrb && onOrb(color),
    },
    h("span", { class: "vault-orb-ball", "aria-hidden": "true" }, orbSymbol(color)),
    h("span", { class: "vault-orb-bar", "aria-hidden": "true" }, bar),
    h("span", { class: "vault-orb-pct", "aria-hidden": "true", text: `${pct}%` }));
  }));
}

/** Mark the orbs of the selected color buckets. */
export function syncOrbs(orbs, selected) {
  orbs.querySelectorAll(".vault-orb").forEach((orb) => {
    const on = selected.includes(orb.dataset.color);
    orb.classList.toggle("is-on", on);
    orb.setAttribute("aria-pressed", String(on));
  });
}

// ---- the fan ---------------------------------------------------------------

/**
 * The cards of the fan, left to right: the spotlight in the middle (or the
 * most valuable card when there is no spotlight), and up to four valuable
 * cards with other names around it. Each card has its offset k (-2 … 2).
 */
export function fanCards(shelves) {
  const spot = shelves && shelves.spotlight ? shelves.spotlight : null;
  const names = new Set(spot ? [spot.name] : []);
  const around = [];
  for (const card of (shelves && shelves.valuable) || []) {
    if (around.length === 4) break;
    if (!card || names.has(card.name)) continue;
    names.add(card.name);
    around.push(card);
  }
  const centre = spot || around.shift();
  if (!centre) return [];
  const placed = [{ card: centre, k: 0, spot: Boolean(spot) }];
  [-1, 1, -2, 2].forEach((k, i) => {
    if (around[i]) placed.push({ card: around[i], k, spot: false });
  });
  return placed.sort((a, b) => a.k - b.k);
}

/**
 * Build the fanned hand in root. onOpen(cards, index) runs on a click.
 * Under reduced motion the fan is still: no hover lift.
 */
export function renderFan(root, shelves, onOpen) {
  const placed = fanCards(shelves);
  const list = placed.map((p) => p.card);
  root.classList.toggle("is-still", reducedMotion());
  const cards = placed.map(({ card, k, spot }, i) => {
    const price = Number(card.price) || 0;
    const tag = spot ? "✦ Today's spotlight" : (k === 0 ? "✦ Most valuable" : formatCardPrice(price));
    const label = [String(card.name || ""), spot ? "today's spotlight" : null, price ? formatCardPrice(price) : null]
      .filter(Boolean).join(", ");
    const el = h("button", {
      type: "button", class: `vault-fan-card${k === 0 ? " is-spot" : ""}`, "data-card-id": card.scryfall_id, "aria-label": label,
      onclick: () => onOpen(list, i),
    },
    h("span", { class: "vault-fan-tag", "aria-hidden": "true", text: tag }),
    cardImg(card, { className: "vault-fan-img", priority: "high" }));
    el.style.setProperty("--k", String(k));
    el.style.setProperty("--ak", String(Math.abs(k)));
    return el;
  });
  root.replaceChildren(
    h("span", { class: "vault-fan-ring", "aria-hidden": "true" }),
    h("span", { class: "vault-fan-glow", "aria-hidden": "true" }),
    ...cards);
  attachFanHover(root);
  return list.length;
}

// The fallback sizes of vault.css, for a root without computed styles.
const FAN_CARD = 206;
const FAN_SPREAD = 64;

function fanSize(root, name, fallback) {
  const value = parseFloat(window.getComputedStyle(root).getPropertyValue(name));
  return Number.isFinite(value) && value > 0 ? value : fallback;
}

/**
 * The fan card at clientX in the resting layout: the top card (lowest |k|)
 * whose resting box holds x, else the card with the nearest centre. The lifted
 * card covers its neighbors, so the pointer target cannot tell which card is
 * under the pointer. The resting layout does not move, so the choice is stable.
 */
export function fanCardAt(root, clientX) {
  const cards = [...root.querySelectorAll(".vault-fan-card")];
  if (!cards.length) return null;
  const box = root.getBoundingClientRect();
  const half = fanSize(root, "--fan-card", FAN_CARD) / 2;
  const spread = fanSize(root, "--fan-spread", FAN_SPREAD);
  const centre = box.left + box.width / 2;
  const away = (el) => Math.abs(clientX - centre - Number(el.style.getPropertyValue("--k")) * spread);
  const top = cards.sort((a, b) => Number(a.style.getPropertyValue("--ak")) - Number(b.style.getPropertyValue("--ak")));
  return top.find((el) => away(el) <= half)
    || top.reduce((best, el) => (away(el) < away(best) ? el : best));
}

// The roots that already track the hover.
const fanHovering = new WeakSet();

/**
 * Track the hovered fan card with the is-hover class. One set of listeners
 * on root serves every render. Touch pointers do not hover.
 */
function attachFanHover(root) {
  if (fanHovering.has(root)) return;
  fanHovering.add(root);
  const hover = (card) => {
    for (const el of root.querySelectorAll(".vault-fan-card")) el.classList.toggle("is-hover", el === card);
  };
  root.addEventListener("pointermove", (event) => {
    if (event.pointerType === "touch") return;
    hover(event.target.closest(".vault-fan-card") ? fanCardAt(root, event.clientX) : null);
  });
  root.addEventListener("pointerleave", () => hover(null));
}

// ---- price history ---------------------------------------------------------

const SVG_NS = "http://www.w3.org/2000/svg";
const SPARK_W = 120;
const SPARK_H = 28;

function svg(tag, attrs) {
  const el = document.createElementNS(SVG_NS, tag);
  Object.entries(attrs).forEach(([key, value]) => el.setAttribute(key, String(value)));
  return el;
}

/** The change of value between the first and the last snapshot: "+$12.40 since 1 Nov 2026". */
export function trendText(history) {
  const points = Array.isArray(history) ? history : [];
  if (points.length < 2) return "";
  const change = (Number(points[points.length - 1].value) || 0) - (Number(points[0].value) || 0);
  const sign = change > 0 ? "+" : change < 0 ? "−" : "±";
  const since = shortDate(points[0].date);
  return `${sign}${formatMoney(Math.abs(change))}${since ? ` since ${since}` : ""}`;
}

/**
 * A small line of the collection value, one point per card-data download.
 * Returns null with fewer than two points.
 */
export function sparkline(history) {
  const points = (Array.isArray(history) ? history : []).map((p) => Number(p.value) || 0);
  if (points.length < 2) return null;
  const low = Math.min(...points);
  const high = Math.max(...points);
  const span = high - low || 1;
  const xy = points.map((value, i) => [
    (i / (points.length - 1)) * (SPARK_W - 4) + 2,
    SPARK_H - 3 - ((value - low) / span) * (SPARK_H - 6),
  ]);
  const label = (history || []).map((p) => `${formatMoney(p.value)} on ${shortDate(p.date)}`).join(", ");
  const root = svg("svg", { class: "vault-spark", viewBox: `0 0 ${SPARK_W} ${SPARK_H}`,
    width: SPARK_W, height: SPARK_H, role: "img", "aria-label": `Value over time: ${label}` });
  root.append(svg("polyline", { class: "vault-spark-line", fill: "none",
    points: xy.map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`).join(" ") }));
  const [lastX, lastY] = xy[xy.length - 1];
  root.append(svg("circle", { class: "vault-spark-dot", cx: lastX.toFixed(1), cy: lastY.toFixed(1), r: 2.5 }));
  return root;
}

function moverRow(card, list, index, onOpen) {
  const quantity = Number(card.quantity) || 1;
  const total = Number(card.total) || 0;
  const sign = total > 0 ? "+" : "−";
  return h("li", { class: `vault-mover ${total > 0 ? "is-up" : "is-down"}` },
    h("button", { type: "button", class: "vault-mover-name", text: String(card.name || ""),
      onclick: () => onOpen(list, index) }),
    h("span", { class: "vault-mover-prices",
      text: `${formatMoney(card.before)} → ${formatMoney(card.after)}${quantity > 1 ? ` ×${quantity}` : ""}` }),
    h("span", { class: "vault-mover-total", text: `${sign}${formatMoney(Math.abs(total))}` }));
}

/**
 * Fill the price movers: the owned cards whose price moved most between the
 * two newest card-data downloads. Returns false (and empties root) when there
 * is nothing to show.
 */
export function renderMovers(root, movers, onOpen) {
  const up = (movers && movers.up) || [];
  const down = (movers && movers.down) || [];
  if (!up.length && !down.length) {
    root.replaceChildren();
    return false;
  }
  const since = shortDate(movers.since);
  const until = shortDate(movers.until);
  const column = (title, list) => h("div", { class: "vault-movers-col" },
    h("h3", { class: "vault-movers-title", text: title }),
    list.length
      ? h("ol", { class: "vault-movers-list" }, ...list.map((card, i) => moverRow(card, list, i, onOpen)))
      : h("p", { class: "vault-movers-none", text: "None." }));
  root.replaceChildren(
    h("div", { class: "vault-movers-head" },
      h("h2", { class: "vault-movers-heading", text: "Price movers" }),
      h("p", { class: "vault-movers-lede",
        text: since && until ? `Between the card data of ${since} and ${until}.` : "Since the last card data." })),
    h("div", { class: "vault-movers-cols" }, column("Up", up), column("Down", down)));
  return true;
}

// ---- the shelves -----------------------------------------------------------

const SHELVES = [
  { key: "new", title: "New since your last import", see: "new" },
  { key: "gems", title: "Forgotten gems",
    lede: "Popular Commander cards that you own and that no saved deck holds.", see: "gems" },
  { key: "foils", title: "Your foils", see: "foils" },
];

/**
 * Build the shelf rails that have cards. Returns the number of rails.
 * onOpen(cards, index) opens a card; onSeeAll(key) applies the shelf's filter.
 */
export function renderShelves(root, shelves, { onOpen, onSeeAll }) {
  const rails = [];
  for (const shelf of SHELVES) {
    const list = ((shelves && shelves[shelf.key]) || []).filter(Boolean);
    if (!list.length) continue;
    const titleId = `vault-shelf-${shelf.key}`;
    const row = h("div", { class: "vault-shelf-row" },
      list.map((card, i) => vaultTile(card, { onOpen: () => onOpen(list, i) })));
    attachTilt(row);
    rails.push(h("section", { class: "vault-shelf", "data-shelf": shelf.key, "aria-labelledby": titleId },
      h("div", { class: "vault-shelf-head" },
        h("h2", { class: "vault-shelf-title", id: titleId, text: shelf.title }),
        h("button", {
          type: "button", class: "vault-shelf-all", text: "See all",
          onclick: () => onSeeAll(shelf.see),
        })),
      shelf.lede ? h("p", { class: "vault-shelf-lede", text: shelf.lede }) : null,
      row));
  }
  root.replaceChildren(...rails);
  return rails.length;
}
