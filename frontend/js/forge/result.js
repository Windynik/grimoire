// Forge result: the finished deck with its plan, metrics, and decklist.
//
// Plan 2 replaces this view with the deck editor.

import { renderExplanation } from "./feed.js";

const METRICS = [
  ["combined", "Score"],
  ["synergy_density", "Synergy"],
  ["role_coverage", "Roles"],
  ["curve_fit", "Curve"],
  ["mana_consistency", "Mana"],
  ["avg_quality", "Quality"],
];
const ROLE_ORDER = ["core", "synergy"];
const ROLE_LAST = ["land", "basic"];
const ROLE_TITLES = { core: "Core", synergy: "Synergy", land: "Lands", basic: "Basic lands" };

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

// Characters a mana cost can hold: "{2}{W/U}{½} // {X}". parseManaSymbols puts
// symbol text into a title attribute, so quotes and markup must not reach it.
const MANA_UNSAFE = /[^{}A-Za-z0-9/ ½∞]/g;

/** Return mana symbol markup for a cost. Unsafe characters are removed before parsing. */
function manaNode(cost) {
  const span = el("span", "forge-mana");
  const parse = window.grimoireMana && window.grimoireMana.parseManaSymbols;
  if (!cost) return span;
  const clean = String(cost).replace(MANA_UNSAFE, "");
  if (typeof parse === "function") span.innerHTML = parse(clean);
  else span.textContent = clean;
  return span;
}

/**
 * Return the decklist text, in the same format as backend decklist_text.
 * @param {Object} deck Deck record.
 * @returns {string}
 */
export function decklistText(deck) {
  const sections = [];
  if (deck.commander) sections.push(`Commander\n1 ${deck.commander.name}`);
  const data = deck.sections || {};
  const main = data.main || [];
  sections.push(["Deck"].concat(main.map((c) => `${c.count} ${c.name}`)).join("\n"));
  const side = data.sideboard || [];
  if (side.length) sections.push(["Sideboard"].concat(side.map((c) => `${c.count} ${c.name}`)).join("\n"));
  return sections.join("\n\n");
}

function roleTitle(role) {
  if (ROLE_TITLES[role]) return ROLE_TITLES[role];
  const text = String(role || "Other");
  return text.charAt(0).toUpperCase() + text.slice(1);
}

function groupByRole(main) {
  const groups = new Map();
  main.forEach((card) => {
    const role = card.role || "other";
    if (!groups.has(role)) groups.set(role, []);
    groups.get(role).push(card);
  });
  const count = (role) => groups.get(role).reduce((n, c) => n + (Number(c.count) || 0), 0);
  const middle = [...groups.keys()]
    .filter((r) => !ROLE_ORDER.includes(r) && !ROLE_LAST.includes(r))
    .sort((a, b) => count(b) - count(a) || a.localeCompare(b));
  return ROLE_ORDER.concat(middle, ROLE_LAST)
    .filter((role) => groups.has(role))
    .map((role) => ({ role, cards: groups.get(role), count: count(role) }));
}

async function copyText(text) {
  if (navigator.clipboard && window.isSecureContext) {
    await navigator.clipboard.writeText(text);
    return;
  }
  const area = document.createElement("textarea");
  area.value = text;
  area.setAttribute("readonly", "");
  area.style.position = "fixed";
  area.style.opacity = "0";
  document.body.appendChild(area);
  area.select();
  const ok = document.execCommand("copy");
  area.remove();
  if (!ok) throw new Error("Copy failed");
}

function list(title, items, className) {
  const box = el("div", `forge-result-list ${className}`);
  box.appendChild(el("h4", "", title));
  const ul = el("ul");
  items.forEach((item) => ul.appendChild(el("li", "", String(item))));
  box.appendChild(ul);
  return box;
}

function cardRow(card) {
  const row = el("li", "forge-result-card");
  row.appendChild(el("span", "forge-result-count", `${card.count}`));
  const main = el("div", "forge-result-main");
  const line = el("div", "forge-result-line");
  line.append(el("span", "forge-result-name", card.name || ""), manaNode(card.mana_cost));
  main.appendChild(line);
  if (card.reason) main.appendChild(el("small", "forge-result-reason", card.reason));
  row.appendChild(main);
  if (card.image_url) row.title = card.type_line || "";
  return row;
}

/**
 * Render a finished deck.
 *
 * @param {HTMLElement} root Container. Its content is replaced.
 * @param {Object} deck Deck record from GET /api/decks/{id}.
 * @param {Object} [actions]
 * @param {function} [actions.onAgain] Called by "Forge again".
 * @param {function(string, string)} [actions.toast] Shows a message.
 */
export function renderResult(root, deck, actions = {}) {
  root.textContent = "";
  const main = (deck.sections && deck.sections.main) || [];
  const total = main.reduce((n, c) => n + (Number(c.count) || 0), 0) + (deck.commander ? 1 : 0);
  const backbone = deck.backbone || {};

  const head = el("header", "forge-result-head");
  head.appendChild(el("p", "forge-result-kicker", [deck.format, `${total} cards`, backbone.playstyle]
    .filter(Boolean).join(" · ")));
  head.appendChild(el("h2", "forge-result-name-title", deck.name || "Forged deck"));
  if (deck.commander) head.appendChild(el("p", "forge-result-commander", `Commander: ${deck.commander.name}`));
  if (backbone.thesis) head.appendChild(el("p", "forge-result-thesis", backbone.thesis));

  const buttons = el("div", "forge-actions");
  const copy = el("button", "btn btn-primary", "Copy decklist");
  copy.type = "button";
  copy.addEventListener("click", async () => {
    try {
      await copyText(decklistText(deck));
      if (actions.toast) actions.toast("Decklist copied.", "success");
    } catch (e) {
      if (actions.toast) actions.toast("Could not copy the decklist.", "error");
    }
  });
  const again = el("button", "btn btn-secondary", "Forge again");
  again.type = "button";
  again.addEventListener("click", () => actions.onAgain && actions.onAgain());
  buttons.append(copy, again);
  head.appendChild(buttons);
  root.appendChild(head);

  const metrics = deck.metrics || {};
  const stats = el("dl", "forge-result-stats");
  METRICS.forEach(([key, label]) => {
    const value = Number(metrics[key]);
    if (!Number.isFinite(value)) return;
    const item = el("div", "forge-stat");
    const shown = key === "synergy_density" ? value.toFixed(2) : `${Math.round(value * 100)}%`;
    item.append(el("dt", "", label), el("dd", "", shown));
    stats.appendChild(item);
  });
  if (Number(deck.game_changers) > 0) {
    const item = el("div", "forge-stat");
    item.append(el("dt", "", "Game changers"), el("dd", "", String(deck.game_changers)));
    stats.appendChild(item);
  }
  root.appendChild(stats);

  const warnings = deck.warnings || [];
  const notes = deck.notes || [];
  if (warnings.length || notes.length) {
    const box = el("div", "forge-result-notes");
    if (warnings.length) box.appendChild(list("Warnings", warnings, "warning"));
    if (notes.length) box.appendChild(list("Notes", notes, "note"));
    root.appendChild(box);
  }

  const sections = el("div", "forge-result-sections");
  groupByRole(main).forEach(({ role, cards, count }) => {
    const section = el("section", "forge-result-group");
    section.appendChild(el("h4", "", `${roleTitle(role)} (${count})`));
    const ul = el("ul");
    cards.forEach((card) => ul.appendChild(cardRow(card)));
    section.appendChild(ul);
    sections.appendChild(section);
  });
  root.appendChild(sections);

  if (deck.explanation) {
    const explain = el("section", "forge-result-explain");
    explain.appendChild(el("h3", "", "How the deck works"));
    const body = el("div", "forge-explain-body");
    renderExplanation(body, deck.explanation);
    explain.appendChild(body);
    root.appendChild(explain);
  }
  return root;
}
