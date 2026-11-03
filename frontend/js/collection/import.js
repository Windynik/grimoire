// Import screen: upload a ManaBox CSV, show live progress, then show a summary.
//
// One of three states shows at a time: upload, progress, or summary.

import { navigate } from "../app/router.js";
import { h } from "../shared/dom.js";
import { readSSE } from "../shared/sse.js";
import { setActiveCollection, setViewerSource } from "../shared/session.js";
import { showToast } from "../shared/toast.js";

const API_BASE = "/api";
const MAX_UNMATCHED_ROWS = 100;
const STOPPED = "The import stopped. Try again.";
const REASONS = {
  not_found: "Not in the card data",
  missing_scryfall_id: "No Scryfall ID",
};

const $ = (id) => document.getElementById(id);

let busy = false; // an import is running
let resultJobId = null; // the job of the summary on view

/** Show one state: "upload", "progress" or "summary". */
function showState(name) {
  $("import-upload").hidden = name !== "upload";
  $("import-progress").hidden = name !== "progress";
  $("import-summary").hidden = name !== "summary";
}

function resetToUpload() {
  $("file-input").value = "";
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
  $("import-row-text").textContent = `Row ${current} of ${total}`;
  $("import-card-name").textContent = event.current_card || " ";
  $("import-unmatched-count").textContent = `${event.errors || 0} unmatched`;
}

function showSummary(result) {
  resultJobId = result.job_id;
  setActiveCollection(result.job_id);
  // A fresh import becomes the viewer's collection again.
  setViewerSource(null);

  $("import-summary-title").textContent =
    `Imported ${result.success_count} of ${result.total_processed} rows`;

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

  $("import-download").setAttribute("href", `${API_BASE}/download/${encodeURIComponent(result.job_id)}`);
  showState("summary");
}

async function handleFile(file) {
  if (busy) return;
  if (!file.name.toLowerCase().endsWith(".csv")) {
    showToast("Choose a CSV file.", "error");
    $("file-input").value = "";
    return;
  }

  busy = true;
  showProgress({ current: 0, total: 0 });
  showState("progress");

  const formData = new FormData();
  formData.append("file", file);

  try {
    const response = await fetch(`${API_BASE}/process/stream`, { method: "POST", body: formData });
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

    let finished = false;
    await readSSE(response, (event) => {
      if (finished) return;
      if (event.type === "progress") {
        showProgress(event);
      } else if (event.type === "done") {
        finished = true;
        showSummary(event.result);
      } else if (event.type === "error") {
        finished = true;
        fail(event.detail);
      }
    });
    if (!finished) fail(STOPPED);
  } catch (error) {
    console.error("Import error:", error);
    fail(STOPPED);
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

  $("import-view-collection").addEventListener("click", () => navigate("#collection"));
  $("import-another").addEventListener("click", resetToUpload);
}

/** Show the screen. It keeps its state, so a running import stays on view. */
export function open() {}

init();
