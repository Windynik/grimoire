// Decks view: the list of saved decks, and the entry point of the deck editor.
//
// Deck names, card names and server text go in with textContent only.

import * as api from "./api.js";

const HASH = /^#deck\/([A-Za-z0-9_-]+)$/;

const $ = (id) => document.getElementById(id);

const state = {
  formats: [], collections: [], decks: [], loadRequest: 0, editing: null, pending: null,
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function h(tag, props, ...children) {
  const el = document.createElement(tag);
  Object.entries(props || {}).forEach(([key, value]) => {
    if (value === undefined || value === null || value === false) return;
    if (key === "class") el.className = value;
    else if (key === "text") el.textContent = value;
    else if (key.startsWith("on")) el.addEventListener(key.slice(2), value);
    else el.setAttribute(key, value === true ? "" : value);
  });
  children.flat().forEach((child) => {
    if (child !== null && child !== undefined) {
      el.append(child.nodeType ? child : document.createTextNode(String(child)));
    }
  });
  return el;
}

function toast(message, type) {
  if (typeof window.showToast === "function") window.showToast(message, type);
}

function formatName(key) {
  const found = state.formats.find((f) => f.key === key);
  return found ? found.name : key || "";
}

function formatDate(value) {
  const date = new Date(value);
  if (!value || Number.isNaN(date.getTime())) return "";
  return date.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

function plural(count, word) {
  return `${count} ${word}${count === 1 ? "" : "s"}`;
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
    toast(`Duplicated ${deck.name}`, "success");
    await loadList();
  } catch (error) {
    toast(`Could not duplicate the deck: ${error.message}`, "error");
  }
}

async function deleteDeck(deck) {
  if (!confirm(`Delete the deck "${deck.name}"? This cannot be undone.`)) return;
  try {
    await api.deleteDeck(deck.id);
    toast(`Deleted ${deck.name}`, "success");
    await loadList();
  } catch (error) {
    toast(`Could not delete the deck: ${error.message}`, "error");
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
  return h("label", { class: "decks-field" }, h("span", { text: label }), control);
}

function openDialog({ title, submitLabel, extra, onSubmit }) {
  const name = h("input", {
    type: "text", id: "decks-dialog-name", maxlength: "120", required: true,
    value: extra.defaultName,
  });
  const formatKey = state.formats.some((f) => f.key === "commander") ? "commander"
    : (state.formats[0] || {}).key;
  const format = selectOf("decks-dialog-format", state.formats.map((f) => [f.key, f.name]));
  if (formatKey) format.value = formatKey;
  const collection = selectOf("decks-dialog-collection", [["", "No collection"]].concat(
    state.collections.map((c) => [c.job_id, `${c.name} (${Number(c.card_count).toLocaleString()})`]),
  ));
  if (state.collections.length) collection.value = state.collections[0].job_id;
  const text = extra.withText
    ? h("textarea", {
      id: "decks-dialog-text", rows: "10", maxlength: "50000", required: true,
      placeholder: "1 Sol Ring\n1 Command Tower\n...",
    })
    : null;
  const error = h("p", { class: "decks-dialog-error", role: "alert", hidden: true });
  const submit = h("button", { type: "submit", class: "btn btn-primary" }, submitLabel);
  const cancel = h("button", { type: "button", class: "btn btn-secondary" }, "Cancel");
  const form = h("form", { class: "decks-form", method: "dialog" },
    h("h2", { class: "decks-dialog-title", text: title }),
    text ? field("Decklist", text) : null,
    field("Name", name), field("Format", format), field("Collection", collection),
    error, h("div", { class: "decks-dialog-actions" }, cancel, submit));
  const dialog = h("dialog", { class: "decks-dialog" }, form);
  document.body.append(dialog);
  const close = () => {
    dialog.close();
    dialog.remove();
  };
  cancel.addEventListener("click", close);
  dialog.addEventListener("cancel", (event) => {
    event.preventDefault();
    close();
  });
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    submit.disabled = true;
    error.hidden = true;
    try {
      await onSubmit({
        name: name.value.trim() || extra.defaultName,
        format: format.value,
        collection_job_id: collection.value || null,
        text: text ? text.value : undefined,
      });
      close();
    } catch (err) {
      error.textContent = err.message;
      error.hidden = false;
      submit.disabled = false;
    }
  });
  dialog.showModal();
  (text || name).focus();
}

function newDeckDialog() {
  openDialog({
    title: "New deck", submitLabel: "Create deck", extra: { defaultName: "New deck" },
    onSubmit: async ({ name, format, collection_job_id }) => {
      const deck = await api.createDeck({ name, format, collection_job_id });
      openEditor(deck.id, { isNew: true });
    },
  });
}

function importDialog() {
  openDialog({
    title: "Import decklist", submitLabel: "Import",
    extra: { defaultName: "Imported deck", withText: true },
    onSubmit: async ({ text, name, format, collection_job_id }) => {
      const deck = await api.importDeck({ text, name, format, collection_job_id });
      const unknown = deck.unknown || [];
      if (unknown.length) {
        const shown = unknown.slice(0, 8).join(", ");
        const more = unknown.length > 8 ? ` and ${unknown.length - 8} more` : "";
        toast(`Imported. ${plural(unknown.length, "card")} not found: ${shown}${more}`, "info");
      } else {
        toast("Imported the decklist", "success");
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

// Return to the list. The editor module (if loaded) gets to flush its save.
async function closeEditor() {
  try {
    if (window.grimoireEditor && window.grimoireEditor.close) await window.grimoireEditor.close();
  } catch (e) {
    // The list still opens when a save fails; the editor showed the error.
  }
  if (deckIdFromHash()) history.pushState(null, "", location.pathname + location.search);
  showList();
  loadList();
}

function showEditor(deckId, options) {
  const host = $("deck-editor");
  // The tab switch, the open call and the hash change all land here: open once.
  if (state.editing === deckId && !host.hidden) return;
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
  window.addEventListener("hashchange", () => {
    if (!$("decks-view").classList.contains("active")) return;
    const deckId = deckIdFromHash();
    if (deckId) showEditor(deckId, {});
    else {
      showList();
      loadList();
    }
  });
  if (deckIdFromHash() && window.grimoireNav) window.grimoireNav.activateTab("decks");
}

window.grimoireDecks = { open, openEditor };

if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
else init();
