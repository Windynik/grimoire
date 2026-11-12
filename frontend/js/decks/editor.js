// Deck editor: loads one deck, keeps the undo history, and saves every change.
//
// Every card edit goes through state.apply(op): history push, render, save.
// The PUT response replaces only the analysis, so a slow response never undoes
// a newer edit. Deck names and server text go in with textContent only.

import * as api from "./api.js";
import { applyOp, History, SaveQueue, sameDeck, SECTIONS } from "./model.js";
import { h, safeManaCost } from "../shared/dom.js";
import { showCardDetail } from "../shared/card.js";
import { cardImage, preload } from "../shared/images.js";
import { showToast } from "../shared/toast.js";
import { renderAgent } from "./agent.js";
import { renderExplanation } from "../forge/feed.js";
import { renderExportMenu } from "./exportmenu.js";
import { renderHand } from "./hand.js";
import { renderPull, renderPullState } from "./pull.js";
import { hidePreview, renderPane } from "./pane.js";
import { renderSearch } from "./search.js";
import { renderStats } from "./stats.js";

const GROUP_KEY = "grimoire.groupMode";
const GROUP_MODES = ["type", "role", "cmc"];
const RETRY_MS = 3000;
const PRELOAD_LIMIT = 6; // images that preload at the same time
const STATUS_TEXT = {
  saving: "Saving…",
  saved: "Saved",
  retrying: "Not saved — retrying",
  failed: "Not saved",
};

let session = null;

function readGroupMode() {
  try {
    const mode = localStorage.getItem(GROUP_KEY);
    return GROUP_MODES.includes(mode) ? mode : "type";
  } catch (e) {
    return "type";
  }
}

function writeGroupMode(mode) {
  try {
    localStorage.setItem(GROUP_KEY, mode);
  } catch (e) {
    // The choice lasts only for this page.
  }
}

function isTextField(el) {
  if (!el) return false;
  if (el.isContentEditable || el.tagName === "TEXTAREA") return true;
  return el.tagName === "INPUT"
    && !["button", "checkbox", "radio", "range", "submit", "reset"].includes(el.type);
}

function entryBody(entry) {
  return {
    scryfall_id: entry.scryfall_id || null,
    name: entry.name,
    count: entry.count,
    basic: Boolean(entry.basic),
    role: entry.role || "",
    reason: entry.reason || "",
  };
}

function option(value, label) {
  const el = document.createElement("option");
  el.value = value;
  el.textContent = label;
  return el;
}

// Copy the editor markup from its template into the host.
function mount(host) {
  const template = document.getElementById("deck-editor-template");
  host.textContent = "";
  host.append(template.content.cloneNode(true));
  const pick = (name) => host.querySelector(`[data-editor="${name}"]`);
  return {
    loading: pick("loading"),
    loadingText: pick("loading-text"),
    shell: pick("shell"),
    error: pick("error"),
    back: host.querySelectorAll('[data-editor="back"]'),
    name: pick("name"),
    format: pick("format"),
    collection: pick("collection"),
    status: pick("status"),
    undo: pick("undo"),
    redo: pick("redo"),
    group: pick("group"),
    pane: pick("pane"),
    search: pick("search"),
    stats: pick("stats"),
    side: pick("side"),
    agent: pick("agent"),
    sideTabs: host.querySelectorAll('[data-editor="side-tab"]'),
    body: pick("body"),
    tabs: host.querySelectorAll('[data-editor="tab"]'),
    center: pick("center"),
    viewTabs: host.querySelectorAll('[data-editor="view-tab"]'),
    hand: pick("hand"),
    explanation: pick("explanation"),
    pull: pick("pull"),
    exportMenu: pick("export"),
  };
}

// Text of the Explanation view: the backbone, the forge explanation, and the reason per card.
function renderExplain(root, state) {
  const forge = state.forge || {};
  const backbone = forge.backbone;
  const reasons = (state.sections.main || []).filter((entry) => String(entry.reason || "").trim());
  if (!backbone && !forge.explanation && !reasons.length) {
    root.replaceChildren(h("p", {
      class: "explain-empty", text: "This deck was not forged, so it has no explanation.",
    }));
    return;
  }
  const parts = [];
  if (backbone) {
    parts.push(h("h3", { class: "explain-title", text: backbone.name || "Backbone" }));
    if (backbone.thesis) parts.push(h("p", { class: "explain-thesis", text: backbone.thesis }));
    if (backbone.playstyle) {
      parts.push(h("p", { class: "explain-playstyle" },
        h("strong", { text: "Playstyle: " }), backbone.playstyle));
    }
    const links = backbone.key_interactions || [];
    if (links.length) {
      parts.push(h("h4", { text: "Key interactions" }), h("ul", { class: "explain-links" },
        links.map((link) => h("li", {},
          h("strong", { text: [].concat(link.cards || []).join(" + ") }),
          link.why ? ` — ${link.why}` : ""))));
    }
  }
  if (forge.explanation) {
    const body = h("div", { class: "explain-body" });
    renderExplanation(body, forge.explanation);
    parts.push(body);
  }
  if (reasons.length) {
    parts.push(h("h4", { text: "Reasons per card" }), h("ul", { class: "explain-reasons" },
      reasons.map((entry) => h("li", {},
        h("strong", { text: entry.name }), ` — ${entry.reason}`))));
  }
  root.replaceChildren(...parts);
}

// Load the front images of the deck in the background, so the first hover is
// fast. One queue loads PRELOAD_LIMIT images at a time: first the small images of
// every card, then the normal images of the commander and the main deck. Only
// local images preload; a card without a valid id is skipped.
// Returns the function that stops the preload.
function preloadDeck(state) {
  const main = [state.commander, ...(state.sections.main || [])].filter(Boolean);
  const all = main.concat(state.sections.sideboard || [], state.sections.maybeboard || []);
  const local = (url) => url.startsWith("/api/images/");
  const small = all.map((card) => cardImage(card, "front", "small")).filter(local);
  const normal = main.map((card) => cardImage(card, "front", "normal")).filter(local);
  return preload(small.concat(normal), PRELOAD_LIMIT);
}

/** A random id for one editor tab. */
function randomId() {
  try {
    if (globalThis.crypto && globalThis.crypto.randomUUID) return globalThis.crypto.randomUUID();
  } catch (e) {
    // Fall back below.
  }
  return `tab-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}

function createSession(host, deckId, options) {
  const view = mount(host);
  const history = new History();
  const queue = new SaveQueue(send);
  let closed = false;
  let deck = null; // Loaded fields the editor sends back unchanged, plus name and collection.
  let lastBody = null; // Newest body given to the queue.
  let status = "saved";
  let retryTimer = null;
  let stopPreload = () => {};
  // The order mark of each save (see edit_check on the server): a random id of
  // this tab, a number that rises with each save, and the newest deck revision.
  const clientId = randomId();
  let seq = 0;
  let revision = 0;
  let shownSeq = -1; // The save whose analysis is on screen.

  const state = {
    deckId,
    sections: { main: [], sideboard: [], maybeboard: [] },
    commander: null,
    analysis: {},
    forge: { backbone: null, explanation: "" },
    groupMode: readGroupMode(),
    flipped: new Set(),
    get canUndo() {
      return history.canUndo;
    },
    get canRedo() {
      return history.canRedo;
    },
    /** Apply one edit: push it on the history, render, and schedule a save. */
    apply(op) {
      if (!deck || closed) return;
      const next = applyOp(state, op);
      if (sameDeck(next, state)) return;
      state.sections = next.sections;
      state.commander = next.commander;
      history.push(next);
      state.render();
      state.save();
    },
    undo() {
      restore(history.undo());
    },
    redo() {
      restore(history.redo());
    },
    /** Schedule a save of the whole deck. */
    save() {
      if (!deck || closed) return;
      lastBody = body();
      clearTimeout(retryTimer);
      setStatus("saving");
      queue.schedule(lastBody);
    },
    /** Send the pending edits. It rejects when the last save failed. */
    saveNow: () => saveBeforeExport(),
    render,
  };

  const handlers = { apply: (op) => state.apply(op), showCard };

  function restore(snapshot) {
    if (!snapshot || closed) return;
    state.sections = snapshot.sections;
    state.commander = snapshot.commander;
    render();
    state.save();
  }

  function body() {
    const sections = {};
    SECTIONS.forEach((section) => {
      sections[section] = (state.sections[section] || []).map(entryBody);
    });
    const commander = state.commander
      ? { scryfall_id: state.commander.scryfall_id, name: state.commander.name } : null;
    return {
      name: deck.name,
      format: deck.format,
      commander,
      collection_job_id: deck.collection_job_id,
      deck_size: deck.deck_size,
      max_copies: deck.max_copies,
      sections,
      edit: { client: clientId, seq: ++seq, base_revision: revision },
    };
  }

  function setStatus(next) {
    status = next;
    view.status.textContent = STATUS_TEXT[next];
    view.status.dataset.state = next;
  }

  async function send(snapshot, sendOptions) {
    // The revision can rise while the save waits in the queue.
    snapshot.edit.base_revision = revision;
    const response = await api.saveDeck(deckId, snapshot, sendOptions);
    if (closed) return;
    if (response && Number.isInteger(response.revision)) revision = Math.max(revision, response.revision);
    // A hidden tab sends its newest save at once, so an older save can answer
    // last. Its analysis must not replace the newer one.
    if (response && response.analysis && snapshot.edit.seq >= shownSeq) {
      shownSeq = snapshot.edit.seq;
      state.analysis = response.analysis;
    }
    if (snapshot === lastBody) {
      setStatus("saved");
      view.error.hidden = true;
    }
    render();
  }

  queue.onError = (error) => {
    if (closed) {
      showToast(`Could not save the deck: ${error.message}`, "error");
      return;
    }
    // A 4xx answer does not change on a retry.
    if (error.status >= 400 && error.status < 500) {
      setStatus("failed");
      view.error.textContent = `Could not save the deck: ${error.message}`;
      view.error.hidden = false;
      return;
    }
    setStatus("retrying");
    clearTimeout(retryTimer);
    retryTimer = setTimeout(() => {
      if (!closed && status === "retrying") queue.schedule(lastBody);
    }, RETRY_MS);
  };

  // Send now. A failed body waits for its retry, so it goes back in the queue first.
  function flushNow(flushOptions) {
    if (status === "retrying" && lastBody) {
      clearTimeout(retryTimer);
      queue.schedule(lastBody);
    }
    return queue.flush(flushOptions);
  }

  // The pull list reads the saved deck, so the last edits are saved first.
  let pullRequest = 0;
  async function showPull() {
    const request = ++pullRequest;
    renderPullState(view.pull, "Finding your cards…");
    try {
      await flushNow();
      const data = await api.pullList(deckId);
      if (closed || request !== pullRequest) return;
      renderPull(view.pull, deckId, data, { copy: copyText });
    } catch (error) {
      if (closed || request !== pullRequest) return;
      renderPullState(view.pull, `Could not make the pull list: ${error.message}`, true);
    }
  }

  async function copyText(text) {
    try {
      await navigator.clipboard.writeText(text);
      showToast("Pull list copied", "success");
    } catch (error) {
      showToast("Could not copy the pull list", "error");
    }
  }

  // The export reads the saved deck, so it must not run after a failed save.
  async function saveBeforeExport() {
    await flushNow();
    if (status !== "saved") throw new Error("the last change is not saved");
  }

  function showCard(card) {
    const info = (state.analysis.cards || {})[card.scryfall_id || `basic:${card.name}`] || {};
    showCardDetail({
      scryfall_id: card.scryfall_id,
      name: card.name,
      image_url: card.image_url || "",
      back_image_url: card.back_image_url || "",
      mana_cost: safeManaCost(card.mana_cost),
      type_line: card.type_line || "",
      price: card.price || 0,
      quantity: info.owned || 0,
    });
  }

  function render() {
    if (!deck || closed) return;
    view.undo.disabled = !history.canUndo;
    view.redo.disabled = !history.canRedo;
    const fmt = state.analysis.format || {};
    view.format.textContent = fmt.name || deck.format || "";
    // With no collection chosen, the server uses the newest one.
    const newest = view.collection.options[0];
    const used = (state.analysis.collection || {}).name;
    if (newest) {
      if (!deck.collection_job_id && used) newest.textContent = `Newest (${used})`;
      else newest.textContent = view.collection.options.length > 1 ? "Newest collection" : "No collection";
    }
    renderPane(view.pane, state, handlers);
    renderStats(view.stats, state.analysis);
    renderSearch(view.search, state);
    renderHand(view.hand, state);
    renderExplain(view.explanation, state);
  }

  function fillCollections(collections) {
    const select = view.collection;
    const list = (collections || []).slice()
      .sort((a, b) => String(b.created || "").localeCompare(String(a.created || "")));
    select.replaceChildren(option("", "No collection"));
    list.forEach((c) => select.append(option(c.job_id, c.name || c.job_id)));
    const current = deck.collection_job_id;
    if (current && !list.some((c) => c.job_id === current)) {
      const named = (state.analysis.collection || {}).name;
      select.append(option(current, named || "Unknown collection"));
    }
    select.value = current || "";
  }

  // ---- Header controls ----

  function commitName() {
    const value = view.name.value.trim();
    if (!value) {
      view.name.value = deck.name;
      return;
    }
    if (value === deck.name) return;
    deck.name = value;
    state.save();
  }

  view.name.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      view.name.blur();
    } else if (event.key === "Escape") {
      view.name.value = deck ? deck.name : "";
      view.name.blur();
    }
  });
  view.name.addEventListener("blur", () => {
    if (deck) commitName();
  });
  view.collection.addEventListener("change", () => {
    if (!deck) return;
    deck.collection_job_id = view.collection.value || null;
    state.save();
  });
  view.group.value = state.groupMode;
  view.group.addEventListener("change", () => {
    state.groupMode = GROUP_MODES.includes(view.group.value) ? view.group.value : "type";
    writeGroupMode(state.groupMode);
    render();
  });
  view.tabs.forEach((tab) => tab.addEventListener("click", () => {
    view.body.dataset.tab = tab.dataset.tab;
    view.tabs.forEach((other) => other.setAttribute("aria-selected", String(other === tab)));
  }));
  // The view switch picks what the center column shows. The layout tabs above pick panels.
  view.viewTabs.forEach((tab) => tab.addEventListener("click", () => {
    hidePreview();
    view.center.dataset.view = tab.dataset.view;
    view.viewTabs.forEach((other) => other.setAttribute("aria-selected", String(other === tab)));
    if (tab.dataset.view === "pull") showPull();
  }));
  // The side switch picks Stats or Agent inside the right panel. The layout tabs are not touched.
  view.sideTabs.forEach((tab) => tab.addEventListener("click", () => {
    view.side.dataset.side = tab.dataset.side;
    view.sideTabs.forEach((other) => other.setAttribute("aria-selected", String(other === tab)));
  }));
  view.undo.addEventListener("click", () => state.undo());
  view.redo.addEventListener("click", () => state.redo());
  view.back.forEach((button) => button.addEventListener("click", () => {
    if (options.onClose) options.onClose();
    else closeEditor();
  }));

  // ---- Page events ----

  function onKey(event) {
    if (closed || !deck || host.hidden || !host.getClientRects().length) return;
    if (!(event.ctrlKey || event.metaKey) || event.altKey) return;
    if (String(event.key).toLowerCase() !== "z") return;
    if (isTextField(document.activeElement)) return;
    event.preventDefault();
    if (event.shiftKey) state.redo();
    else state.undo();
  }

  function onPageHide() {
    flushNow({ closing: true });
  }

  function onVisibility() {
    if (document.visibilityState === "hidden") flushNow({ closing: true });
  }

  document.addEventListener("keydown", onKey);
  window.addEventListener("pagehide", onPageHide);
  document.addEventListener("visibilitychange", onVisibility);

  async function load() {
    try {
      const [record, collections] = await Promise.all([
        api.getDeck(deckId),
        api.getCollections().catch(() => ({ collections: [] })),
      ]);
      if (closed) return;
      revision = Number.isInteger(record.revision) ? record.revision : 0;
      deck = {
        name: record.name || "Untitled deck",
        format: record.format,
        collection_job_id: record.collection_job_id || null,
        deck_size: record.deck_size ?? null,
        max_copies: record.max_copies ?? null,
      };
      const sections = record.sections || {};
      SECTIONS.forEach((section) => {
        state.sections[section] = Array.isArray(sections[section]) ? sections[section] : [];
      });
      state.commander = record.commander || null;
      state.analysis = record.analysis || {};
      state.forge = { backbone: record.backbone || null, explanation: record.explanation || "" };
      history.push(state);
      renderAgent(view.agent, state);
      renderExportMenu(view.exportMenu, deckId, { beforeExport: saveBeforeExport, toast: showToast });
      view.name.value = deck.name;
      fillCollections(collections.collections);
      setStatus("saved");
      view.loading.hidden = true;
      view.shell.hidden = false;
      render();
      stopPreload = preloadDeck(state);
      if (options.isNew) {
        view.name.focus();
        view.name.select();
      }
    } catch (error) {
      if (closed) return;
      view.loadingText.textContent = `Could not load the deck: ${error.message}`;
      view.loadingText.setAttribute("role", "alert");
    }
  }

  async function close() {
    if (closed) return;
    document.removeEventListener("keydown", onKey);
    window.removeEventListener("pagehide", onPageHide);
    document.removeEventListener("visibilitychange", onVisibility);
    hidePreview();
    stopPreload();
    // A name typed but not yet committed (browser Back, deck switch) still saves.
    if (deck && document.activeElement === view.name) commitName();
    const flushed = flushNow();
    closed = true;
    clearTimeout(retryTimer);
    await flushed;
  }

  return { state, load, close };
}

/**
 * Open the editor for one deck in root.
 *
 * @param {HTMLElement} root Host element; the editor replaces its content.
 * @param {string} deckId
 * @param {{onClose: function(), isNew: boolean}} [options] onClose runs on "Back to decks".
 * @returns {Object} The editor state (apply, undo, redo, save, render, and the deck data).
 */
export function openEditor(root, deckId, options = {}) {
  if (session) closeEditor();
  const current = createSession(root, deckId, options);
  session = current;
  current.load();
  return current.state;
}

/**
 * Close the open editor. It does not call onClose.
 *
 * @returns {Promise<void>} Resolves after the pending save is sent and answered.
 */
export function closeEditor() {
  const current = session;
  session = null;
  return current ? current.close() : Promise.resolve();
}
