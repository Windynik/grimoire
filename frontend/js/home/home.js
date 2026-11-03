// Home screen: the archive status, the bulk data download, and the collection list.
//
// Collection names and server text go in with textContent only.

import { navigate } from "../app/router.js";
import { h } from "../shared/dom.js";
import { formatDate } from "../shared/format.js";
import { confirmDialog } from "../shared/modal.js";
import {
  activeCollection, setActiveCollection, setViewerSource, viewerSource,
} from "../shared/session.js";
import { readSSE } from "../shared/sse.js";
import { showToast } from "../shared/toast.js";

const API_BASE = "/api";

const $ = (id) => document.getElementById(id);

let listRequest = 0;

// ---------------------------------------------------------------------------
// Archive status and the bulk data download
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
  const view = $("home-view");

  view.querySelector(".status-dot").classList.toggle("ready", isReady);
  view.querySelector(".status-text").textContent = isReady
    ? "Archive ready — everything works offline"
    : "Archive not downloaded yet (~100 MB, one-time)";
  $("card-count").textContent = isReady ? status.card_count?.toLocaleString() || "—" : "—";
  $("cache-size").textContent = isReady && status.file_size_mb
    ? `${status.file_size_mb.toFixed(1)} MB`
    : "—";
  $("last-updated").textContent = isReady ? formatDate(status.download_date) : "—";
  $("quick-process").disabled = !isReady;
}

async function downloadCache() {
  const progressContainer = $("download-progress");
  const progressFill = $("download-progress-fill");
  const progressText = $("download-progress-text");

  progressContainer.style.display = "block";
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
        showToast("Bulk data downloaded successfully!", "success");
        await checkCacheStatus();
        progressContainer.style.display = "none";
      }

      if (data.error) {
        showToast(data.error, "error");
        progressContainer.style.display = "none";
      }
    });
  } catch (error) {
    console.error("Download error:", error);
    showToast("Error downloading bulk data: " + error.message, "error");
    progressContainer.style.display = "none";
  }
}

async function clearCache() {
  const ok = await confirmDialog({
    title: "Clear the cache",
    message: "Are you sure you want to clear the cache?",
    confirmLabel: "Clear cache",
  });
  if (!ok) return;

  try {
    const response = await fetch(`${API_BASE}/cache`, { method: "DELETE" });
    if (response.ok) {
      showToast("Cache cleared successfully", "success");
      await checkCacheStatus();
    }
  } catch (error) {
    showToast("Error clearing cache", "error");
  }
}

// ---------------------------------------------------------------------------
// Collection list
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

function collectionRow(c) {
  const created = c.created ? ` · ${new Date(c.created).toLocaleDateString()}` : "";
  const count = Number(c.card_count || 0).toLocaleString();

  const exportLink = h("a", {
    class: "collection-export",
    href: `${API_BASE}/collection/${encodeURIComponent(c.job_id)}/export`,
    download: true,
    title: "Download this collection as a CSV",
    "aria-label": `Export ${c.name} as CSV`,
    onclick: (e) => {
      e.stopPropagation();
      e.preventDefault();
      exportCollection(c);
    },
  }, "Export CSV");

  const deleteButton = h("button", {
    class: "collection-del",
    title: "Delete this collection",
    "aria-label": `Delete ${c.name}`,
    onclick: (e) => {
      e.stopPropagation();
      deleteCollection(c);
    },
  }, "×");

  const openIt = () => {
    setActiveCollection(c.job_id);
    setViewerSource(c.job_id);
    navigate("#collection");
  };

  return h("div", {
    class: "collection-row",
    tabindex: "0",
    role: "button",
    "aria-label": `View ${c.name}`,
    onclick: openIt,
    onkeydown: (e) => {
      if (e.target !== e.currentTarget) return; // keys on the Export and Delete controls stay theirs
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        openIt();
      }
    },
  },
  h("img", { src: "/favicon.svg", alt: "", class: "collection-row-icon" }),
  h("span", { class: "collection-row-name", text: c.name }),
  h("span", { class: "collection-row-meta", text: `${count} cards${created}` }),
  h("span", { class: "collection-row-cta", text: "View →" }),
  exportLink,
  deleteButton);
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
        class: "settings-note", text: "No collections yet — process a ManaBox CSV to add one.",
      }));
      return;
    }
    container.replaceChildren(...data.collections.map(collectionRow));
  } catch (error) {
    console.error("Error loading dashboard collections:", error);
  }
}

// ---------------------------------------------------------------------------
// Entry
// ---------------------------------------------------------------------------

function init() {
  $("download-cache").addEventListener("click", downloadCache);
  $("clear-cache").addEventListener("click", clearCache);
  $("quick-process").addEventListener("click", () => navigate("#import"));
}

/** Show the screen: refresh the archive status and the collection list. */
export function open() {
  checkCacheStatus();
  loadCollections();
}

init();
