// Decks view: the list of saved decks, and the entry point of the deck editor.
//
// Deck names, card names and server text go in with textContent only.

import { h } from "../shared/dom.js";
import { plural } from "../shared/format.js";
import { confirmDialog, openDialog } from "../shared/modal.js";
import { showToast } from "../shared/toast.js";
import { navigate } from "../app/router.js";
import * as api from "./api.js";
import { deckTile } from "./tile.js";
import { closeEditor as unmountEditor, openEditor as mountEditor } from "./editor.js";

const $ = (id) => document.getElementById(id);

const state = {
  formats: [], collections: [], decks: [], loadRequest: 0,
  editing: null, // the id of the deck in the editor, or null
  ticket: 0, // bumped by every route change, so a stale editor open stops
};
let closing = Promise.resolve(); // the close of the last editor, with its save

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatName(key) {
  const found = state.formats.find((f) => f.key === key);
  return found ? found.name : key || "";
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

function renderList() {
  const grid = $("decks-grid");
  grid.textContent = "";
  state.decks.forEach((deck) => grid.append(deckTile(deck, {
    onOpen: () => openEditor(deck.id),
    onDuplicate: () => duplicateDeck(deck),
    onDelete: () => deleteDeck(deck),
    formatName,
  })));
  $("decks-empty").hidden = state.decks.length > 0;
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
  const collection = selectOf("decks-dialog-collection", [["", "No collection"]].concat(
    state.collections.map((c) => [c.job_id, `${c.name} (${Number(c.card_count).toLocaleString()})`]),
  ));
  if (state.collections.length) collection.value = state.collections[0].job_id;
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
      collection_job_id: collection.value || null,
      text: text ? text.value : undefined,
    }),
  });
}

function newDeckDialog() {
  deckDialog({
    title: "New deck", submitLabel: "Create deck", defaultName: "New deck",
    onSubmit: async ({ name, format, collection_job_id }) => {
      const deck = await api.createDeck({ name, format, collection_job_id });
      openEditor(deck.id, { isNew: true });
    },
  });
}

function importDialog() {
  deckDialog({
    title: "Import decklist", submitLabel: "Import",
    defaultName: "Imported deck", withText: true,
    onSubmit: async ({ text, name, format, collection_job_id }) => {
      const deck = await api.importDeck({ text, name, format, collection_job_id });
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
  return showDeckList();
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
}

init();
