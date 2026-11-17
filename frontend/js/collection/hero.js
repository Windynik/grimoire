// The head of the collection screen: the collection switcher, the summary
// line, the ledger, the color orbs, and the shelves under it.
//
// Server text goes in with textContent only. Mana symbols are sprite classes.

import { h } from "../shared/dom.js";
import { vaultTile } from "./tile.js";
import { formatCount, formatMoney, shortDate } from "./numbers.js";

export const COLOR_NAMES = {
  W: "White", U: "Blue", B: "Black", R: "Red", G: "Green", C: "Colorless", M: "Multicolor",
};
const ORB_ORDER = ["W", "U", "B", "R", "G", "C", "M"];

export { formatCount, formatMoney, shortDate };

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

/**
 * Show the final value of each counter.
 *
 * @param {Array<{el: HTMLElement, to: number, format: function(number): string}>} items
 */
export function showCounters(items) {
  items.forEach((item) => { item.el.textContent = item.format(item.to); });
}

// ---- the hero --------------------------------------------------------------

function ledgerItem(key, label, note, gold) {
  const value = h("span", { class: "vault-ledger-value" });
  const el = h("div", { class: `vault-ledger-item${gold ? " is-gold" : ""}`, "data-key": key },
    value,
    h("span", { class: "vault-ledger-label", text: label }),
    note ? h("span", { class: "vault-ledger-note", text: note }) : null);
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
  const date = shortDate(data.created);
  parts.lede.textContent = `${formatCount(data.cards)} ${Number(data.cards) === 1 ? "card" : "cards"}, `
    + `${formatCount(data.unique)} unique.${date ? ` Imported ${date}.` : ""}`;

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
    [ledgerItem("foils", "Foils"), Number(data.foils) || 0, formatCount],
    [ledgerItem("sets", "Sets"), Number(data.sets) || 0, formatCount],
  ];
  // The value over time, when there are two card-data downloads or more.
  const spark = sparkline(data.history);
  if (spark) {
    const trend = trendText(data.history);
    items[0][0].el.append(spark, h("span", { class: "vault-ledger-trend", text: trend }));
  }
  parts.ledger.replaceChildren(...items.map(([item]) => item.el));
  showCounters(items.map(([item, to, format]) => ({ el: item.value, to, format })));

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
