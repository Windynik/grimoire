// Live stats panel of the deck editor: card count, curve, mana, issues, price,
// Game Changers and the forge metrics. All values come from the analysis.
//
// The count bar and the curve bars are built once per root, so a new value
// moves them with a transform transition. Server text goes in with textContent only.

import { h } from "../shared/dom.js";
import { issueSummary } from "./model.js";

const METRICS = [
  ["combined", "Score"],
  ["synergy_density", "Synergy"],
  ["role_coverage", "Roles"],
  ["curve_fit", "Curve"],
  ["mana_consistency", "Mana"],
  ["avg_quality", "Quality"],
];
const CURVE_KEYS = ["0", "1", "2", "3", "4", "5", "6+"];
const COLOR_NAMES = { W: "White", U: "Blue", B: "Black", R: "Red", G: "Green" };
const ISSUE_LABELS = {
  not_a_card: "unknown", not_owned: "not owned", short: "short on copies", banned: "banned",
  not_legal: "not legal", off_color: "off color", too_many: "too many",
};

const contexts = new WeakMap();

const ratio = (value, total) => (total > 0 ? Math.max(0, Math.min(1, value / total)) : 0);

function bar(className) {
  const fill = h("span", { class: "stat-fill" });
  return { track: h("span", { class: `stat-bar ${className}`, "aria-hidden": "true" }, fill), fill };
}

function section(title, ...children) {
  return h("section", { class: "stat-block" }, h("h3", { class: "stat-title", text: title }), children);
}

function build(root) {
  const count = h("p", { class: "stat-count" });
  const countBar = bar("stat-bar-count");
  const curveCols = new Map();
  const curve = h("div", { class: "stat-curve", role: "img" });
  CURVE_KEYS.forEach((key) => {
    const fill = h("span", { class: "stat-curve-fill" });
    const value = h("span", { class: "stat-curve-value" });
    const col = h("span", { class: "stat-curve-col", hidden: true },
      value, h("span", { class: "stat-curve-track" }, fill),
      h("span", { class: "stat-curve-label", text: key }));
    curveCols.set(key, { col, fill, value });
    curve.append(col);
  });
  const mana = h("div", { class: "stat-mana" });
  const issues = h("ul", { class: "stat-issues" });
  const price = h("dd", { class: "stat-value" });
  const changers = h("dd", { class: "stat-value" });
  const metrics = h("div", { class: "stat-metrics" });
  root.replaceChildren(
    section("Cards", count, countBar.track),
    section("Curve", curve),
    section("Mana", mana),
    section("Issues", issues),
    h("dl", { class: "stat-facts" },
      h("div", { class: "stat-fact" }, h("dt", { text: "Price" }), price),
      h("div", { class: "stat-fact" }, h("dt", { text: "Game Changers" }), changers)),
    section("Metrics", metrics));
  return { count, countBar, curve, curveCols, mana, issues, price, changers, metrics };
}

function manaRow(row) {
  const name = COLOR_NAMES[row.color] || row.color;
  const short = row.sources < row.needed;
  const meter = bar(short ? "stat-bar-short" : "stat-bar-ok");
  meter.fill.style.transform = `scaleX(${ratio(row.sources, row.needed)})`;
  return h("div", { class: "stat-mana-row" },
    h("span", { class: `stat-mana-color mana-${String(row.color).toLowerCase()}`, text: name }),
    h("span", { class: "stat-mana-text",
      text: `${row.pips} pips · ${row.sources} of ${row.needed} sources` }),
    meter.track);
}

function metricText(key, value) {
  return key === "synergy_density" ? value.toFixed(2) : `${Math.round(value * 100)}%`;
}

/**
 * Render the stats panel into root.
 *
 * @param {HTMLElement} root
 * @param {Object} analysis The analysis of the deck (may be empty before the first load).
 */
export function renderStats(root, analysis) {
  let ui = contexts.get(root);
  if (!ui) {
    ui = build(root);
    contexts.set(root, ui);
  }
  const data = analysis || {};
  const total = (data.count || {}).main || 0;
  const target = (data.count || {}).target || 0;
  ui.count.textContent = target ? `${total} / ${target} cards` : `${total} cards`;
  ui.countBar.fill.style.transform = `scaleX(${ratio(total, target)})`;

  const curve = data.curve || {};
  const max = Math.max(1, ...CURVE_KEYS.map((key) => Number(curve[key]) || 0));
  ui.curveCols.forEach((item, key) => {
    const value = Number(curve[key]) || 0;
    item.col.hidden = !(key in curve) && !value;
    item.fill.style.transform = `scaleY(${value / max})`;
    item.value.textContent = value;
  });
  ui.curve.setAttribute("aria-label", `Mana curve: ${CURVE_KEYS
    .filter((key) => key in curve).map((key) => `${curve[key]} at ${key}`).join(", ")}`);

  ui.mana.replaceChildren(...(data.mana || []).map(manaRow));
  if (!(data.mana || []).length) ui.mana.textContent = "No colored cards yet.";

  const rows = (data.issues || []).map((issue) => h("li", { class: "stat-issue", text: issue.message }));
  Object.entries(issueSummary(data.cards)).forEach(([code, number]) => {
    rows.push(h("li", { class: "stat-issue stat-issue-card",
      text: `${number} ${number === 1 ? "card" : "cards"}: ${ISSUE_LABELS[code] || code}` }));
  });
  if (!rows.length) rows.push(h("li", { class: "stat-issue stat-issue-none", text: "No issues." }));
  ui.issues.replaceChildren(...rows);

  const price = Number(data.price);
  ui.price.textContent = Number.isFinite(price) ? `$${price.toFixed(2)}` : "$0.00";
  ui.changers.textContent = Number(data.game_changers) || 0;

  const metrics = data.metrics || {};
  const items = [];
  METRICS.forEach(([key, label]) => {
    const value = Number(metrics[key]);
    if (!Number.isFinite(value)) return;
    items.push(h("div", { class: "stat-metric" },
      h("span", { class: "stat-metric-label", text: label }),
      h("span", { class: "stat-metric-value", text: metricText(key, value) })));
  });
  if (!items.length) items.push(h("p", { class: "stat-empty", text: "Add cards to see scores." }));
  ui.metrics.replaceChildren(...items);
}
