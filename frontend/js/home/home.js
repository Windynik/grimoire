// Home screen: quick actions, the card data status, the collections, and the recent decks.
//
// Collection names, deck names and server text go in with textContent only.

import { navigate } from "../app/router.js";
import * as decksApi from "../decks/api.js";
import { deckTile } from "../decks/tile.js";
import { h } from "../shared/dom.js";
import { formatDate } from "../shared/format.js";
import { confirmDialog } from "../shared/modal.js";
import {
  activeCollection, setActiveCollection, setViewerSource, viewerSource,
} from "../shared/session.js";
import { readSSE } from "../shared/sse.js";
import { showToast } from "../shared/toast.js";

const API_BASE = "/api";
const RECENT_DECKS = 4;

const $ = (id) => document.getElementById(id);

let listRequest = 0;
let decksRequest = 0;
let downloading = false;
let formatNames = new Map();

// ---------------------------------------------------------------------------
// Card data status and the download
// ---------------------------------------------------------------------------

async function checkCacheStatus() {
  try {
    const response = await fetch(`${API_BASE}/cache/status`);
    updateCacheStatusUI(await response.json());
  } catch (error) {
    showToast("Error checking cache status", "error");
  }
}

function updateCacheStatusUI(status) {
  const isReady = status.status === "ready";

  $("home-view").querySelector(".status-dot").classList.toggle("ready", isReady);
  $("home-status-text").textContent = isReady
    ? "Card data ready. Everything works offline."
    : "Card data not downloaded yet (about 100 MB, one time).";
  $("card-count").textContent = isReady ? status.card_count?.toLocaleString() || "—" : "—";
  $("cache-size").textContent = isReady && status.file_size_mb
    ? `${status.file_size_mb.toFixed(1)} MB`
    : "—";
  $("last-updated").textContent = isReady ? formatDate(status.download_date) : "—";
  $("download-cache").textContent = isReady ? "Update card data" : "Download card data";
}

async function downloadCache() {
  if (downloading) return;
  downloading = true;
  const button = $("download-cache");
  const progressContainer = $("download-progress");
  const progressFill = $("download-progress-fill");
  const progressText = $("download-progress-text");
  const finish = () => {
    progressContainer.hidden = true;
    button.disabled = false;
    downloading = false;
  };

  button.disabled = true;
  progressContainer.hidden = false;
  progressFill.style.transform = "scaleX(0)";
  progressText.textContent = "0%";

  try {
    const response = await fetch(`${API_BASE}/cache/download`, { method: "POST" });

    await readSSE(response, async (data) => {
      if (data.percentage !== undefined) {
        progressFill.style.transform = `scaleX(${data.percentage / 100})`;
        progressText.textContent = `${data.percentage}%`;
        const progressBar = progressContainer.querySelector(".progress-bar");
        if (progressBar) progressBar.setAttribute("aria-valuenow", data.percentage);
      }

      if (data.status === "complete") {
        showToast("Card data downloaded", "success");
        await checkCacheStatus();
        finish();
      }

      if (data.error) {
        showToast(data.error, "error");
        finish();
      }
    });
  } catch (error) {
    console.error("Download error:", error);
    showToast("Error downloading card data: " + error.message, "error");
  } finally {
    finish();
  }
}

// ---------------------------------------------------------------------------
// Collections
// ---------------------------------------------------------------------------

// Fetch the collection CSV and save it. A failed export shows the server's reason.
async function exportCollection(c) {
  try {
    const res = await fetch(`${API_BASE}/collection/${encodeURIComponent(c.job_id)}/export`);
    if (!res.ok) {
      let detail = `Export failed (HTTP ${res.status})`;
      try {
        const body = await res.json();
        if (body && typeof body.detail === "string") detail = body.detail;
      } catch (e) {
        // The body is not JSON: keep the status text.
      }
      showToast(detail, "error");
      return;
    }
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const link = h("a", { href: url, download: `${c.name || "collection"}.csv` });
    document.body.appendChild(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  } catch (error) {
    showToast("Error exporting collection", "error");
  }
}

async function deleteCollection(c) {
  const ok = await confirmDialog({
    title: "Delete collection",
    message: `Delete “${c.name}” (${c.card_count} cards)? This cannot be undone.`,
    confirmLabel: "Delete",
  });
  if (!ok) return;

  try {
    const res = await fetch(`${API_BASE}/collection/${c.job_id}`, { method: "DELETE" });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);

    // Forget it everywhere. The viewer reloads when its source changes.
    if (activeCollection() === c.job_id) setActiveCollection(null);
    if (viewerSource() === c.job_id) setViewerSource(null);

    showToast(`“${c.name}” deleted`, "success");
    loadCollections();
  } catch (error) {
    showToast("Error deleting collection", "error");
  }
}

function openCollection(c) {
  setActiveCollection(c.job_id);
  setViewerSource(c.job_id);
  navigate("#collection");
}

function collectionRow(c) {
  const created = c.created ? ` · ${new Date(c.created).toLocaleDateString()}` : "";
  const count = Number(c.card_count || 0).toLocaleString();

  const view = h("button", {
    type: "button",
    class: "btn btn-secondary btn-compact collection-view",
    "aria-label": `View ${c.name}`,
    onclick: () => openCollection(c),
  }, "View");

  const exportLink = h("a", {
    class: "btn btn-secondary btn-compact collection-export",
    href: `${API_BASE}/collection/${encodeURIComponent(c.job_id)}/export`,
    download: true,
    title: "Download this collection as a CSV",
    "aria-label": `Export ${c.name} as CSV`,
    onclick: (e) => {
      e.preventDefault();
      exportCollection(c);
    },
  }, "Export CSV");

  const remove = h("button", {
    type: "button",
    class: "btn btn-danger btn-compact collection-del",
    "aria-label": `Delete ${c.name}`,
    onclick: () => deleteCollection(c),
  }, "Delete");

  return h("div", { class: "collection-row" },
    h("img", { src: "/favicon.svg", alt: "", class: "collection-row-icon" }),
    h("div", { class: "collection-row-info" },
      h("span", { class: "collection-row-name", text: c.name }),
      h("span", { class: "collection-row-meta", text: `${count} cards${created}` })),
    h("div", { class: "collection-row-actions" }, view, exportLink, remove));
}

async function loadCollections() {
  const request = ++listRequest;
  const container = $("dashboard-collections");

  try {
    const response = await fetch(`${API_BASE}/collections`);
    if (!response.ok) return;
    const data = await response.json();
    if (request !== listRequest) return;

    if (data.collections.length === 0) {
      container.replaceChildren(h("p", {
        class: "home-empty",
        text: "No collections yet. Import a ManaBox CSV to start.",
      }));
      return;
    }
    container.replaceChildren(...data.collections.map(collectionRow));
  } catch (error) {
    console.error("Error loading dashboard collections:", error);
  }
}

// ---------------------------------------------------------------------------
// Recent decks
// ---------------------------------------------------------------------------

async function loadFormats() {
  if (formatNames.size) return;
  try {
    const data = await decksApi.getFormats();
    formatNames = new Map((data.formats || []).map((f) => [f.key, f.name]));
  } catch (error) {
    // The tiles show the format key instead.
  }
}

async function loadDecks() {
  const request = ++decksRequest;
  const container = $("home-decks");

  try {
    const [data] = await Promise.all([decksApi.listDecks(), loadFormats()]);
    if (request !== decksRequest) return;
    const recent = (data.decks || []).slice(0, RECENT_DECKS);

    if (recent.length === 0) {
      container.replaceChildren(h("p", {
        class: "home-empty",
        text: "No decks yet. Forge one, or create one in Decks.",
      }));
      return;
    }
    container.replaceChildren(...recent.map((deck) => deckTile(deck, {
      compact: true,
      onOpen: () => navigate(`#deck/${encodeURIComponent(deck.id)}`),
      formatName: (key) => formatNames.get(key) || key || "",
    })));
  } catch (error) {
    if (request !== decksRequest) return;
    container.replaceChildren(h("p", {
      class: "home-empty", text: `Could not load the decks: ${error.message}`,
    }));
  }
}

// ---------------------------------------------------------------------------
// Entry
// ---------------------------------------------------------------------------

function init() {
  $("download-cache").addEventListener("click", downloadCache);
}

/** Show the screen: refresh the card data status, the collections, and the decks. */
export function open() {
  checkCacheStatus();
  loadCollections();
  loadDecks();
}

init();
