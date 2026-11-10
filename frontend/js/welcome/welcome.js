// The welcome screen: the first run of a new owner (no collection yet).
//
// Three steps light up on a path at the left. The scene at the right shows the
// current step:
//   1. the card data download, with a sigil and a progress ring;
//   2. the import of a collection export or of the sample collection, on a binder
//      page with ten card slots that light up as the rows go by; at the end,
//      real cards of the new collection flip into the slots;
//   3. the reveal: the most valuable cards fan in and the ledger counts up.
//
// The gate that sends Home and the Vault here lives in gate.js. This module
// builds its UI on the first open().
//
// Server text goes in with textContent only (h()). Card images use cardImg.

import { navigate, parseHash, redirect } from "../app/router.js";
import { formatCount, formatMoney } from "../collection/numbers.js";
import { h } from "../shared/dom.js";
import { getJSON } from "../shared/http.js";
import { isImportFile, WRONG_FILE } from "../shared/importfile.js";
import { cardImg } from "../shared/images.js";
import { DURATION, reducedMotion } from "../shared/motion.js";
import { setActiveCollection, setViewerSource, setWelcomeSkipped } from "../shared/session.js";
import { readSSE } from "../shared/sse.js";
import { showToast } from "../shared/toast.js";

const RING = 2 * Math.PI * 146; // the length of the ring (r = 146 in the SVG)
const SLOTS = 10;
const FAN = 5;
const FAN_SPOTS = [0, -1, 1, -2, 2]; // the most valuable card goes in the middle
const COUNT_MS = DURATION.slow * 2;
// The flip of the binder slots: each card starts FLIP_STEP after the one
// before and flips for DURATION.base (css/welcome.css, .welcome-slot-card).
// Ten cards end at 574 ms, inside DURATION.slow.
const FLIP_STEP = DURATION.fast * 0.24;
const flipMs = (cards) => (cards > 0 ? DURATION.base + (cards - 1) * FLIP_STEP : 0);
const STOPPED = "The import stopped. Try again.";
const UNSHOWN = "The import finished, but its summary did not show. Open the Vault to see the cards.";
const DOWNLOAD_STOPPED = "The download stopped. Try again.";
const DOWNLOAD_LABEL = "Download card data · 100 MB";
// Flavor lines of the download, one for each fifth of the percent.
const FLAVOR = [
  "Gathering every card of the Multiverse…",
  "Learning every mana cost…",
  "Sorting the rules text…",
  "Noting what each card is legal in…",
  "Almost there…",
];

const $ = (id) => document.getElementById(id);

const screen = {
  gen: 0, // bumped by each open() that starts the flow again
  step: 0,
  downloading: false,
  importing: false, // true from the start of an import until its reveal shows
  quarter: 0, // the last quarter of the import that screen readers heard
  job: null, // the job id of the new collection
};
let countFrame = 0;
let ui = null;
let endFlip = null; // ends the wait for the binder flip at once, while it runs

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
  if (n === 2) ui.binder.focus();
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

function setSigil(percent, label) {
  const p = Math.max(0, Math.min(100, Number(percent) || 0));
  ui.ring.setAttribute("stroke-dashoffset", (RING * (1 - p / 100)).toFixed(2));
  ui.sigil.setAttribute("aria-valuenow", String(Math.round(p)));
  if (label !== undefined) ui.sigilLabel.textContent = label;
}

function resetSigil() {
  setSigil(0, "Card library");
  ui.pct.textContent = "✦";
  ui.ticker.textContent = "";
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
  setSigil(0, "Downloading");
  ui.pct.textContent = "0%";
  ui.ticker.textContent = FLAVOR[0];
  holdFocus(ui.sigil);

  const fail = (message) => {
    finished = true;
    screen.downloading = false;
    showToast(message || DOWNLOAD_STOPPED, "error");
    resetSigil();
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
        setSigil(p);
        ui.pct.textContent = `${Math.round(p)}%`;
        ui.ticker.textContent = FLAVOR[Math.min(FLAVOR.length - 1, Math.floor(p / 20))];
      }
      if (data.status === "complete") {
        finished = true;
        setSigil(100, "Ready");
        ui.pct.textContent = "✓";
        const count = await cardCount();
        ui.ticker.textContent = count ? `${formatCount(count)} cards ready offline.` : "The card data is ready offline.";
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

function buildSlots() {
  ui.slots.replaceChildren(...Array.from({ length: SLOTS }, () => h("span", { class: "welcome-slot" })));
}

/** Show the binder ready for a file: no progress, dark slots. */
function resetImport() {
  ui.file.value = "";
  ui.actions.hidden = false;
  ui.progress.hidden = true;
  ui.drop.hidden = false;
  ui.binder.classList.remove("is-busy", "is-drag");
  ui.binder.setAttribute("aria-disabled", "false");
  ui.choose.disabled = false;
  ui.sample.disabled = false;
  ui.doneRow.hidden = true;
  ui.announce.textContent = "";
  buildSlots();
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
  // The slots light up as the rows go by. Cards do not show here: the stream
  // does not name the imported cards.
  const lit = Math.floor(share * SLOTS);
  [...ui.slots.children].forEach((slot, i) => slot.classList.toggle("is-lit", i < lit));
  const quarter = Math.floor(share * 4);
  if (quarter > screen.quarter && quarter < 4) {
    screen.quarter = quarter;
    announce(`Import ${quarter * 25}% done.`);
  }
}

function startProgress() {
  ui.actions.hidden = true;
  ui.drop.hidden = true;
  ui.progress.hidden = false;
  ui.binder.classList.add("is-busy");
  ui.binder.setAttribute("aria-disabled", "true");
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
  // The progress region that had the focus hid: the binder takes it back.
  if (lost && onView()) ui.binder.focus();
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
          // The collection exists, but the reveal failed: say so, and go back to step 2.
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

// Up to n cards with different names, in the order of the list.
function uniqueCards(list, n) {
  const names = new Set();
  const out = [];
  for (const card of list || []) {
    if (out.length === n) break;
    const name = card && String(card.name || "");
    if (!card || !card.scryfall_id || names.has(name)) continue;
    names.add(name);
    out.push(card);
  }
  return out;
}

async function load(path) {
  try {
    return await getJSON(path);
  } catch (error) {
    return null;
  }
}

/** Put real cards of the new collection in the slots, with a flip stagger. */
function fillSlots(cards) {
  [...ui.slots.children].forEach((slot, i) => {
    // Every row is read: each slot is lit. A slot without a card stays empty.
    slot.classList.add("is-lit");
    const card = cards[i];
    if (!card) {
      slot.replaceChildren();
      return;
    }
    const face = h("span", { class: "welcome-slot-card" }, cardImg(card, { size: "small" }));
    face.style.setProperty("--i", String(i));
    slot.replaceChildren(face);
  });
}

/**
 * Remember the new collection and read its shelves and insights. Real cards
 * flip into the binder, and "Open the Vault →" shows under it at once, so
 * nothing waits on the flip. When the flip ends, the reveal (step 3) shows.
 * Without shelves, or under reduced motion, the reveal shows at once.
 */
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

    const base = job ? `/collection/${encodeURIComponent(job)}` : null;
    const [shelves, insights] = base
      ? await Promise.all([load(`${base}/shelves`), load(`${base}/insights`)])
      : [null, null];
    const still = reducedMotion();
    ui.view.classList.toggle("is-still", still);
    const picks = uniqueCards(shelves && shelves.valuable, SLOTS);
    if (picks.length) {
      fillSlots(picks);
      if (!still) {
        ui.doneRow.hidden = false;
        holdFocus(ui.done);
        await new Promise((resolve) => {
          const timer = setTimeout(resolve, flipMs(picks.length));
          endFlip = () => {
            clearTimeout(timer);
            resolve();
          };
        });
        endFlip = null;
      }
    }
    screen.importing = false;
    reveal(insights, shelves);
  } finally {
    screen.importing = false;
  }
}

// ---- step 3: the reveal ----------------------------------------------------

function countUp(items) {
  if (countFrame) cancelAnimationFrame(countFrame);
  countFrame = 0;
  const finish = () => items.forEach((item) => { item.el.textContent = item.format(item.to); });
  if (reducedMotion() || typeof requestAnimationFrame !== "function") {
    finish();
    return;
  }
  const start = performance.now();
  items.forEach((item) => { item.el.textContent = item.format(0); });
  const step = () => {
    const t = Math.min(1, (performance.now() - start) / COUNT_MS);
    if (t >= 1) {
      countFrame = 0;
      finish();
      return;
    }
    const eased = 1 - (1 - t) ** 4;
    items.forEach((item) => { item.el.textContent = item.format(item.to * eased); });
    countFrame = requestAnimationFrame(step);
  };
  countFrame = requestAnimationFrame(step);
}

function renderFan(cards) {
  ui.fan.replaceChildren(...cards.map((card, i) => {
    const k = FAN_SPOTS[i];
    const li = h("li", { class: `welcome-fan-card${Math.abs(k) === 2 ? " is-outer" : ""}` },
      cardImg(card, { className: "welcome-fan-img", alt: String(card.name || ""), priority: "high" }));
    li.style.setProperty("--k", String(k));
    li.style.setProperty("--ak", String(Math.abs(k)));
    li.style.setProperty("--i", String(i));
    return li;
  }));
  ui.fan.hidden = cards.length === 0;
}

function ledgerItem(key, label, gold) {
  const value = h("span", { class: "welcome-ledger-value", "aria-hidden": "true" });
  const spoken = h("span", { class: "welcome-sr" });
  const el = h("div", { class: `welcome-ledger-item${gold ? " is-gold" : ""}`, "data-key": key },
    value, spoken, h("span", { class: "welcome-ledger-label", text: label }));
  return { el, value, spoken };
}

function renderLedger(insights) {
  if (!insights) {
    ui.ledger.replaceChildren();
    ui.ledger.hidden = true;
    return;
  }
  const rarity = insights.rarity || {};
  const rows = [
    ["value", "Estimated value", Number(insights.value) || 0, formatMoney, true],
    ["cards", "Cards", Number(insights.cards) || 0, formatCount, false],
    ["rares", "Rares & mythics", (Number(rarity.rare) || 0) + (Number(rarity.mythic) || 0), formatCount, false],
  ];
  const items = rows.map(([key, label, to, format, gold]) => {
    const item = ledgerItem(key, label, gold);
    // Screen readers get the final value, not the count.
    item.spoken.textContent = format(to);
    return { ...item, to, format };
  });
  ui.ledger.replaceChildren(...items.map((item) => item.el));
  ui.ledger.hidden = false;
  countUp(items.map(({ value, to, format }) => ({ el: value, to, format })));
}

function reveal(insights, shelves) {
  const fan = uniqueCards(shelves && shelves.valuable, FAN);
  const count = insights ? Number(insights.cards) || 0 : 0;
  ui.revealSub.textContent = insights
    ? `${formatCount(count)} ${count === 1 ? "card" : "cards"} found their place.${fan.length ? " Here are your crown jewels." : ""}`
    : "Your cards are in the Vault.";
  renderFan(fan);
  // The step shows first, so the fan and the counters start in view.
  showStep(3, { focus: true });
  renderLedger(insights);
}

function openVault() {
  // The owner leaves during the flip: the flow ends now, not after the flip.
  if (endFlip) endFlip();
  if (screen.job) {
    setActiveCollection(screen.job);
    setViewerSource(null);
  }
  navigate("#collection");
}

// ---- entry -----------------------------------------------------------------

function onBinderKey(event) {
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
    sigil: $("welcome-sigil"),
    ring: $("welcome-ring"),
    pct: $("welcome-pct"),
    sigilLabel: $("welcome-sigil-label"),
    ticker: $("welcome-ticker"),
    downloadBtn: $("welcome-download-btn"),
    file: $("welcome-file"),
    binder: $("welcome-binder"),
    slots: $("welcome-slots"),
    drop: $("welcome-drop"),
    actions: $("welcome-actions"),
    choose: $("welcome-choose"),
    sample: $("welcome-sample"),
    progress: $("welcome-progress"),
    progressFill: $("welcome-progress-fill"),
    track: document.querySelector("#welcome-progress .welcome-track"),
    row: $("welcome-row"),
    card: $("welcome-card"),
    announce: $("welcome-announce"),
    doneRow: $("welcome-done-row"),
    done: $("welcome-done"),
    revealTitle: $("welcome-reveal-title"),
    revealSub: $("welcome-reveal-sub"),
    fan: $("welcome-fan"),
    ledger: $("welcome-ledger"),
    open: $("welcome-open"),
  };
  buildSlots();

  ui.skip.addEventListener("click", skip);
  ui.downloadBtn.addEventListener("click", download);
  ui.binder.addEventListener("click", chooseFile);
  ui.binder.addEventListener("keydown", onBinderKey);
  ui.choose.addEventListener("click", chooseFile);
  ui.sample.addEventListener("click", importSample);
  ui.file.addEventListener("change", () => {
    const file = ui.file.files && ui.file.files[0];
    if (file) importFile(file);
  });
  ui.binder.addEventListener("dragover", (event) => {
    event.preventDefault();
    if (!screen.importing) ui.binder.classList.add("is-drag");
  });
  ui.binder.addEventListener("dragleave", () => ui.binder.classList.remove("is-drag"));
  ui.binder.addEventListener("drop", (event) => {
    event.preventDefault();
    ui.binder.classList.remove("is-drag");
    const files = event.dataTransfer && event.dataTransfer.files;
    if (files && files.length > 0) importFile(files[0]);
  });
  ui.open.addEventListener("click", openVault);
  ui.done.addEventListener("click", openVault);
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
  ui.view.classList.toggle("is-still", reducedMotion());
  if (screen.downloading || screen.importing) return;
  const gen = ++screen.gen;
  screen.job = null;
  screen.step = 0;
  ui.view.dataset.step = "0";
  ui.view.querySelectorAll(".welcome-panel").forEach((panel) => { panel.hidden = true; });
  syncSkip();
  resetSigil();
  resetImport();
  const [ready, collections] = await Promise.all([cardDataReady(), collectionList()]);
  if (gen !== screen.gen) return;
  if (collections && collections.length > 0) {
    if (parseHash(location.hash).screen === "welcome") redirect("#home");
    return;
  }
  showStep(ready ? 2 : 1);
}
