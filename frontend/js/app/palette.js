// Command palette: Cmd-K (Ctrl-K) opens a box that jumps to a screen, runs an
// action, opens a saved deck, opens an owned card, or searches the collection
// for the typed text.
//
// The palette is a modal dialog with a combobox and a listbox: the arrow keys
// move the active option, Enter runs it, Escape closes the palette, and the
// focus goes back to where it was. Deck names go in with textContent only.
//
// A deck row has a detail line (commander, format, last change), because
// forged decks can share a name.
//
// The card rows come from the collection that the Collection screen shows. A
// card row names the copies in that collection and the saved decks that use
// the card. The card search waits for a pause in the typing, and a newer text
// cancels the older request. When it fails, the other rows stay.

import { fold } from "../decks/filter.js";
import { h } from "../shared/dom.js";
import { formatDay, plural } from "../shared/format.js";
import { getJSON, request } from "../shared/http.js";
import { activeCollection, setViewerSource, viewerSource } from "../shared/session.js";
import { navigate } from "./router.js";

const MAX_SHOWN = 12;
const MAX_CARDS = 5;
const CARD_DELAY = 200; // ms of quiet in the typing before the card search runs
const CARD_MIN = 2; // the fewest characters that start a card search
const CARD_PAGE = 40; // printings to read; they fold into at most MAX_CARDS names

// The fixed commands: [label, group, words to match, run].
const COMMANDS = [
  ["Home", "Go to", "home start", () => navigate("#home")],
  ["Collection", "Go to", "collection cards binder vault", () => navigate("#collection")],
  ["Deck Forge", "Go to", "forge build ai", () => navigate("#forge")],
  ["Decks", "Go to", "decks list", () => navigate("#decks")],
  ["Settings", "Go to", "settings prices images phone model", () => navigate("#settings")],
  ["Import cards", "Action", "import csv upload add cards collection", () => navigate("#import")],
  ["New deck", "Action", "new create deck", () => navigate("#decks", { newDeck: true })],
  ["Import a decklist", "Action", "import paste decklist deck", () => navigate("#decks", { importDeck: true })],
  ["Forgotten gems", "Action", "gems forgotten unused popular", () => navigate("#collection", { q: "is:gem" })],
  ["Cards for trade", "Action", "trade flag binder", () => navigate("#collection", { q: "flag:trade" })],
];

let ui = null;
let decks = [];
let collections = [];
let items = [];
let active = 0;
let opener = null;
// The card rows of the newest answer. A row: {id, name, copies, decks (null until known), job}.
let found = { query: "", rows: [], failed: false };
let cardTimer = 0;
let cardTicket = 0; // bumped by each new text, so an older answer is dropped
let cardAbort = null;
let cardWaiting = false; // the text waits for the collection list

/**
 * Rank the commands for a query: every word must appear; a label that starts
 * with the query comes first. Case and accents do not count ("eowyn" finds "Éowyn").
 */
export function rank(query, entries) {
  const words = fold(query).split(/\s+/).filter(Boolean);
  if (!words.length) return entries.slice();
  const scored = [];
  entries.forEach((entry, order) => {
    const hay = fold(`${entry.label} ${entry.group} ${entry.words || ""}`);
    if (!words.every((w) => hay.includes(w))) return;
    const label = fold(entry.label);
    const score = label.startsWith(words.join(" ")) ? 0 : label.includes(words[0]) ? 1 : 2;
    scored.push([score, order, entry]);
  });
  return scored.sort((a, b) => a[0] - b[0] || a[1] - b[1]).map((s) => s[2]);
}

function entries() {
  const fixed = COMMANDS.map(([label, group, words, run]) => ({ label, group, words, run }));
  const saved = decks.map((d) => {
    const commander = String(d.commander || "");
    const format = String(d.format_name || d.format || "");
    return {
      label: String(d.name || "Untitled deck"), group: "Deck",
      words: `deck ${d.format || ""} ${format} ${commander}`,
      detail: [commander, format, formatDay(d.updated)].filter(Boolean).join(" · "),
      run: () => navigate(`#deck/${encodeURIComponent(d.id)}`),
    };
  });
  return [...fixed, ...saved];
}

// ---- owned cards -----------------------------------------------------------

/** The collection that the Collection screen shows: the chosen one, the active one, else the newest. */
function cardSource() {
  const listed = (id) => Boolean(id) && collections.some((c) => c.job_id === id);
  const chosen = viewerSource();
  if (chosen !== "archive" && listed(chosen)) return chosen;
  const current = activeCollection();
  if (listed(current)) return current;
  return collections.length ? String(collections[0].job_id) : null;
}

/**
 * Fold the printings of a search answer into one row per name, with the
 * copies added up. A name that starts with the text comes first, then a name
 * with a word that starts with it, then the others; each group by name.
 */
function cardRows(cards, query, job) {
  const byName = new Map();
  for (const card of Array.isArray(cards) ? cards : []) {
    const name = String((card && card.name) || "");
    if (!name || !card.scryfall_id) continue;
    const row = byName.get(name) || { id: String(card.scryfall_id), name, copies: 0, decks: null, job };
    row.copies += Math.max(0, Number(card.quantity) || 0);
    byName.set(name, row);
  }
  const text = fold(query).trim();
  const first = text.split(/\s+/)[0] || "";
  const score = (name) => {
    const folded = fold(name);
    if (folded.startsWith(text)) return 0;
    return folded.split(/[^a-z0-9]+/).some((word) => word && word.startsWith(first)) ? 1 : 2;
  };
  const order = (a, b) => {
    const x = fold(a.name);
    const y = fold(b.name);
    return score(a.name) - score(b.name) || (x < y ? -1 : x > y ? 1 : 0);
  };
  return [...byName.values()].sort(order).slice(0, MAX_CARDS);
}

function cardDetail(row) {
  const copies = `${row.copies} owned`;
  if (row.decks === null) return copies;
  return `${copies} · ${row.decks ? `in ${plural(row.decks, "deck")}` : "in no deck"}`;
}

// Open the Collection screen on the card: its name is the search, and its card panel opens.
function openCardRow(row) {
  // On the archive the screen would not show the card, so it opens the collection instead.
  if (viewerSource() === "archive") setViewerSource(row.job);
  navigate("#collection", { card: { id: row.id, name: row.name } });
}

/** The card rows for the text: the newest answer, or the rows of an older text that still match. */
function cardItems(query) {
  if (query.length < CARD_MIN) return [];
  const words = fold(query).split(/\s+/).filter(Boolean);
  const rows = found.query === query ? found.rows
    : found.rows.filter((row) => words.every((word) => fold(row.name).includes(word)));
  return rows.map((row) => ({
    label: row.name, group: "Card", detail: cardDetail(row), run: () => openCardRow(row),
  }));
}

// Drop the waiting search and the answer in flight.
function stopCards() {
  clearTimeout(cardTimer);
  cardTimer = 0;
  cardTicket += 1;
  if (cardAbort) cardAbort.abort();
  cardAbort = null;
}

function scheduleCards() {
  stopCards();
  const query = ui.input.value.trim();
  // Text typed before the collection list loaded waits for the list.
  cardWaiting = query.length >= CARD_MIN && !cardSource();
  if (query.length < CARD_MIN || cardWaiting) return;
  cardTimer = setTimeout(() => {
    cardTimer = 0;
    searchCards(query);
  }, CARD_DELAY);
}

async function searchCards(query) {
  const job = cardSource();
  if (!job) return;
  const ticket = ++cardTicket;
  const controller = typeof AbortController === "function" ? new AbortController() : null;
  cardAbort = controller;
  const options = controller ? { signal: controller.signal } : undefined;
  const params = new URLSearchParams({ q: query, sort: "name", limit: String(CARD_PAGE) });
  let rows;
  try {
    const data = await request(`/collection/${encodeURIComponent(job)}/search?${params}`, options);
    if (ticket !== cardTicket) return;
    rows = cardRows(data && data.cards, query, job);
    found = { query, rows, failed: false };
  } catch (error) {
    if (ticket !== cardTicket) return;
    found = { query, rows: [], failed: true };
    if (isOpen()) render();
    return;
  }
  if (isOpen()) render();
  if (!rows.length) return;
  try {
    const ids = new URLSearchParams({ ids: rows.map((row) => row.id).join(",") });
    const usage = await request(`/decks/usage?${ids}`, options);
    if (ticket !== cardTicket) return;
    rows.forEach((row) => {
      const known = usage && usage[row.id];
      row.decks = known && Array.isArray(known.decks) ? known.decks.length : 0;
    });
    if (isOpen()) render();
  } catch (error) {
    // Without the deck counts, the rows still show the copies.
  }
}

// ---- the box ---------------------------------------------------------------

function build() {
  const input = h("input", {
    id: "palette-input", class: "palette-input", type: "text", role: "combobox", autocomplete: "off",
    spellcheck: "false", "aria-expanded": "true", "aria-controls": "palette-list", "aria-autocomplete": "list",
    placeholder: "Go to a screen, open a deck, or search your cards…", "aria-label": "Command",
  });
  const list = h("ul", { id: "palette-list", class: "palette-list", role: "listbox", "aria-label": "Commands" });
  const hint = h("p", { class: "palette-hint", text: "↑ ↓ to move · Enter to open · Esc to close" });
  const box = h("div", { class: "palette-box", role: "dialog", "aria-modal": "true", "aria-label": "Command palette" },
    input, list, hint);
  const root = h("div", { class: "palette", id: "palette", hidden: true }, box);
  root.addEventListener("mousedown", (event) => { if (event.target === root) close(); });
  input.addEventListener("input", () => {
    active = 0;
    render();
    scheduleCards();
  });
  input.addEventListener("keydown", onKey);
  document.body.append(root);
  return { root, input, list };
}

function render() {
  const query = ui.input.value.trim();
  items = rank(query, entries()).slice(0, MAX_SHOWN);
  if (query) {
    items.unshift({ label: `Search the collection for “${query}”`, group: "Search",
      run: () => navigate("#collection", { q: query }) });
  }
  // The card rows come last, so an answer that comes in does not move the rows above.
  items.push(...cardItems(query));
  active = Math.max(0, Math.min(active, items.length - 1));
  ui.list.replaceChildren(...items.map((item, i) => {
    const option = h("li", { id: `palette-option-${i}`, class: "palette-option", role: "option",
      "aria-selected": String(i === active) },
    h("span", { class: "palette-text" },
      h("span", { class: "palette-label", text: item.label }),
      item.detail ? h("span", { class: "palette-detail", text: item.detail }) : null),
    h("span", { class: "palette-group", text: item.group }));
    option.addEventListener("mousemove", () => { if (active !== i) { active = i; paint(); } });
    option.addEventListener("click", () => runAt(i));
    return option;
  }));
  if (!items.length) {
    ui.list.append(h("li", { class: "palette-empty", role: "presentation", text: "Nothing matches." }));
  }
  if (found.failed && found.query === query) {
    ui.list.append(h("li", { class: "palette-note", role: "presentation", text: "The card search did not answer." }));
  }
  paint();
}

function paint() {
  ui.list.querySelectorAll(".palette-option").forEach((el, i) => el.setAttribute("aria-selected", String(i === active)));
  const current = ui.list.querySelector(`#palette-option-${active}`);
  if (current) {
    ui.input.setAttribute("aria-activedescendant", current.id);
    if (current.scrollIntoView) current.scrollIntoView({ block: "nearest" });
  } else {
    ui.input.removeAttribute("aria-activedescendant");
  }
}

function runAt(index) {
  const item = items[index];
  if (!item) return;
  close(false);
  item.run();
}

function onKey(event) {
  if (event.key === "ArrowDown" || event.key === "ArrowUp") {
    event.preventDefault();
    if (!items.length) return;
    active = (active + (event.key === "ArrowDown" ? 1 : -1) + items.length) % items.length;
    paint();
  } else if (event.key === "Enter") {
    event.preventDefault();
    runAt(active);
  } else if (event.key === "Escape") {
    event.preventDefault();
    close();
  } else if (event.key === "Tab") {
    // The input is the only control: the focus stays in the dialog.
    event.preventDefault();
  }
}

export function isOpen() {
  return Boolean(ui && !ui.root.hidden);
}

async function loadDecks() {
  try {
    const data = await getJSON("/decks");
    decks = (data && data.decks) || [];
    if (isOpen()) render();
  } catch (error) {
    // Without the decks, the palette still has the screens and the actions.
  }
}

async function loadCollections() {
  try {
    const data = await getJSON("/collections");
    collections = Array.isArray(data && data.collections) ? data.collections : [];
  } catch (error) {
    collections = []; // Without the list there is no card search.
  }
  // Text typed while the list loaded gets its card search now.
  if (isOpen() && cardWaiting) scheduleCards();
}

/** Open the palette. The saved decks and the collection list load in the background. */
export async function openPalette() {
  if (!ui) ui = build();
  if (isOpen()) return;
  opener = document.activeElement;
  ui.input.value = "";
  active = 0;
  found = { query: "", rows: [], failed: false };
  ui.root.hidden = false;
  document.body.classList.add("palette-open");
  render();
  ui.input.focus();
  await Promise.all([loadDecks(), loadCollections()]);
}

/** Close the palette. The focus goes back to the control that had it. */
export function close(restore = true) {
  if (!isOpen()) return;
  stopCards();
  ui.root.hidden = true;
  document.body.classList.remove("palette-open");
  if (restore && opener && opener.focus && opener.isConnected) opener.focus();
  opener = null;
}

/** Listen for Cmd-K and Ctrl-K, and for the top bar's search button. */
export function startPalette() {
  document.addEventListener("keydown", (event) => {
    if ((event.metaKey || event.ctrlKey) && !event.altKey && event.key.toLowerCase() === "k") {
      event.preventDefault();
      if (isOpen()) close();
      else openPalette();
    }
  });
  const button = document.getElementById("palette-button");
  if (button) button.addEventListener("click", () => openPalette());
}
