// The welcome screen: the first run of a new owner (no collection yet).
//
// Three steps light up on a path at the left. The scene at the right shows the
// current step:
//   1. the card data download, with a progress bar and a status line;
//   2. the import of a collection export or of the sample collection, with a
//      drop box and a progress bar;
//   3. the summary: the numbers of the new collection.
//
// The gate that sends Home and the collection screen here lives in gate.js.
// This module builds its UI on the first open().
//
// Server text goes in with textContent only (h()).

import { navigate, parseHash, redirect } from "../app/router.js";
import { formatCount, formatMoney } from "../collection/numbers.js";
import { h } from "../shared/dom.js";
import { getJSON } from "../shared/http.js";
import { isImportFile, WRONG_FILE } from "../shared/importfile.js";
import { setActiveCollection, setViewerSource, setWelcomeSkipped } from "../shared/session.js";
import { readSSE } from "../shared/sse.js";
import { showToast } from "../shared/toast.js";

const STOPPED = "The import stopped. Try again.";
const UNSHOWN = "The import finished, but its summary did not show. Open the collection to see the cards.";
const DOWNLOAD_STOPPED = "The download stopped. Try again.";
const DOWNLOAD_LABEL = "Download card data (about 100 MB)";

const $ = (id) => document.getElementById(id);

const screen = {
  gen: 0, // bumped by each open() that starts the flow again
  step: 0,
  downloading: false,
  importing: false, // true from the start of an import until its reveal shows
  quarter: 0, // the last quarter of the import that screen readers heard
  job: null, // the job id of the new collection
};
let ui = null;

// ---- the path and the panels -----------------------------------------------

function focusInside() {
  const el = document.activeElement;
  return !el || el === document.body || ui.view.contains(el);
}

function onView() {
  return ui.view.classList.contains("active");
}

/** Show step n (1, 2 or 3): light the path and show the scene of that step. */
function showStep(n, { focus = false } = {}) {
  screen.step = n;
  ui.view.dataset.step = String(n);
  ui.view.querySelectorAll(".welcome-step").forEach((li) => {
    const k = Number(li.dataset.step);
    li.classList.toggle("is-on", k === n);
    li.classList.toggle("is-done", k < n);
    if (k === n) li.setAttribute("aria-current", "step");
    else li.removeAttribute("aria-current");
    li.querySelector(".welcome-step-n").textContent = k < n ? "✓" : String(k);
  });
  ui.fill.style.transform = `scaleY(${Math.max(0, n - 1) / 2})`;
  ui.view.querySelectorAll(".welcome-panel").forEach((panel) => {
    panel.hidden = Number(panel.dataset.panel) !== n;
  });
  syncSkip();
  if (!focus || !onView() || !focusInside()) return;
  // The control of the old step is gone: the focus moves to the new step.
  if (n === 2) ui.dropzone.focus();
  if (n === 3) ui.revealTitle.focus();
}

// Skip shows on steps 1 and 2 while no stream runs. Without card data the
// archive opens anyway and says that the card data is not on this Mac yet.
function syncSkip() {
  ui.skip.hidden = screen.downloading || screen.importing || screen.step === 3;
}

function skip() {
  setWelcomeSkipped(true);
  setViewerSource("archive");
  navigate("#collection");
}

// Move the focus to a progress region when the control that had it hides.
function holdFocus(el) {
  if (onView() && focusInside()) el.focus();
}

// ---- step 1: the card data -------------------------------------------------

function setMeter(percent) {
  const p = Math.max(0, Math.min(100, Number(percent) || 0));
  ui.meterFill.style.transform = `scaleX(${p / 100})`;
  ui.meter.setAttribute("aria-valuenow", String(Math.round(p)));
}

function resetDownload() {
  setMeter(0);
  ui.status.textContent = "";
  ui.downloadBtn.disabled = false;
  ui.downloadBtn.textContent = DOWNLOAD_LABEL;
}

async function cardCount() {
  try {
    const status = await getJSON("/cache/status");
    return Number(status && status.card_count) || 0;
  } catch (error) {
    return 0;
  }
}

async function download() {
  if (screen.downloading) return;
  screen.downloading = true;
  syncSkip();
  const gen = screen.gen;
  let finished = false;
  ui.downloadBtn.disabled = true;
  ui.downloadBtn.textContent = "Downloading…";
  setMeter(0);
  ui.status.textContent = "Downloading card data: 0%";
  holdFocus(ui.meter);

  const fail = (message) => {
    finished = true;
    screen.downloading = false;
    showToast(message || DOWNLOAD_STOPPED, "error");
    resetDownload();
    // The toast goes away. The reason stays until the next try.
    ui.status.textContent = message || DOWNLOAD_STOPPED;
    syncSkip();
  };

  try {
    const response = await fetch("/api/cache/download", { method: "POST" });
    if (!response.ok) {
      fail(DOWNLOAD_STOPPED);
      return;
    }
    await readSSE(response, async (data) => {
      if (finished) return;
      if (data.error) {
        fail(String(data.error));
        return;
      }
      if (data.percentage !== undefined) {
        const p = Math.max(0, Math.min(100, Number(data.percentage) || 0));
        setMeter(p);
        ui.status.textContent = `Downloading card data: ${Math.round(p)}%`;
      }
      if (data.status === "complete") {
        finished = true;
        setMeter(100);
        const count = await cardCount();
        ui.status.textContent = count ? `${formatCount(count)} cards ready offline.` : "The card data is ready offline.";
        ui.downloadBtn.textContent = "Card data ready";
        screen.downloading = false;
        if (gen === screen.gen) showStep(2, { focus: true });
      }
    });
    if (!finished) fail(DOWNLOAD_STOPPED);
  } catch (error) {
    if (!finished) fail(DOWNLOAD_STOPPED);
  } finally {
    screen.downloading = false;
    syncSkip();
  }
}

// ---- step 2: the import ----------------------------------------------------

/** Show the drop box ready for a file, with no progress. */
function resetImport() {
  ui.file.value = "";
  ui.actions.hidden = false;
  ui.progress.hidden = true;
  ui.dropzone.hidden = false;
  ui.dropzone.classList.remove("is-drag");
  ui.choose.disabled = false;
  ui.sample.disabled = false;
  ui.announce.textContent = "";
  syncSkip();
}

// Screen readers hear the start, each quarter, and the end of the import,
// not each row.
function announce(text) {
  ui.announce.textContent = text;
}

function showProgress(event) {
  const total = Number(event.total) || 0;
  const current = Number(event.current) || 0;
  const share = total > 0 ? Math.min(1, current / total) : 0;
  ui.progressFill.style.transform = `scaleX(${share})`;
  ui.track.setAttribute("aria-valuenow", String(Math.round(share * 100)));
  // The server loads the card index first, so the total is 0 for a few seconds.
  ui.row.textContent = total > 0 ? `Row ${formatCount(current)} of ${formatCount(total)}` : "Reading the card data…";
  ui.card.textContent = event.current_card ? String(event.current_card) : "";
  const quarter = Math.floor(share * 4);
  if (quarter > screen.quarter && quarter < 4) {
    screen.quarter = quarter;
    announce(`Import ${quarter * 25}% done.`);
  }
}

function startProgress() {
  ui.actions.hidden = true;
  ui.dropzone.hidden = true;
  ui.progress.hidden = false;
  ui.choose.disabled = true;
  ui.sample.disabled = true;
  screen.quarter = 0;
  showProgress({ current: 0, total: 0 });
  announce("Import started.");
  syncSkip();
  holdFocus(ui.progress);
}

function failImport(message) {
  screen.importing = false;
  const lost = screen.step === 2 && focusInside();
  showToast(message || STOPPED, "error");
  resetImport();
  // The progress region that had the focus hid: the drop box takes it back.
  if (lost && onView()) ui.dropzone.focus();
}

async function runImport(request) {
  if (screen.importing) return;
  screen.importing = true;
  let finished = false;
  startProgress();
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
      failImport(detail);
      return;
    }
    await readSSE(response, async (event) => {
      if (finished) return;
      if (event.type === "progress") {
        showProgress(event);
      } else if (event.type === "done") {
        finished = true;
        try {
          await finishImport(event.result || {});
        } catch (error) {
          // The collection exists, but the summary failed: say so, and go back to step 2.
          failImport(UNSHOWN);
        }
      } else if (event.type === "error") {
        finished = true;
        failImport(event.detail);
      }
    });
    if (!finished) failImport(STOPPED);
  } catch (error) {
    // A reset after the last chunk must not undo a finished import.
    if (!finished) failImport(STOPPED);
  }
}

function importFile(file) {
  if (!file || screen.importing) return;
  if (!isImportFile(file.name)) {
    showToast(WRONG_FILE, "error");
    ui.file.value = "";
    return;
  }
  const form = new FormData();
  form.append("file", file);
  runImport(() => fetch("/api/process/stream", { method: "POST", body: form }));
}

function importSample() {
  runImport(() => fetch("/api/process/sample", { method: "POST" }));
}

function chooseFile() {
  if (screen.importing) return;
  ui.file.click();
}

async function load(path) {
  try {
    return await getJSON(path);
  } catch (error) {
    return null;
  }
}

/** Remember the new collection, read its numbers, and show the summary (step 3). */
async function finishImport(result) {
  try {
    const job = result.job_id ? String(result.job_id) : null;
    screen.job = job;
    if (job) {
      setActiveCollection(job);
      // A fresh import becomes the viewer's collection.
      setViewerSource(null);
      setWelcomeSkipped(false);
    }
    const total = Number(result.total_processed) || 0;
    const matched = Number(result.success_count) || 0;
    ui.progressFill.style.transform = "scaleX(1)";
    ui.track.setAttribute("aria-valuenow", "100");
    ui.row.textContent = `${formatCount(matched)} of ${formatCount(total)} rows matched`;
    ui.card.textContent = total > matched ? `${formatCount(total - matched)} to check` : "";
    announce(`Import done: ${formatCount(matched)} of ${formatCount(total)} rows matched.`);
    const insights = job ? await load(`/collection/${encodeURIComponent(job)}/insights`) : null;
    screen.importing = false;
    showSummary(insights);
  } finally {
    screen.importing = false;
  }
}

// ---- step 3: the summary ---------------------------------------------------

function ledgerItem(key, label, text, gold) {
  return h("div", { class: `welcome-ledger-item${gold ? " is-gold" : ""}`, "data-key": key },
    h("span", { class: "welcome-ledger-value", text }),
    h("span", { class: "welcome-ledger-label", text: label }));
}

function renderLedger(insights) {
  if (!insights) {
    ui.ledger.replaceChildren();
    ui.ledger.hidden = true;
    return;
  }
  const rarity = insights.rarity || {};
  const rares = (Number(rarity.rare) || 0) + (Number(rarity.mythic) || 0);
  ui.ledger.replaceChildren(
    ledgerItem("value", "Estimated value", formatMoney(Number(insights.value) || 0), true),
    ledgerItem("cards", "Cards", formatCount(Number(insights.cards) || 0), false),
    ledgerItem("rares", "Rares & mythics", formatCount(rares), false));
  ui.ledger.hidden = false;
}

function showSummary(insights) {
  const count = insights ? Number(insights.cards) || 0 : 0;
  ui.revealSub.textContent = insights
    ? `Imported ${formatCount(count)} ${count === 1 ? "card" : "cards"}.`
    : "The cards are in your collection.";
  renderLedger(insights);
  showStep(3, { focus: true });
}

function openCollection() {
  if (screen.job) {
    setActiveCollection(screen.job);
    setViewerSource(null);
  }
  navigate("#collection");
}

// ---- entry -----------------------------------------------------------------

function onDropzoneKey(event) {
  if (event.key !== "Enter" && event.key !== " ") return;
  event.preventDefault();
  chooseFile();
}

function init() {
  if (ui) return;
  ui = {
    view: $("welcome-view"),
    skip: $("welcome-skip"),
    fill: $("welcome-path-fill"),
    meter: $("welcome-meter"),
    meterFill: $("welcome-meter-fill"),
    status: $("welcome-status"),
    downloadBtn: $("welcome-download-btn"),
    file: $("welcome-file"),
    dropzone: $("welcome-dropzone"),
    actions: $("welcome-actions"),
    choose: $("welcome-choose"),
    sample: $("welcome-sample"),
    progress: $("welcome-progress"),
    progressFill: $("welcome-progress-fill"),
    track: document.querySelector("#welcome-progress .welcome-track"),
    row: $("welcome-row"),
    card: $("welcome-card"),
    announce: $("welcome-announce"),
    revealTitle: $("welcome-reveal-title"),
    revealSub: $("welcome-reveal-sub"),
    ledger: $("welcome-ledger"),
    open: $("welcome-open"),
  };

  ui.skip.addEventListener("click", skip);
  ui.downloadBtn.addEventListener("click", download);
  ui.dropzone.addEventListener("click", chooseFile);
  ui.dropzone.addEventListener("keydown", onDropzoneKey);
  ui.choose.addEventListener("click", chooseFile);
  ui.sample.addEventListener("click", importSample);
  ui.file.addEventListener("change", () => {
    const file = ui.file.files && ui.file.files[0];
    if (file) importFile(file);
  });
  ui.dropzone.addEventListener("dragover", (event) => {
    event.preventDefault();
    if (!screen.importing) ui.dropzone.classList.add("is-drag");
  });
  ui.dropzone.addEventListener("dragleave", () => ui.dropzone.classList.remove("is-drag"));
  ui.dropzone.addEventListener("drop", (event) => {
    event.preventDefault();
    ui.dropzone.classList.remove("is-drag");
    const files = event.dataTransfer && event.dataTransfer.files;
    if (files && files.length > 0) importFile(files[0]);
  });
  ui.open.addEventListener("click", openCollection);
}

async function cardDataReady() {
  try {
    const status = await getJSON("/cache/status");
    return Boolean(status && status.status === "ready");
  } catch (error) {
    showToast("Could not check the card data.", "error");
    return false;
  }
}

/** The collection list, or null when it did not load. */
async function collectionList() {
  try {
    const data = await getJSON("/collections");
    return Array.isArray(data && data.collections) ? data.collections : null;
  } catch (error) {
    return null;
  }
}

/**
 * Show the screen. A running download or import keeps its place. With a
 * collection, Home opens instead (in place of this history entry). Else the
 * flow starts again: step 2 when the card data is ready, else step 1.
 */
export async function open() {
  init();
  if (screen.downloading || screen.importing) return;
  const gen = ++screen.gen;
  screen.job = null;
  screen.step = 0;
  ui.view.dataset.step = "0";
  ui.view.querySelectorAll(".welcome-panel").forEach((panel) => { panel.hidden = true; });
  syncSkip();
  resetDownload();
  resetImport();
  const [ready, collections] = await Promise.all([cardDataReady(), collectionList()]);
  if (gen !== screen.gen) return;
  if (collections && collections.length > 0) {
    if (parseHash(location.hash).screen === "welcome") redirect("#home");
    return;
  }
  showStep(ready ? 2 : 1);
}
