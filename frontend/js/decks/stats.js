// Live stats panel of the deck editor: card count, curve, mana, issues (with a
// plain reason for each card), Commander bracket facts, price, Game Changers and
// the forge metrics. All values come from the analysis.
//
// The count bar and the curve bars are built once per root, so a new value
// moves them with a transform transition. Server text goes in with textContent only.

import { h } from "../shared/dom.js";
import { issueSummary } from "./model.js";
import { renderCombos } from "./combos.js";

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
  taken: "copies in other decks",
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
  const bracket = h("div", { class: "stat-bracket" });
  const bracketBlock = section("Bracket", bracket);
  bracketBlock.hidden = true;
  const combos = h("div", { class: "stat-combos" });
  const price = h("dd", { class: "stat-value" });
  const changers = h("dd", { class: "stat-value" });
  const metrics = h("div", { class: "stat-metrics" });
  root.replaceChildren(
    section("Cards", count, countBar.track),
    section("Curve", curve),
    section("Mana", mana),
    section("Issues", issues),
    bracketBlock,
    section("Combos", combos),
    h("dl", { class: "stat-facts" },
      h("div", { class: "stat-fact" }, h("dt", { text: "Price" }), price),
      h("div", { class: "stat-fact" }, h("dt", { text: "Game Changers" }), changers)),
    section("Metrics", metrics));
  return { count, countBar, curve, curveCols, mana, issues, bracket, bracketBlock, combos, price,
    changers, metrics };
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

// One issue code: "2 cards: banned", and under it each card with its reason.
function issueGroup(code, number, cards, names) {
  const items = Object.entries(cards || {})
    .filter(([, info]) => ((info && info.issues) || []).includes(code))
    .map(([key, info]) => h("li", { class: "stat-issue-card-item" },
      h("b", { text: names[key] || key }),
      ` ${((info.reasons || {})[code]) || ""}`));
  return h("li", { class: "stat-issue stat-issue-card" },
    h("details", null,
      h("summary", { text: `${number} ${number === 1 ? "card" : "cards"}: ${ISSUE_LABELS[code] || code}` }),
      h("ul", { class: "stat-issue-cards" }, ...items)));
}

// The bracket facts of a Commander deck: the lowest bracket the facts allow,
// what raised it, the cards behind each fact, and what the check cannot see.
function bracketView(facts) {
  const floor = Number(facts.floor) || 2;
  const head = floor <= 2 ? "Bracket 1 or 2"
    : `Bracket ${floor} or higher (${facts.floor_name || ""})`;
  const parts = [h("p", { class: "stat-bracket-floor", text: head })];
  (facts.reasons || []).forEach((text) => parts.push(h("p", { class: "stat-bracket-reason", text })));
  const rows = [
    ["Game Changers", facts.game_changers],
    ["Mass land denial", facts.mass_land_denial],
    ["Extra turns", facts.extra_turns],
    ["Tutors", facts.tutors],
  ];
  parts.push(h("dl", { class: "stat-bracket-facts" }, ...rows.map(([label, names]) => {
    const list = Array.isArray(names) ? names : [];
    return h("div", { class: "stat-bracket-fact" },
      h("dt", { text: label }),
      h("dd", { text: list.length ? `${list.length}: ${list.join(", ")}` : "none" }));
  })));
  (facts.notes || []).forEach((text) => parts.push(h("p", { class: "stat-bracket-note", text })));
  return parts;
}

function metricText(key, value) {
  return key === "synergy_density" ? value.toFixed(2) : `${Math.round(value * 100)}%`;
}

/**
 * Render the stats panel into root.
 *
 * @param {HTMLElement} root
 * @param {Object} analysis The analysis of the deck (may be empty before the first load).
 * @param {Object} [names] Card name per entry key, for the issue list.
 * @param {{combos: Object|null, busy: boolean, onFindCombos: function()}} [extra] The combo check.
 */
export function renderStats(root, analysis, names = {}, extra = {}) {
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
    rows.push(issueGroup(code, number, data.cards, names));
  });
  if (!rows.length) rows.push(h("li", { class: "stat-issue stat-issue-none", text: "No issues." }));
  ui.issues.replaceChildren(...rows);

  ui.bracketBlock.hidden = !data.bracket;
  ui.bracket.replaceChildren(...(data.bracket ? bracketView(data.bracket) : []));
  renderCombos(ui.combos, extra.combos || null, {
    stale: Boolean(data.combos_stale), busy: Boolean(extra.busy), onFind: extra.onFindCombos,
  });

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
