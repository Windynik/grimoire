// Add-cards search of the deck editor: owned cards or the whole archive,
// with type, color and format filters, and one-click add to a section.
//
// The panel is built once per root. Later renderSearch calls only refresh the
// state link and the collection. Card text goes in with textContent only.

import { h, manaNode } from "../shared/dom.js";
import { cardImage, cardImg } from "../shared/images.js";
import { shownSections, toEntryCard } from "./model.js";
import * as api from "./api.js";

const PAGE = 30;
const DEBOUNCE_MS = 250;
const ADD_SECTIONS = [["main", "Main"], ["sideboard", "Side"], ["maybeboard", "Maybe"]];
const SECTION_NAMES = { main: "Main", sideboard: "Sideboard", maybeboard: "Maybeboard" };
const TYPES = ["Creature", "Instant", "Sorcery", "Artifact", "Enchantment", "Planeswalker", "Land"];
const COLORS = [["W", "White"], ["U", "Blue"], ["B", "Black"], ["R", "Red"], ["G", "Green"],
  ["C", "Colorless"]];

const contexts = new WeakMap();

function select(label, name, options) {
  const el = h("select", { "data-filter": name, "aria-label": label },
    h("option", { value: "", text: label }),
    options.map(([value, text]) => h("option", { value, text })));
  return el;
}

function build(root, ctx) {
  const field = h("input", {
    type: "search", class: "search-field", placeholder: "Search cards by name",
    "aria-label": "Search cards by name", autocomplete: "off", spellcheck: "false",
  });
  const type = select("Any type", "card_type", TYPES.map((t) => [t, t]));
  const color = select("Any color", "color", COLORS);
  const legal = h("input", { type: "checkbox", checked: true });
  const archive = h("input", { type: "checkbox" });
  const note = h("p", { class: "search-note", hidden: true });
  const list = h("ul", { class: "search-results" });
  const more = h("button", {
    type: "button", class: "btn btn-secondary btn-compact search-more", hidden: true,
  }, "More");
  const status = h("p", { class: "search-status", role: "status", "aria-live": "polite" });
  const lockNote = h("span", { class: "search-lock", hidden: true, text: "(no collection)" });

  root.replaceChildren(
    h("div", { class: "search-filters" }, field,
      h("div", { class: "search-selects" }, type, color),
      h("label", { class: "search-check" }, legal, h("span", { text: "Legal in this format" })),
      h("label", { class: "search-check" }, archive,
        h("span", { text: "Show cards I do not own" }), lockNote)),
    note, status, list, more);

  Object.assign(ctx, { field, type, color, legal, archive, note, list, more, status, lockNote });

  let timer = null;
  const refresh = () => {
    clearTimeout(timer);
    ctx.run(false);
  };
  field.addEventListener("input", () => {
    clearTimeout(timer);
    timer = setTimeout(() => ctx.run(false), DEBOUNCE_MS);
  });
  [type, color, legal, archive].forEach((el) => el.addEventListener("change", refresh));
  more.addEventListener("click", () => ctx.run(true));
  list.addEventListener("click", (event) => {
    const button = event.target.closest("button[data-section]");
    if (!button) return;
    const card = ctx.cards[Number(button.closest("li").dataset.index)];
    if (!card) return;
    ctx.state.apply({ type: "add", section: button.dataset.section, card: toEntryCard(card) });
    ctx.status.textContent = `Added ${card.name} to ${SECTION_NAMES[button.dataset.section]}.`;
  });
}

// One add button per section the deck shows (a commander deck has no Sideboard).
function addButtons(card, sections) {
  return ADD_SECTIONS.filter(([section]) => sections.includes(section)).map(([section, label]) => h(
    "button", {
      type: "button", class: "search-add", "data-section": section,
      "aria-label": `Add ${card.name} to ${SECTION_NAMES[section]}`, text: label,
    }));
}

function resultNode(card, index, owned, sections) {
  const art = cardImage(card)
    ? cardImg(card, { className: "search-art", size: "small" })
    : h("span", { class: "search-art" });
  const name = h("span", { class: "search-name" });
  name.textContent = card.name;
  const mana = manaNode(card.mana_cost, "search-mana");
  mana.setAttribute("aria-hidden", "true");
  // One row stands for every printing of the card: the copies add up.
  const printings = Number(card.printings) || 1;
  const have = owned
    ? h("span", { class: "search-owned",
      text: `Own ${Number(card.quantity) || 0}${printings > 1 ? ` · ${printings} printings` : ""}` })
    : h("span", { class: "deck-badge deck-badge-not_owned", text: "not owned" });
  const more = !owned && printings > 1
    ? h("span", { class: "search-printings", text: `${printings} printings` }) : null;
  return h("li", { class: "search-result", "data-index": index },
    art,
    h("span", { class: "search-info" }, name, h("span", { class: "search-line" }, mana, have, more)),
    h("span", { class: "search-adds" }, addButtons(card, sections)));
}

/**
 * Render the search panel into root. The first call builds it; later calls keep
 * the typed text and results and only refresh the collection.
 *
 * @param {HTMLElement} root
 * @param {{analysis: Object, apply: function(Object)}} state The editor state.
 */
export function renderSearch(root, state) {
  let ctx = contexts.get(root);
  if (!ctx) {
    ctx = { state, cards: [], total: 0, serial: 0, jobId: undefined };
    contexts.set(root, ctx);
    ctx.run = (append) => run(ctx, append);
    build(root, ctx);
  }
  ctx.state = state;
  // The add targets follow the sections the deck shows.
  const sections = shownSections(state);
  if (ctx.sections && ctx.sections.join() !== sections.join()) {
    ctx.list.querySelectorAll(".search-result").forEach((row) => {
      const card = ctx.cards[Number(row.dataset.index)];
      if (card) row.querySelector(".search-adds").replaceChildren(...addButtons(card, sections));
    });
  }
  ctx.sections = sections;
  // Every collection of the deck: the search reads them as one pool.
  const collection = (state.analysis && state.analysis.collection) || {};
  ctx.jobIds = (collection.job_ids && collection.job_ids.length ? collection.job_ids
    : [collection.job_id]).filter(Boolean);
  const jobId = ctx.jobIds.join(",") || null;
  const locked = !jobId;
  ctx.archive.disabled = locked;
  ctx.lockNote.hidden = !locked;
  if (locked) ctx.archive.checked = true;
  if (ctx.jobId === undefined) {
    ctx.jobId = jobId;
    ctx.run(false);
  } else if (ctx.jobId !== jobId) {
    ctx.jobId = jobId;
    if (!ctx.archive.checked || locked) ctx.run(false);
  }
}

async function run(ctx, append) {
  const serial = ++ctx.serial;
  const archive = ctx.archive.checked || !ctx.jobId;
  const fmt = ctx.state.analysis && ctx.state.analysis.format;
  const params = {
    q: ctx.field.value.trim(),
    card_type: ctx.type.value,
    color: ctx.color.value,
    format: ctx.legal.checked && fmt ? fmt.key : "",
    // One row per card name; the add takes the printing with the most copies.
    group: "name",
    limit: PAGE,
    offset: append ? ctx.cards.length : 0,
  };
  ctx.status.textContent = "Searching…";
  ctx.more.disabled = true;
  try {
    const data = await (archive ? api.searchArchive(params) : api.searchOwned(ctx.jobIds, params));
    if (serial !== ctx.serial) return;
    const cards = data.cards || [];
    ctx.cards = append ? ctx.cards.concat(cards) : cards;
    ctx.total = data.total || 0;
    if (!append) ctx.list.replaceChildren();
    const start = ctx.cards.length - cards.length;
    cards.forEach((card, i) => ctx.list.append(resultNode(card, start + i, !archive, ctx.sections)));
    ctx.status.textContent = ctx.cards.length
      ? `Showing ${ctx.cards.length} of ${ctx.total}.` : "No cards match.";
    ctx.note.hidden = true;
  } catch (error) {
    if (serial !== ctx.serial) return;
    ctx.status.textContent = "";
    ctx.note.textContent = `Could not search: ${error.message}`;
    ctx.note.hidden = false;
  } finally {
    if (serial === ctx.serial) {
      ctx.more.disabled = false;
      ctx.more.hidden = ctx.cards.length >= ctx.total;
    }
  }
}
