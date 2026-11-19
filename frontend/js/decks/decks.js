// Decks view: the list of saved decks, and the entry point of the deck editor.
//
// Deck names, card names and server text go in with textContent only.

import { h } from "../shared/dom.js";
import { plural } from "../shared/format.js";
import { confirmDialog, openDialog } from "../shared/modal.js";
import { showToast } from "../shared/toast.js";
import { navigate } from "../app/router.js";
import * as api from "./api.js";
import { SORTS, filterDecks, formatsOf, sortDecks } from "./filter.js";
import { deckTable } from "./table.js";
import { deckTile } from "./tile.js";
import { closeEditor as unmountEditor, openEditor as mountEditor } from "./editor.js";

const $ = (id) => document.getElementById(id);

// The view (Tiles or List) stays in localStorage. The search, the sort and the
// format filter stay in sessionStorage, so they last for this browser session.
const VIEW_KEY = "decksView";
const FILTERS_KEY = "decksFilters";
const VIEWS = ["tiles", "list"];
const NO_FILTERS = { q: "", sort: SORTS[0], format: "" };

const state = {
  formats: [], collections: [], decks: [], loadRequest: 0,
  editing: null, // the id of the deck in the editor, or null
  ticket: 0, // bumped by every route change, so a stale editor open stops
  view: VIEWS[0],
  filters: { ...NO_FILTERS },
};
let closing = Promise.resolve(); // the close of the last editor, with its save

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatName(key) {
  const found = state.formats.find((f) => f.key === key);
  if (found) return found.name;
  const deck = state.decks.find((d) => d.format === key && d.format_name);
  return deck ? deck.format_name : key || "";
}

// ---------------------------------------------------------------------------
// Remembered choices. A blocked storage throws on each access; then the value
// stays in memory for this page.
// ---------------------------------------------------------------------------

const memory = new Map();

function readStored(area, key) {
  let stored = null;
  try {
    stored = globalThis[area].getItem(key);
  } catch (error) {
    stored = null;
  }
  return memory.has(`${area}:${key}`) ? memory.get(`${area}:${key}`) : stored;
}

function writeStored(area, key, value) {
  try {
    globalThis[area].setItem(key, value);
    memory.delete(`${area}:${key}`);
  } catch (error) {
    memory.set(`${area}:${key}`, value);
  }
}

function loadChoices() {
  const view = readStored("localStorage", VIEW_KEY);
  state.view = VIEWS.includes(view) ? view : VIEWS[0];
  let saved = {};
  try {
    saved = JSON.parse(readStored("sessionStorage", FILTERS_KEY) || "{}") || {};
  } catch (error) {
    saved = {};
  }
  state.filters = {
    q: typeof saved.q === "string" ? saved.q.slice(0, 200) : "",
    sort: SORTS.includes(saved.sort) ? saved.sort : NO_FILTERS.sort,
    format: typeof saved.format === "string" ? saved.format : "",
  };
}

function saveFilters() {
  const { q, sort, format } = state.filters;
  writeStored("sessionStorage", FILTERS_KEY, JSON.stringify({ q, sort, format }));
}

async function loadLookups() {
  const [formats, collections] = await Promise.all([
    api.getFormats().catch(() => ({ formats: [] })),
    api.getCollections().catch(() => ({ collections: [] })),
  ]);
  state.formats = formats.formats || [];
  state.collections = (collections.collections || []).slice()
    .sort((a, b) => String(b.created || "").localeCompare(String(a.created || "")));
}

// ---------------------------------------------------------------------------
// Deck list
// ---------------------------------------------------------------------------

// Show the chosen view, sort and filters in the tools above the decks.
function renderTools() {
  const { q, sort, format } = state.filters;
  $("decks-tools").hidden = state.decks.length === 0;
  const search = $("decks-search");
  if (search.value !== q) search.value = q;
  $("decks-sort").value = sort;
  // The format menu lists only the formats that have decks, by name.
  const select = $("decks-format");
  const keys = formatsOf(state.decks)
    .map((key) => [key, formatName(key)])
    .sort((a, b) => a[1].localeCompare(b[1]));
  select.replaceChildren(h("option", { value: "", text: "All" }),
    ...keys.map(([key, name]) => h("option", { value: key, text: name })));
  if (format && !keys.some(([key]) => key === format)) state.filters.format = "";
  select.value = state.filters.format;
  document.querySelectorAll("#decks-view-switch [data-view]").forEach((button) => {
    button.setAttribute("aria-pressed", String(button.dataset.view === state.view));
  });
}

function renderList() {
  renderTools();
  const shown = sortDecks(filterDecks(state.decks, state.filters), state.filters.sort);
  const actions = (deck) => ({
    onOpen: () => openEditor(deck.id),
    onDuplicate: () => duplicateDeck(deck),
    onDelete: () => deleteDeck(deck),
    formatName,
  });
  const grid = $("decks-grid");
  const table = $("decks-table");
  const list = state.view === "list";
  grid.textContent = "";
  table.textContent = "";
  grid.hidden = list || !shown.length;
  table.hidden = !list || !shown.length;
  if (list && shown.length) {
    table.append(deckTable(shown, {
      onOpen: (deck) => openEditor(deck.id),
      onDuplicate: duplicateDeck,
      onDelete: deleteDeck,
      formatName,
    }));
  } else {
    shown.forEach((deck) => grid.append(deckTile(deck, actions(deck))));
  }
  $("decks-empty").hidden = state.decks.length > 0;
  $("decks-none").hidden = !(state.decks.length && !shown.length);
}

function setFilters(change) {
  Object.assign(state.filters, change);
  saveFilters();
  renderList();
}

async function loadList() {
  const request = ++state.loadRequest;
  const errorBox = $("decks-error");
  errorBox.hidden = true;
  try {
    await loadLookups();
    const data = await api.listDecks();
    if (request !== state.loadRequest) return;
    state.decks = data.decks || [];
    renderList();
  } catch (error) {
    if (request !== state.loadRequest) return;
    state.decks = [];
    renderList();
    $("decks-empty").hidden = true;
    errorBox.textContent = `Could not load the decks: ${error.message}`;
    errorBox.hidden = false;
  }
}

async function duplicateDeck(deck) {
  try {
    await api.duplicateDeck(deck.id);
    showToast(`Duplicated ${deck.name}`, "success");
    await loadList();
  } catch (error) {
    showToast(`Could not duplicate the deck: ${error.message}`, "error");
  }
}

async function deleteDeck(deck) {
  const ok = await confirmDialog({
    title: "Delete deck",
    message: `Delete the deck "${deck.name}"? This cannot be undone.`,
    confirmLabel: "Delete deck",
  });
  if (!ok) return;
  try {
    await api.deleteDeck(deck.id);
    showToast(`Deleted ${deck.name}`, "success");
    await loadList();
  } catch (error) {
    showToast(`Could not delete the deck: ${error.message}`, "error");
  }
}

// ---------------------------------------------------------------------------
// Dialogs: new deck and import
// ---------------------------------------------------------------------------

function selectOf(id, options) {
  const select = h("select", { id });
  options.forEach(([value, label]) => select.append(h("option", { value, text: label })));
  return select;
}

function field(label, control) {
  return h("label", { class: "dialog-field" }, h("span", { text: label }), control);
}

// The new deck and import dialogs share these fields. onSubmit gets the field values.
function deckDialog({ title, submitLabel, defaultName, withText, onSubmit }) {
  const name = h("input", {
    type: "text", id: "decks-dialog-name", maxlength: "120", required: true, value: defaultName,
  });
  const formatKey = state.formats.some((f) => f.key === "commander") ? "commander"
    : (state.formats[0] || {}).key;
  const format = selectOf("decks-dialog-format", state.formats.map((f) => [f.key, f.name]));
  if (formatKey) format.value = formatKey;
  // A deck can read several collections; the newest one starts checked.
  const collection = selectOf("decks-dialog-collection",
    state.collections.map((c) => [c.job_id, `${c.name} (${Number(c.card_count).toLocaleString()})`]));
  collection.multiple = true;
  collection.dataset.placeholder = "Newest collection";
  collection.dataset.countLabel = "collections";
  if (collection.options.length) collection.options[0].selected = true;
  const chosenJobs = () => [...collection.options].filter((o) => o.selected).map((o) => o.value);
  const text = withText
    ? h("textarea", {
      id: "decks-dialog-text", rows: "10", maxlength: "50000", required: true,
      placeholder: "1 Sol Ring\n1 Command Tower\n...",
    })
    : null;
  return openDialog({
    title,
    submitLabel,
    content: [
      text ? field("Decklist", text) : null,
      field("Name", name), field("Format", format), field("Collection", collection),
    ],
    onSubmit: () => onSubmit({
      name: name.value.trim() || defaultName,
      format: format.value,
      collection_job_id: chosenJobs()[0] || null,
      collection_job_ids: chosenJobs(),
      text: text ? text.value : undefined,
    }),
  });
}

function newDeckDialog() {
  deckDialog({
    title: "New deck", submitLabel: "Create deck", defaultName: "New deck",
    onSubmit: async ({ name, format, collection_job_id, collection_job_ids }) => {
      const deck = await api.createDeck({ name, format, collection_job_id, collection_job_ids });
      openEditor(deck.id, { isNew: true });
    },
  });
}

function importDialog() {
  deckDialog({
    title: "Import decklist", submitLabel: "Import",
    defaultName: "Imported deck", withText: true,
    onSubmit: async ({ text, name, format, collection_job_id, collection_job_ids }) => {
      const deck = await api.importDeck({ text, name, format, collection_job_id, collection_job_ids });
      const unknown = deck.unknown || [];
      if (unknown.length) {
        const shown = unknown.slice(0, 8).join(", ");
        const more = unknown.length > 8 ? ` and ${unknown.length - 8} more` : "";
        showToast(`Imported. ${plural(unknown.length, "card")} not found: ${shown}${more}`, "info");
      } else {
        showToast("Imported the decklist", "success");
      }
      openEditor(deck.id, { imported: true, unknown });
    },
  });
}

// ---------------------------------------------------------------------------
// Editor entry
// ---------------------------------------------------------------------------

function showList() {
  $("deck-editor").hidden = true;
  $("decks-list").hidden = false;
}

// Close the open editor. The editor flushes its pending save; every caller
// waits for that same save, also a caller that comes after the editor closed.
function closeCurrent() {
  if (state.editing) {
    state.editing = null;
    // The next screen still opens when a save fails; the editor showed the error.
    closing = unmountEditor().catch(() => {});
  }
  return closing;
}

async function showEditor(deckId, options) {
  const host = $("deck-editor");
  // A second route to the open deck (the same hash again) keeps the editor.
  if (state.editing === deckId && !host.hidden) return;
  const ticket = ++state.ticket;
  // The old editor saves before the new one loads.
  await closeCurrent();
  if (ticket !== state.ticket) return; // a newer route came meanwhile
  state.editing = deckId;
  $("decks-list").hidden = true;
  host.hidden = false;
  mountEditor(host, deckId, Object.assign({ onClose: () => navigate("#decks") }, options));
}

async function showDeckList() {
  const ticket = ++state.ticket;
  await closeCurrent();
  if (ticket !== state.ticket) return; // a newer route came meanwhile
  loadChoices();
  showList();
  await loadList();
}

/**
 * Open a deck in the editor. It goes through the router (#deck/<id>).
 *
 * @param {string} deckId
 * @param {Object} [options] Editor options, for example {isNew: true} or {from: "forge"}.
 */
export function openEditor(deckId, options) {
  navigate(`#deck/${deckId}`, options || {});
}

/** Show the screen: the editor for params.deckId, else the deck list. */
export function open(params = {}) {
  if (params.deckId) return showEditor(params.deckId, params.state || {});
  const shown = showDeckList();
  // The command palette can ask for the New deck or the Import dialog.
  const asked = params.state || {};
  if (asked.newDeck) newDeckDialog();
  else if (asked.importDeck) importDialog();
  return shown;
}

/** Leave the screen. It resolves after the editor sent its pending save. */
export async function leave() {
  ++state.ticket;
  await closeCurrent();
  showList();
}

function init() {
  $("decks-new").addEventListener("click", newDeckDialog);
  $("decks-import").addEventListener("click", importDialog);
  // The empty state names the same two dialogs. Its "forge one" is a plain link to #forge.
  $("decks-empty").addEventListener("click", (event) => {
    const button = event.target.closest("button[data-empty]");
    if (!button) return;
    if (button.dataset.empty === "new") newDeckDialog();
    else if (button.dataset.empty === "import") importDialog();
  });
  $("decks-search").addEventListener("input", (event) => setFilters({ q: event.target.value }));
  $("decks-sort").addEventListener("change", (event) => setFilters({ sort: event.target.value }));
  $("decks-format").addEventListener("change", (event) => setFilters({ format: event.target.value }));
  $("decks-clear").addEventListener("click", () => {
    // Clear filters keeps the sort: the sort hides no deck.
    setFilters({ q: "", format: "" });
    $("decks-search").focus();
  });
  $("decks-view-switch").addEventListener("click", (event) => {
    const button = event.target.closest("[data-view]");
    if (!button || !VIEWS.includes(button.dataset.view)) return;
    state.view = button.dataset.view;
    writeStored("localStorage", VIEW_KEY, state.view);
    renderList();
  });
}

init();
