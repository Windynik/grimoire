// Decks view: the list of saved decks, and the entry point of the deck editor.
//
// Deck names, card names and server text go in with textContent only.

import { h } from "../shared/dom.js";
import { plural } from "../shared/format.js";
import { confirmDialog, openDialog } from "../shared/modal.js";
import { showToast } from "../shared/toast.js";
import * as api from "./api.js";
// Defines window.grimoireEditor before the first hash route opens a deck.
import "./editor.js";

const HASH = /^#deck\/([A-Za-z0-9_-]+)$/;

const $ = (id) => document.getElementById(id);

const state = {
  formats: [], collections: [], decks: [], loadRequest: 0, editing: null, pending: null,
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatName(key) {
  const found = state.formats.find((f) => f.key === key);
  return found ? found.name : key || "";
}

function formatDate(value) {
  const date = new Date(value);
  if (!value || Number.isNaN(date.getTime())) return "";
  return date.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
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

function deckIdFromHash() {
  const match = HASH.exec(location.hash);
  return match ? match[1] : null;
}

// ---------------------------------------------------------------------------
// Deck list
// ---------------------------------------------------------------------------

function deckTile(deck) {
  const art = h("div", { class: "deck-art", "aria-hidden": "true" });
  if (deck.image_url) {
    art.append(h("img", { src: deck.image_url, alt: "", loading: "lazy" }));
  } else {
    art.classList.add("deck-art-empty");
  }
  const meta = [formatName(deck.format), plural(deck.count || 0, "card")];
  const updated = formatDate(deck.updated);
  if (updated) meta.push(`Updated ${updated}`);

  const open = h("button", {
    type: "button", class: "btn btn-primary btn-compact",
    onclick: () => openEditor(deck.id),
  }, "Open");
  const duplicate = h("button", {
    type: "button", class: "btn btn-secondary btn-compact",
    onclick: () => duplicateDeck(deck),
  }, "Duplicate");
  const remove = h("button", {
    type: "button", class: "btn btn-danger btn-compact",
    onclick: () => deleteDeck(deck),
  }, "Delete");

  const title = h("button", {
    type: "button", class: "deck-name", onclick: () => openEditor(deck.id),
  });
  title.textContent = deck.name;
  const body = h("div", { class: "deck-body" },
    h("h3", { class: "deck-title" }, title),
    deck.commander
      ? h("p", { class: "deck-commander", text: deck.commander.name || deck.commander }) : null,
    h("p", { class: "deck-meta", text: meta.join(" · ") }),
    h("div", { class: "deck-actions" }, open, duplicate, remove));
  return h("article", { class: "deck-tile" }, art, body);
}

function renderList() {
  const grid = $("decks-grid");
  grid.textContent = "";
  state.decks.forEach((deck) => grid.append(deckTile(deck)));
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
  state.editing = null;
  $("deck-editor").hidden = true;
  $("decks-list").hidden = false;
}

// Contract with the editor module (Task 8): window.grimoireEditor.open(host, deckId, options)
// and window.grimoireEditor.close(). close() may return a promise; it flushes the pending save.
// Every path that tears the editor down awaits close() first: Back, browser Back, deck switch.
async function closeCurrent() {
  if (!state.editing) return;
  try {
    if (window.grimoireEditor && window.grimoireEditor.close) await window.grimoireEditor.close();
  } catch (e) {
    // The next screen still opens when a save fails; the editor showed the error.
  }
}

// Return to the list.
async function closeEditor() {
  await closeCurrent();
  if (deckIdFromHash()) history.pushState(null, "", location.pathname + location.search);
  showList();
  loadList();
}

async function showEditor(deckId, options) {
  const host = $("deck-editor");
  // The tab switch, the open call and the hash change all land here: open once.
  if (state.editing === deckId && !host.hidden) return;
  // A different deck: the old editor saves before the new one loads.
  if (state.editing && state.editing !== deckId) {
    await closeCurrent();
    if (state.editing === deckId) return;
  }
  state.editing = deckId;
  $("decks-list").hidden = true;
  host.hidden = false;
  host.textContent = "";
  if (window.grimoireEditor && window.grimoireEditor.open) {
    window.grimoireEditor.open(host, deckId, Object.assign({ onClose: closeEditor }, options));
    return;
  }
  // The editor module is not loaded: show a plain placeholder.
  host.append(
    h("button", { type: "button", class: "btn btn-secondary btn-compact", onclick: closeEditor },
      "Back to decks"),
    h("p", { class: "decks-empty", text: "The deck editor is not available yet." }),
  );
}

function openEditor(deckId, options) {
  const wanted = `#deck/${deckId}`;
  state.pending = options || {};
  if (location.hash !== wanted) location.hash = wanted;
  if (window.grimoireNav) window.grimoireNav.activateTab("decks");
  showEditor(deckId, state.pending);
  state.pending = null;
}

async function open() {
  const deckId = deckIdFromHash();
  if (deckId) {
    showEditor(deckId, state.pending || {});
    return;
  }
  showList();
  await loadList();
}

function init() {
  $("decks-new").addEventListener("click", newDeckDialog);
  $("decks-import").addEventListener("click", importDialog);
  window.addEventListener("hashchange", async () => {
    if (!$("decks-view").classList.contains("active")) return;
    const deckId = deckIdFromHash();
    if (deckId) showEditor(deckId, {});
    else {
      await closeCurrent();
      showList();
      loadList();
    }
  });
  if (deckIdFromHash() && window.grimoireNav) window.grimoireNav.activateTab("decks");
}

window.grimoireDecks = { open, openEditor };

if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
else init();
