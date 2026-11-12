// Pull list of the editor: where to find each card of the deck on the shelf,
// grouped by collection and binder. The owner ticks the cards off as they go.
// Card names go in with textContent only.

import { h } from "../shared/dom.js";

// Ticked cards per deck, for this page visit. A new list keeps the ticks of
// the cards that are still in it.
const ticked = new Map();

function title(group) {
  return group.binder ? `${group.collection} · ${group.binder}` : group.collection || "Collection";
}

function cardText(card) {
  const where = [card.set, card.number].filter(Boolean).join(" ");
  const finish = card.foil && card.foil !== "normal" ? ` ${card.foil}` : "";
  return `${card.count} ${card.name}${where ? ` (${where})` : ""}${finish}`;
}

/** The pull list as plain text, one block per binder. */
export function pullText(data) {
  const blocks = (data.groups || []).map((group) =>
    [title(group), ...group.cards.map(cardText)].join("\n"));
  if ((data.basics || []).length) {
    blocks.push(["Basic lands", ...data.basics.map((b) => `${b.count} ${b.name}`)].join("\n"));
  }
  if ((data.missing || []).length) {
    blocks.push(["Not owned", ...data.missing.map((m) => `${m.count} ${m.name}`)].join("\n"));
  }
  return blocks.join("\n\n");
}

function tickKey(group, card) {
  return `${group.job_id}|${group.binder}|${card.scryfall_id}|${card.foil}`;
}

function groupNode(group, ticks, onTick) {
  const items = group.cards.map((card) => {
    const key = tickKey(group, card);
    const box = h("input", { type: "checkbox", class: "pull-tick", "aria-label": `Pulled ${card.name}` });
    box.checked = ticks.has(key);
    box.addEventListener("change", () => onTick(key, box.checked));
    const other = card.printing ? null
      : h("span", { class: "pull-other", text: "other printing", title: "The deck names another printing of this card." });
    return h("li", { class: "pull-card" },
      h("label", null, box, h("span", { class: "pull-text", text: cardText(card) }), other));
  });
  return h("section", { class: "pull-group" },
    h("h3", { class: "pull-title" }, h("span", { text: title(group) }),
      h("span", { class: "pull-count", text: `${group.count} ${group.count === 1 ? "card" : "cards"}` })),
    h("ul", { class: "pull-cards" }, ...items));
}

function plainGroup(name, cards, hint) {
  return h("section", { class: "pull-group pull-plain" },
    h("h3", { class: "pull-title" }, h("span", { text: name })),
    hint ? h("p", { class: "pull-hint", text: hint }) : null,
    h("ul", { class: "pull-cards" },
      ...cards.map((c) => h("li", { class: "pull-card", text: `${c.count} ${c.name}` }))));
}

/**
 * Show a pull list in a root element.
 * @param {HTMLElement} root The panel.
 * @param {string} deckId The deck, to keep its ticks.
 * @param {{groups: Array, basics: Array, missing: Array}} data The pull list from the server.
 * @param {{copy?: function(string): Promise<void>}} [options]
 */
export function renderPull(root, deckId, data, options = {}) {
  const ticks = ticked.get(deckId) || new Set();
  ticked.set(deckId, ticks);
  const groups = data.groups || [];
  const total = groups.reduce((sum, g) => sum + g.count, 0);
  const progress = h("p", { class: "pull-progress", role: "status" });
  const showProgress = () => {
    const done = groups.reduce((sum, g) => sum + g.cards
      .filter((c) => ticks.has(tickKey(g, c))).reduce((n, c) => n + c.count, 0), 0);
    progress.textContent = `${done} of ${total} cards pulled.`;
  };
  const onTick = (key, on) => {
    if (on) ticks.add(key);
    else ticks.delete(key);
    showProgress();
  };
  const copy = h("button", { type: "button", class: "btn btn-secondary btn-compact pull-copy", text: "Copy as text" });
  copy.addEventListener("click", () => {
    if (typeof options.copy === "function") options.copy(pullText(data));
  });
  const nodes = [
    h("div", { class: "pull-head" },
      h("p", { class: "pull-lede", text: total
        ? `Take ${total} ${total === 1 ? "card" : "cards"} from ${groups.length} ${groups.length === 1 ? "place" : "places"}.`
        : "No card of this deck is in your collections." }),
      copy),
    total ? progress : null,
    ...groups.map((g) => groupNode(g, ticks, onTick)),
  ];
  if ((data.basics || []).length) {
    nodes.push(plainGroup("Basic lands", data.basics, "From your basic land box."));
  }
  if ((data.missing || []).length) {
    nodes.push(plainGroup("Not owned", data.missing, "No collection holds these copies."));
  }
  root.replaceChildren(...nodes.filter(Boolean));
  if (total) showProgress();
}

/** Show the loading or the error state of the pull list. */
export function renderPullState(root, text, isError = false) {
  root.replaceChildren(h("p", { class: isError ? "pull-error" : "pull-lede", role: isError ? "alert" : "status", text }));
}
