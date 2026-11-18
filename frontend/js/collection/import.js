// Import screen: upload a collection export or paste a card list, show live
// progress, then show a summary.
//
// One of three states shows at a time: upload, progress, or summary.
//
// The import adds a new collection, or it replaces one (same job id, same
// name), so the decks that read that collection stay linked.

import { navigate } from "../app/router.js";
import { h } from "../shared/dom.js";
import { getJSON } from "../shared/http.js";
import { isImportFile, sourceText, WRONG_FILE } from "../shared/importfile.js";
import { readSSE } from "../shared/sse.js";
import { setActiveCollection, setViewerSource } from "../shared/session.js";
import { showToast } from "../shared/toast.js";

const API_BASE = "/api";
const MAX_UNMATCHED_ROWS = 100;
const STOPPED = "The import stopped. Try again.";
const REASONS = {
  not_found: "Not in the card data",
  missing_scryfall_id: "No Scryfall ID",
  unknown_card: "No card with this name",
};

const $ = (id) => document.getElementById(id);

let busy = false; // an import is running
let resultJobId = null; // the job of the summary on view
let targetsRequest = 0; // bumped by each read of the collection list

/** Show one state: "upload", "progress" or "summary". */
function showState(name) {
  $("import-upload").hidden = name !== "upload";
  $("import-progress").hidden = name !== "progress";
  $("import-summary").hidden = name !== "summary";
}

// ---- the import target: a new collection, or one to replace ----------------

/** The job id of the collection to replace, or "" for a new collection. */
function replaceTarget() {
  return $("import-target").value;
}

function syncTarget() {
  // One collection per binder makes new collections, so it does not apply to a replace.
  $("import-split").disabled = Boolean(replaceTarget());
}

/** Fill the choice from the collection list. A choice that is gone falls back to a new collection. */
async function loadTargets() {
  const request = ++targetsRequest;
  let collections = [];
  try {
    const data = await getJSON("/collections");
    collections = Array.isArray(data && data.collections) ? data.collections : [];
  } catch (error) {
    // Without the list the import still adds a new collection.
  }
  if (request !== targetsRequest) return;
  const select = $("import-target");
  const chosen = select.value;
  select.replaceChildren(h("option", { value: "", text: "Add as a new collection" }),
    ...collections.map((c) => h("option", { value: c.job_id, "data-name": c.name, text: `Replace ${c.name}` })));
  select.value = collections.some((c) => c.job_id === chosen) ? chosen : "";
  $("import-target-field").hidden = collections.length === 0;
  syncTarget();
}

/** Show Upload again. A failed import keeps the pasted list and the choice, so they are not lost. */
function resetToUpload({ clearPaste = false } = {}) {
  $("file-input").value = "";
  if (clearPaste) {
    $("import-paste-text").value = "";
    $("import-target").value = "";
    syncTarget();
  }
  resultJobId = null;
  showState("upload");
}

function fail(message) {
  showToast(message || STOPPED, "error");
  resetToUpload();
}

function showProgress(event) {
  const total = Number(event.total) || 0;
  const current = Number(event.current) || 0;
  const percent = total > 0 ? Math.min(100, Math.round((current / total) * 100)) : 0;
  $("import-progress-fill").style.transform = `scaleX(${total > 0 ? Math.min(1, current / total) : 0})`;
  $("import-progress").querySelector(".progress-bar").setAttribute("aria-valuenow", percent);
  // The server loads the card index first, so the total is 0 for a few seconds.
  $("import-row-text").textContent = total > 0 ? `Row ${current} of ${total}` : "Reading the card data…";
  $("import-card-name").textContent = event.current_card || " ";
  $("import-unmatched-count").textContent = `${event.errors || 0} unmatched`;
}

function showSummary(result, replaced) {
  resultJobId = result.job_id;
  setActiveCollection(result.job_id);
  // A fresh import becomes the viewer's collection again.
  setViewerSource(null);

  const made = Array.isArray(result.collections) ? result.collections : [];
  const rows = `${result.success_count} of ${result.total_processed} rows`;
  const title = $("import-summary-title");
  if (replaced) {
    const name = (made[0] && made[0].name) || replaced;
    title.textContent = `Replaced ${name} with ${rows}`;
  } else {
    title.textContent = made.length > 1 ? `Imported ${rows} into ${made.length} collections` : `Imported ${rows}`;
  }
  const list = $("import-summary-collections");
  list.replaceChildren(...(made.length > 1
    ? made.map((c) => h("li", { text: `${c.name} · ${Number(c.rows).toLocaleString()} rows` }))
    : []));
  list.hidden = made.length < 2;
  const source = $("import-summary-source");
  source.textContent = sourceText(result.source_format);
  source.hidden = !source.textContent;
  const notice = $("import-summary-notice");
  notice.textContent = result.notice || "";
  notice.hidden = !result.notice;

  const errors = result.errors || [];
  const shown = errors.slice(0, MAX_UNMATCHED_ROWS);
  $("import-unmatched").hidden = errors.length === 0;
  $("import-unmatched").querySelector("tbody").replaceChildren(
    ...shown.map((e) => h("tr", null,
      h("td", null, e.row),
      h("td", null, e.card),
      h("td", null, REASONS[e.error] || e.error))),
  );
  const more = $("import-unmatched-more");
  const extra = errors.length - shown.length;
  more.hidden = extra <= 0;
  more.textContent = extra > 0 ? `and ${extra} more rows` : "";

  // The enhanced CSV covers the whole file, also when it became several collections.
  const download = result.download_id || result.job_id;
  $("import-download").setAttribute("href", `${API_BASE}/download/${encodeURIComponent(download)}`);
  showState("summary");
}

function handleFile(file) {
  if (busy) return;
  if (!isImportFile(file.name)) {
    showToast(WRONG_FILE, "error");
    $("file-input").value = "";
    return;
  }
  const formData = new FormData();
  formData.append("file", file);
  const replace = replaceTarget();
  if (replace) formData.append("replace", replace);
  else if ($("import-split").checked) formData.append("split_binders", "true");
  runImport(() => fetch(`${API_BASE}/process/stream`, { method: "POST", body: formData }));
}

function handlePaste() {
  if (busy) return;
  const text = $("import-paste-text").value;
  if (!text.trim()) {
    showToast("Paste a card list first.", "error");
    $("import-paste-text").focus();
    return;
  }
  const replace = replaceTarget();
  runImport(() => fetch(`${API_BASE}/process/text`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(replace ? { text, replace } : { text }),
  }));
}

/** Run one import. `request` sends it and returns the streamed response. */
async function runImport(request) {
  busy = true;
  let finished = false;
  // The name of the collection to replace, for the summary when the server gives none.
  const select = $("import-target");
  const replaced = select.value ? select.selectedOptions[0].dataset.name || "the collection" : "";
  showProgress({ current: 0, total: 0 });
  showState("progress");

  try {
    const response = await request();
    if (!response.ok) {
      let detail = "";
      try {
        const body = await response.json();
        if (body && typeof body.detail === "string") detail = body.detail;
      } catch (e) {
        // The body is not JSON: use the default text.
      }
      fail(detail);
      return;
    }

    await readSSE(response, (event) => {
      if (finished) return;
      if (event.type === "progress") {
        showProgress(event);
      } else if (event.type === "done") {
        finished = true;
        showSummary(event.result, replaced);
      } else if (event.type === "error") {
        finished = true;
        fail(event.detail);
      }
    });
    if (!finished) fail(STOPPED);
  } catch (error) {
    console.error("Import error:", error);
    // A reset after the last chunk must not wipe the summary.
    if (!finished) fail(STOPPED);
  } finally {
    busy = false;
  }
}

function init() {
  const zone = $("upload-zone");
  const input = $("file-input");

  zone.addEventListener("click", () => input.click());
  zone.addEventListener("keydown", (e) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      input.click();
    }
  });
  input.addEventListener("change", () => {
    const file = input.files && input.files[0];
    if (file) handleFile(file);
  });

  zone.addEventListener("dragover", (e) => {
    e.preventDefault();
    zone.classList.add("dragover");
  });
  zone.addEventListener("dragleave", () => zone.classList.remove("dragover"));
  zone.addEventListener("drop", (e) => {
    e.preventDefault();
    zone.classList.remove("dragover");
    const files = e.dataTransfer && e.dataTransfer.files;
    if (files && files.length > 0) handleFile(files[0]);
  });

  $("import-paste-go").addEventListener("click", handlePaste);
  $("import-target").addEventListener("change", syncTarget);
  $("import-view-collection").addEventListener("click", () => navigate("#collection"));
  $("import-another").addEventListener("click", () => resetToUpload({ clearPaste: true }));
}

/**
 * Show the screen. It keeps its state, so a running import stays on view.
 * The choice of a collection to replace is read again from the server.
 */
export function open() {
  if (!busy) loadTargets();
}

init();
