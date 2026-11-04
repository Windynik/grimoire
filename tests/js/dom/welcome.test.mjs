// The first-run welcome flow: the gate, Skip, the download, the import, and the reveal.
import { test, before } from "node:test";
import assert from "node:assert/strict";
import { loadApp } from "./harness.mjs";

const ID = (i) => `00000000-0000-4000-8000-${String(i).padStart(12, "0")}`;
const READY = { status: "ready", card_count: 30000, file_size_mb: 120.5, download_date: "2026-11-01T10:00:00" };
const MISSING = { status: "missing" };
const BOX = { job_id: "job1", name: "Test box", card_count: 3, created: null };
const NEW_BOX = { job_id: "job9", name: "Sample collection", card_count: 1002, created: null };
const RING = 2 * Math.PI * 146;

function card(i, over = {}) {
  return {
    scryfall_id: ID(i), name: `Card ${i}`, mana_cost: "{1}{U}", type_line: "Creature — Wizard",
    rarity: "rare", set: "neo", image_url: `https://example.test/${i}.jpg`, back_image_url: "",
    quantity: 1, foil: false, price: 100 - i, value: 100 - i, owned: true, new: false, ...over,
  };
}

// Twelve valuable cards, highest price first. Card 2 has the name of card 1
// (a foil printing), so the unique names skip it.
const VALUABLE = Array.from({ length: 12 }, (_, i) => card(i + 1, i === 1 ? { name: "Card 1", foil: true } : {}));
const SHELVES = { spotlight: card(50, { name: "Spot" }), valuable: VALUABLE, foils: [], new: [] };
const INSIGHTS = {
  value: 1234.5, cards: 1002, unique: 851, rarity: { common: 500, uncommon: 300, rare: 160, mythic: 42 },
  foils: 37, colors: {}, curve: {}, sets: 64, name: "Sample collection", created: null,
  card_data_date: null, has_previous: false,
};

let app;
let document;
let window;
let navigate;

before(async () => {
  app = await loadApp({});
  document = app.document;
  window = app.window;
  ({ navigate } = await import("../../../frontend/js/app/router.js"));
});

const encoder = new TextEncoder();
const sse = (event) => encoder.encode(`data: ${JSON.stringify(event)}\n\n`);

// A stream the test feeds by hand. send() adds an event; end() closes it.
function openStream() {
  let controller;
  const body = new ReadableStream({ start(c) { controller = c; } });
  return {
    reply: () => ({ status: 200, body, headers: { "content-type": "text/event-stream" } }),
    send: (event) => controller.enqueue(sse(event)),
    end: () => controller.close(),
  };
}

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];
const text = (selector) => ($(selector)?.textContent || "").trim();
const shown = (selector) => {
  const el = $(selector);
  return Boolean(el) && !el.hidden && !el.closest("[hidden]");
};
const active = (screen) => document.getElementById(`${screen}-view`).classList.contains("active");
const toasts = () => $$("#toast-container .toast").map((t) => t.textContent);
const posts = (path) => app.fetchLog.filter((r) => r.method === "POST" && r.path === path);
const progress = (current, total, name, errors = 0) => ({
  type: "progress", current, total, current_card: name, errors,
});
const done = (total = 25, errors = 0) => ({
  type: "done",
  result: {
    job_id: "job9", status: "complete", total_processed: total,
    success_count: total - errors, error_count: errors, errors: [],
  },
});

/**
 * Reset the storage, the toasts and the stubs. With open, show the welcome
 * screen and wait until its first step shows.
 */
async function setup({
  status = READY, collections = [], storage = {}, open = true, shelves = SHELVES, insights = INSIGHTS,
} = {}) {
  window.localStorage.clear();
  window.sessionStorage.clear();
  for (const [key, value] of Object.entries(storage)) window.localStorage.setItem(key, value);
  $("#toast-container").replaceChildren();
  let list = collections.slice();
  app.route("GET /api/cache/status", () => ({ json: status }));
  app.route("GET /api/collections", () => ({ json: { collections: list } }));
  app.route("GET /api/decks", () => ({ json: { decks: [] } }));
  app.route("GET /api/forge/formats", () => ({ json: { formats: [] } }));
  app.route("GET /api/cards/search", () => ({ json: { cards: [card(70)], total: 1 } }));
  for (const job of ["job1", "job9"]) {
    app.route(`GET /api/collection/${job}/search`, () => ({
      json: { cards: [card(80)], total: 1, offset: 0, limit: 60, facets: {}, value: 0 },
    }));
    app.route(`GET /api/collection/${job}/insights`, () => (insights ? { json: insights } : { status: 500, json: { detail: "down" } }));
    app.route(`GET /api/collection/${job}/shelves`, () => (shelves ? { json: shelves } : { status: 500, json: { detail: "down" } }));
  }
  app.fetchLog.length = 0;
  if (open) {
    await go("#welcome");
    await app.until(() => $("#welcome-view").dataset.step !== "0");
  }
  return { addCollection: (c) => list.push(c) };
}

// Go to a hash, or run its route again when it shows already.
async function go(hash) {
  if (window.location.hash === hash) await navigate(hash);
  else window.location.hash = hash;
  const screen = hash.replace("#", "");
  await app.until(() => active(screen));
}

// Choose a file with the file input.
function choose(name) {
  const input = $("#welcome-file");
  const file = new window.File(["Name,Quantity\nSol Ring,1\n"], name, { type: "text/csv" });
  Object.defineProperty(input, "files", { value: [file], configurable: true });
  input.dispatchEvent(new window.Event("change", { bubbles: true }));
}

// Run an import with the sample button to its reveal.
async function importSample(stream) {
  app.route("POST /api/process/sample", () => stream.reply());
  $("#welcome-sample").click();
  await app.until(() => posts("/api/process/sample").length === 1);
  stream.send(progress(1002, 1002, "Last Card"));
  stream.send(done(1002));
  stream.end();
}

// ---- the gate --------------------------------------------------------------

test("Home goes to the welcome screen when there is no collection", async () => {
  await setup({ open: false });
  await go("#settings");
  const length = window.history.length;
  window.location.hash = "#home";
  await app.until(() => active("welcome") && window.location.hash === "#welcome");
  // The welcome screen takes the place of #home: Back does not loop to the gate.
  assert.equal(window.history.length, length + 1);
  assert.equal($('.nav-item[aria-current="page"]').dataset.screen, "home");
  assert.ok(!active("home"));
});

test("the Vault goes to the welcome screen when there is no collection", async () => {
  await setup({ open: false });
  await go("#settings");
  const length = window.history.length;
  window.location.hash = "#collection";
  await app.until(() => active("welcome") && window.location.hash === "#welcome");
  assert.equal(window.history.length, length + 1);
});

test("a collection keeps Home and the Vault, and forgets an old skip", async () => {
  await setup({ open: false, collections: [BOX], storage: { welcomeSkipped: "1" } });
  await go("#home");
  await app.until(() => $(".collection-row"));
  await app.settle();
  assert.equal(window.location.hash, "#home");
  assert.ok(active("home"));
  assert.equal(window.localStorage.getItem("welcomeSkipped"), null);

  await go("#collection");
  await app.until(() => $("#collection-view").dataset.vault === "ready");
  await app.settle();
  assert.equal(window.location.hash, "#collection");
  assert.ok(active("collection"));
});

// ---- Skip ------------------------------------------------------------------

test("Skip opens the archive, and the gate lets it stay", async () => {
  await setup();
  const skip = $("#welcome-skip");
  assert.ok(shown("#welcome-skip"));
  assert.match(skip.textContent, /Skip — just browse all cards/);
  skip.click();
  await app.until(() => window.location.hash === "#collection" && active("collection"));
  await app.until(() => $("#collection-view").dataset.vault === "ready");
  await app.settle();
  assert.equal(window.location.hash, "#collection");
  assert.equal(window.localStorage.getItem("viewerSource"), "archive");
  assert.equal(window.localStorage.getItem("welcomeSkipped"), "1");
  assert.ok(app.fetchLog.some((r) => r.path === "/api/cards/search"));

  await go("#home");
  await app.until(() => /No collections yet/.test(text("#dashboard-collections")));
  await app.settle();
  assert.equal(window.location.hash, "#home");
});

// ---- step 1: the card data -------------------------------------------------

test("ready card data skips step 1", async () => {
  await setup();
  assert.equal($("#welcome-view").dataset.step, "2");
  assert.ok(shown("#welcome-import"));
  assert.ok(!shown("#welcome-download"));
  assert.ok(!shown("#welcome-reveal"));
  const steps = $$(".welcome-step");
  assert.ok(steps[0].classList.contains("is-done"));
  assert.ok(steps[1].classList.contains("is-on"));
  assert.equal(steps[1].getAttribute("aria-current"), "step");
  assert.equal(text(".welcome-step[data-step='1'] .welcome-step-n"), "✓");
  assert.ok(!app.fetchLog.some((r) => r.path === "/api/cache/download"));
});

test("step 1 downloads the card data with the sigil ring, then step 2 shows", async () => {
  await setup({ status: MISSING });
  assert.equal($("#welcome-view").dataset.step, "1");
  assert.ok(shown("#welcome-download"));
  assert.ok(!shown("#welcome-skip"), "Skip waits for the card data");
  assert.equal(text("#welcome-download-btn"), "Download card data · 100 MB");

  const stream = openStream();
  app.route("POST /api/cache/download", () => stream.reply());
  $("#welcome-download-btn").click();
  await app.until(() => posts("/api/cache/download").length === 1);
  assert.ok($("#welcome-download-btn").disabled);

  stream.send({ percentage: 5 });
  await app.until(() => text("#welcome-pct") === "5%");
  const early = text("#welcome-ticker");
  assert.ok(early.length > 0);
  stream.send({ percentage: 40 });
  await app.until(() => text("#welcome-pct") === "40%");
  const ring = $("#welcome-ring");
  assert.equal(Number(ring.getAttribute("stroke-dashoffset")).toFixed(1), (RING * 0.6).toFixed(1));
  assert.equal($("#welcome-sigil").getAttribute("aria-valuenow"), "40");
  stream.send({ percentage: 90 });
  await app.until(() => text("#welcome-pct") === "90%");
  assert.notEqual(text("#welcome-ticker"), early, "the flavor line changes with the percent");

  app.route("GET /api/cache/status", () => ({ json: READY }));
  stream.send({ percentage: 100, status: "complete" });
  stream.end();
  await app.until(() => $("#welcome-view").dataset.step === "2");
  assert.ok(shown("#welcome-import"));
  assert.ok(shown("#welcome-skip"));
  assert.ok($(".welcome-step[data-step='1']").classList.contains("is-done"));
});

test("a failed download stays on step 1 with a toast", async () => {
  await setup({ status: MISSING });
  const stream = openStream();
  app.route("POST /api/cache/download", () => stream.reply());
  $("#welcome-download-btn").click();
  stream.send({ percentage: 12 });
  stream.send({ error: "Download failed" });
  stream.end();
  await app.until(() => toasts().includes("Download failed"));
  await app.until(() => !$("#welcome-download-btn").disabled);
  assert.equal($("#welcome-view").dataset.step, "1");
  assert.ok(!shown("#welcome-skip"));
});

// ---- step 2: the import ----------------------------------------------------

test("the binder opens the file chooser with a click, Enter and Space", async () => {
  await setup();
  const input = $("#welcome-file");
  let clicks = 0;
  input.click = () => { clicks += 1; };
  try {
    $("#welcome-binder").click();
    for (const key of ["Enter", " "]) {
      $("#welcome-binder").dispatchEvent(new window.KeyboardEvent("keydown", { key, bubbles: true, cancelable: true }));
    }
    $("#welcome-choose").click();
    assert.equal(clicks, 4);
  } finally {
    delete input.click;
  }
  assert.equal($("#welcome-binder").getAttribute("role"), "button");
  assert.equal($("#welcome-binder").getAttribute("tabindex"), "0");
  assert.equal($$("#welcome-slots .welcome-slot").length, 10);
  const how = $("details.welcome-how");
  assert.match(how.querySelector("summary").textContent, /How do I export from ManaBox\?/);
  assert.equal(how.querySelectorAll("ol li").length, 3);
});

test("a file that is not a CSV gets a toast and no import", async () => {
  await setup();
  choose("notes.txt");
  await app.until(() => toasts().includes("Choose a CSV file."));
  assert.equal(posts("/api/process/stream").length, 0);
  assert.ok(shown("#welcome-actions"));
});

test("a dropped CSV imports with live rows, then real cards fill the slots and the reveal shows", async () => {
  const { addCollection } = await setup();
  const stream = openStream();
  app.route("POST /api/process/stream", () => stream.reply());

  const binder = $("#welcome-binder");
  const over = new window.Event("dragover", { bubbles: true, cancelable: true });
  binder.dispatchEvent(over);
  assert.ok(binder.classList.contains("is-drag"));
  const drop = new window.Event("drop", { bubbles: true, cancelable: true });
  const file = new window.File(["Name\nSol Ring\n"], "mine.CSV", { type: "text/csv" });
  Object.defineProperty(drop, "dataTransfer", { value: { files: [file] } });
  binder.dispatchEvent(drop);
  assert.ok(!binder.classList.contains("is-drag"));

  await app.until(() => posts("/api/process/stream").length === 1);
  // The file goes out as the "file" part of a multipart form.
  assert.ok(posts("/api/process/stream")[0].body.has("file"));
  await app.until(() => shown("#welcome-progress"));
  assert.ok(!shown("#welcome-actions"));

  stream.send(progress(0, 0, ""));
  await app.until(() => text("#welcome-row") === "Reading the card data…");
  stream.send(progress(10, 25, "Sol Ring", 1));
  await app.until(() => text("#welcome-row") === "Row 10 of 25");
  assert.equal(text("#welcome-card"), "Sol Ring");
  assert.equal($("#welcome-progress-fill").style.transform, "scaleX(0.4)");
  assert.equal($("#welcome-progress .welcome-track").getAttribute("aria-valuenow"), "40");
  assert.equal($$("#welcome-slots .welcome-slot.is-lit").length, 4);
  assert.equal($$("#welcome-slots img").length, 0, "no card shows before the import is done");

  addCollection(NEW_BOX);
  stream.send(progress(25, 25, "Last Card", 1));
  stream.send(done(25, 1));
  stream.end();
  await app.until(() => $$("#welcome-slots .welcome-slot-card").length === 10);
  const sources = $$("#welcome-slots .welcome-slot-card img.card-img-sharp").map((img) => img.getAttribute("src"));
  // The unique names: card 2 shares the name of card 1, so it is skipped.
  const expected = [1, 3, 4, 5, 6, 7, 8, 9, 10, 11].map((i) => `/api/images/${ID(i)}/front?size=small`);
  assert.deepEqual(sources, expected);
  assert.equal(text("#welcome-row"), "24 of 25 rows matched");
  assert.equal(window.localStorage.getItem("lastJobId"), "job9");

  await app.until(() => $("#welcome-view").dataset.step === "3", 5000);
  assert.ok(shown("#welcome-reveal"));
  assert.ok($(".welcome-step[data-step='2']").classList.contains("is-done"));
  assert.ok(!shown("#welcome-skip"), "Skip leaves once the collection exists");
});

test("the sample button imports the sample collection", async () => {
  const { addCollection } = await setup();
  const stream = openStream();
  addCollection(NEW_BOX);
  await importSample(stream);
  assert.equal(posts("/api/process/stream").length, 0);
  await app.until(() => $("#welcome-view").dataset.step === "3", 5000);
});

test("an import error returns to step 2 with a toast", async () => {
  await setup();
  const stream = openStream();
  app.route("POST /api/process/stream", () => stream.reply());
  choose("mine.csv");
  stream.send(progress(10, 25, "Sol Ring"));
  await app.until(() => text("#welcome-row") === "Row 10 of 25");
  stream.send({ type: "error", detail: "File must be UTF-8 encoded text" });
  stream.end();
  await app.until(() => toasts().includes("File must be UTF-8 encoded text"));
  await app.until(() => shown("#welcome-actions"));
  assert.equal($("#welcome-view").dataset.step, "2");
  assert.ok(!shown("#welcome-progress"));
  assert.equal($$("#welcome-slots .welcome-slot.is-lit").length, 0);
  assert.equal($("#welcome-file").value, "");

  // A refusal before the stream shows the server's reason.
  app.route("POST /api/process/sample", () => ({ status: 404, json: { detail: "The sample collection is missing." } }));
  $("#welcome-sample").click();
  await app.until(() => toasts().includes("The sample collection is missing."));
  await app.until(() => shown("#welcome-actions"));

  // A stream that ends without a result.
  const cut = openStream();
  app.route("POST /api/process/sample", () => cut.reply());
  $("#welcome-sample").click();
  cut.send(progress(3, 25, "Opt"));
  cut.end();
  await app.until(() => toasts().includes("The import stopped. Try again."));
  await app.until(() => shown("#welcome-actions"));
  assert.equal($("#welcome-view").dataset.step, "2");
});

// ---- step 3: the reveal ----------------------------------------------------

test("the reveal shows the fan, counts the ledger up, and opens the Vault", async () => {
  const { addCollection } = await setup();
  addCollection(NEW_BOX);
  await importSample(openStream());
  await app.until(() => $("#welcome-view").dataset.step === "3", 5000);
  assert.ok(!$("#welcome-view").classList.contains("is-still"));

  assert.equal(text("#welcome-reveal-title"), "Your vault is ready.");
  assert.equal(text("#welcome-reveal-sub"), "1,002 cards found their place. Here are your crown jewels.");
  const fan = $$("#welcome-fan .welcome-fan-card");
  assert.equal(fan.length, 5);
  assert.deepEqual(fan.map((li) => li.querySelector("img.card-img-sharp").getAttribute("alt")),
    ["Card 1", "Card 3", "Card 4", "Card 5", "Card 6"]);
  assert.deepEqual(fan.map((li) => li.style.getPropertyValue("--k")), ["0", "-1", "1", "-2", "2"]);

  const value = (key) => text(`#welcome-ledger [data-key="${key}"] .welcome-ledger-value`);
  await app.until(() => value("value") === "$1,234.50" && value("cards") === "1,002" && value("rares") === "202", 4000);
  assert.deepEqual($$("#welcome-ledger .welcome-ledger-label").map((el) => el.textContent),
    ["Estimated value", "Cards", "Rares & mythics"]);

  window.localStorage.setItem("viewerSource", "archive");
  $("#welcome-open").click();
  await app.until(() => window.location.hash === "#collection" && active("collection"));
  assert.equal(window.localStorage.getItem("lastJobId"), "job9");
  assert.equal(window.localStorage.getItem("viewerSource"), null);
  await app.until(() => $("#collection-view").dataset.vault === "ready");
  assert.ok(app.fetchLog.some((r) => r.path === "/api/collection/job9/search"));
});

test("a reveal without insights still opens the Vault", async () => {
  const { addCollection } = await setup({ insights: null, shelves: null });
  addCollection(NEW_BOX);
  await importSample(openStream());
  await app.until(() => $("#welcome-view").dataset.step === "3", 5000);
  assert.equal(text("#welcome-reveal-sub"), "Your cards are in the Vault.");
  assert.equal($$("#welcome-fan .welcome-fan-card").length, 0);
  assert.ok($("#welcome-ledger").hidden);
  assert.ok(shown("#welcome-open"));
});

test("reduced motion shows each final state at once", async () => {
  const media = window.matchMedia;
  const still = (query) => ({
    matches: /prefers-reduced-motion/.test(query), media: query,
    addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {},
  });
  window.matchMedia = still;
  try {
    const { addCollection } = await setup();
    assert.ok($("#welcome-view").classList.contains("is-still"));
    addCollection(NEW_BOX);
    let ledger = null;
    let slots = 0;
    const observer = new window.MutationObserver(() => {
      if ($("#welcome-view").dataset.step === "3" && !ledger) {
        ledger = $$("#welcome-ledger .welcome-ledger-value").map((el) => el.textContent);
        slots = $$("#welcome-slots .welcome-slot-card").length;
      }
    });
    observer.observe($("#welcome-view"), { attributes: true, attributeFilter: ["data-step"] });
    await importSample(openStream());
    // No pause for the flip: the reveal follows the import at once.
    await app.until(() => $("#welcome-view").dataset.step === "3", 500);
    observer.disconnect();
    assert.deepEqual(ledger, ["$1,234.50", "1,002", "202"]);
    assert.equal(slots, 10);
  } finally {
    window.matchMedia = media;
  }
});
