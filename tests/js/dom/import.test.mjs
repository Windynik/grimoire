import { test, before } from "node:test";
import assert from "node:assert/strict";
import { loadApp } from "./harness.mjs";

let app;
let document;
let window;
let open;

before(async () => {
  app = await loadApp({});
  document = app.document;
  window = app.window;
  ({ open } = await import("../../../frontend/js/collection/import.js"));
});

const encoder = new TextEncoder();
const sse = (event) => encoder.encode(`data: ${JSON.stringify(event)}\n\n`);
const progress = (current, total, card, errors = 0) => ({
  type: "progress", current, total, current_card: card, errors,
});

// A stream the test feeds by hand. send() adds an event; end() closes it.
function openStream() {
  let controller;
  const body = new ReadableStream({ start(c) { controller = c; } });
  return {
    body,
    headers: { "content-type": "text/event-stream" },
    send: (event) => controller.enqueue(sse(event)),
    end: () => controller.close(),
  };
}

const text = (selector) => document.querySelector(selector)?.textContent || "";
const visible = (selector) => {
  const el = document.querySelector(selector);
  return Boolean(el) && !el.hidden;
};
const toasts = () => [...document.querySelectorAll("#toast-container .toast")].map((t) => t.textContent);

// Reset the screen, the storage, the toasts and the stubs. Each test calls this first.
async function setup({ stream = null, reply = null } = {}) {
  window.localStorage.clear();
  document.getElementById("toast-container").replaceChildren();
  app.fetchLog.length = 0;
  const answer = () => reply || { status: 200, body: stream.body, headers: stream.headers };
  app.route("POST /api/process/stream", answer);
  app.route("POST /api/process/text", answer);
  app.route("GET /api/cache/status", () => ({ json: { status: "ready", card_count: 1 } }));
  app.route("GET /api/collections", () => ({ json: { collections: [] } }));
  app.route("GET /api/decks", () => ({ json: { decks: [] } }));
  if (window.location.hash !== "#import") {
    window.location.hash = "#import";
    await app.until(() => document.getElementById("import-view").classList.contains("active"));
  }
  open();
  document.getElementById("import-another").click(); // back to Upload with an empty input
  await app.settle();
}

// Choose a file with the file input.
function choose(name) {
  const input = document.getElementById("file-input");
  const file = new window.File(["Name,Quantity\nSol Ring,1\n"], name, { type: "text/csv" });
  Object.defineProperty(input, "files", { value: [file], configurable: true });
  input.dispatchEvent(new window.Event("change", { bubbles: true }));
}

const done = (errors, total = 25) => ({
  type: "done",
  result: {
    job_id: "job9", status: "completed", total_processed: total,
    success_count: total - errors.length, error_count: errors.length, errors,
  },
});

test("progress, then the summary", async () => {
  const stream = openStream();
  await setup({ stream });
  assert.ok(visible("#import-upload"));
  assert.ok(!visible("#import-progress"));

  choose("mine.csv");
  stream.send(progress(10, 25, "Sol Ring", 1));
  await app.until(() => /Row 10 of 25/.test(text("#import-progress")));
  assert.ok(visible("#import-progress"));
  assert.ok(!visible("#import-upload"));
  assert.match(text("#import-progress"), /Sol Ring/);
  assert.match(text("#import-progress"), /1 unmatched/);
  const bar = document.querySelector("#import-progress .progress-bar");
  assert.equal(bar.getAttribute("aria-valuenow"), "40");
  assert.equal(document.getElementById("import-progress-fill").style.transform, "scaleX(0.4)");

  stream.send(progress(25, 25, "Last Card", 2));
  stream.send(done([
    { row: 4, card: "Black Lotus", error: "not_found" },
    { row: 9, card: "Odd Card", error: "missing_scryfall_id" },
  ]));
  stream.end();
  await app.until(() => visible("#import-summary"));
  assert.ok(!visible("#import-progress"));
  assert.equal(text("#import-summary h3"), "Imported 23 of 25 rows");
  const rows = [...document.querySelectorAll("#import-unmatched tbody tr")].map((tr) =>
    [...tr.children].map((td) => td.textContent));
  assert.deepEqual(rows, [
    ["4", "Black Lotus", "Not in the card data"],
    ["9", "Odd Card", "No Scryfall ID"],
  ]);
  const request = app.fetchLog.find((r) => r.path === "/api/process/stream");
  assert.equal(request.method, "POST");
  assert.equal(document.getElementById("import-download").getAttribute("href"), "/api/download/job9");

  document.getElementById("import-view-collection").click();
  assert.equal(window.localStorage.getItem("lastJobId"), "job9");
  await app.until(() => window.location.hash === "#collection");
});

test("only 100 unmatched rows show", async () => {
  const stream = openStream();
  await setup({ stream });
  choose("big.csv");
  const errors = Array.from({ length: 150 }, (_, i) => ({ row: i + 1, card: `Card ${i + 1}`, error: "not_found" }));
  stream.send(done(errors, 200));
  stream.end();
  await app.until(() => visible("#import-summary"));
  assert.equal(document.querySelectorAll("#import-unmatched tbody tr").length, 100);
  assert.match(text("#import-unmatched-more"), /and 50 more rows/);
});

test("a stream that stops early resets", async () => {
  const stream = openStream();
  await setup({ stream });
  choose("mine.csv");
  stream.send(progress(10, 25, "Sol Ring"));
  await app.until(() => visible("#import-progress"));
  stream.end();
  await app.until(() => visible("#import-upload"));
  assert.ok(!visible("#import-progress"));
  assert.ok(!visible("#import-summary"));
  assert.deepEqual(toasts(), ["The import stopped. Try again."]);
});

test("an error event shows its detail", async () => {
  const stream = openStream();
  await setup({ stream });
  choose("mine.csv");
  stream.send({ type: "error", detail: "Disk is full" });
  stream.end();
  await app.until(() => visible("#import-upload"));
  assert.deepEqual(toasts(), ["Disk is full"]);
});

test("a response that is not OK shows its detail", async () => {
  await setup({ reply: { status: 400, json: { detail: "Download the card data first." } } });
  choose("mine.csv");
  await app.until(() => toasts().length > 0);
  assert.deepEqual(toasts(), ["Download the card data first."]);
  assert.ok(visible("#import-upload"));
});

test("a file that is not a CSV or a list sends nothing", async () => {
  await setup({ reply: { status: 200, json: {} } });
  choose("sheet.xlsx");
  await app.settle();
  assert.deepEqual(toasts(), ["Choose a CSV file or a card list (.txt)."]);
  assert.equal(app.fetchLog.filter((r) => r.path === "/api/process/stream").length, 0);
  assert.ok(visible("#import-upload"));
});

test("Import another returns to Upload and clears the input", async () => {
  const stream = openStream();
  await setup({ stream });
  choose("mine.csv");
  stream.send(done([]));
  stream.end();
  await app.until(() => visible("#import-summary"));
  document.getElementById("import-another").click();
  assert.ok(visible("#import-upload"));
  assert.ok(!visible("#import-summary"));
});

test("the first wait reads Reading the card data", async () => {
  const stream = openStream();
  await setup({ stream });
  choose("mine.csv");
  await app.until(() => visible("#import-progress"));
  assert.match(text("#import-row-text"), /Reading the card data/);
  assert.doesNotMatch(text("#import-row-text"), /Row 0 of 0/);

  stream.send(progress(5, 25, "Sol Ring"));
  await app.until(() => /Row 5 of 25/.test(text("#import-row-text")));
  stream.send(done([]));
  stream.end();
  await app.until(() => visible("#import-summary"));
});

test("a connection reset after the last chunk keeps the summary", async () => {
  let controller;
  const body = new ReadableStream({ start(c) { controller = c; } });
  await setup({ stream: { body, headers: { "content-type": "text/event-stream" } } });
  choose("mine.csv");
  await app.until(() => visible("#import-progress"));
  controller.enqueue(sse(done([])));
  await app.until(() => visible("#import-summary"));
  const log = console.error;
  console.error = () => {}; // The import code logs the reset.
  try {
    controller.error(new Error("reset"));
    await app.settle();
    await app.settle();
  } finally {
    console.error = log;
  }
  assert.ok(visible("#import-summary"), "the summary stays");
  assert.deepEqual(toasts(), []);
});

test("a text file imports, and a result without a source or notice hides both lines", async () => {
  const stream = openStream();
  await setup({ stream });
  choose("deck.TXT");
  stream.send(done([{ row: 2, card: "Ghost Card", error: "unknown_card" }], 3));
  stream.end();
  await app.until(() => visible("#import-summary"));
  const rows = [...document.querySelectorAll("#import-unmatched tbody tr")].map((tr) =>
    [...tr.children].map((td) => td.textContent));
  assert.deepEqual(rows, [["2", "Ghost Card", "No card with this name"]]);
  assert.ok(!visible("#import-summary-source"));
  assert.ok(!visible("#import-summary-notice"));
});

test("a pasted list posts its text and shows the source", async () => {
  const stream = openStream();
  await setup({ stream });
  document.querySelector("details.import-paste").open = true;
  document.getElementById("import-paste-text").value = "4 Lightning Bolt\n1x Sol Ring";
  document.getElementById("import-paste-go").click();
  const finish = done([], 2);
  finish.result.source_format = "a card list";
  stream.send(finish);
  stream.end();
  await app.until(() => visible("#import-summary"));
  assert.equal(text("#import-summary-source"), "Read as a card list.");
  const request = app.fetchLog.find((r) => r.path === "/api/process/text");
  assert.equal(request.method, "POST");
  assert.deepEqual(request.body, { text: "4 Lightning Bolt\n1x Sol Ring" });

  // Import another clears the paste box.
  document.getElementById("import-another").click();
  assert.equal(document.getElementById("import-paste-text").value, "");
});

test("an app export names the app in the summary", async () => {
  const stream = openStream();
  await setup({ stream });
  choose("moxfield.csv");
  const finish = done([], 5);
  finish.result.source_format = "Moxfield";
  stream.send(finish);
  stream.end();
  await app.until(() => visible("#import-summary"));
  assert.equal(text("#import-summary-source"), "Read as an export of Moxfield.");
});

test("an empty paste gets a toast and sends nothing", async () => {
  await setup({ reply: { status: 200, json: {} } });
  document.getElementById("import-paste-text").value = "   ";
  document.getElementById("import-paste-go").click();
  await app.settle();
  assert.deepEqual(toasts(), ["Paste a card list first."]);
  assert.equal(app.fetchLog.filter((r) => r.path === "/api/process/text").length, 0);
});

test("the summary shows the notice of the server", async () => {
  const stream = openStream();
  await setup({ stream });
  choose("moxfield.csv");
  const finish = done([], 5);
  finish.result.source_format = "Moxfield";
  finish.result.notice = "Update the card data on Home to get the exact printings.";
  stream.send(finish);
  stream.end();
  await app.until(() => visible("#import-summary"));
  assert.ok(visible("#import-summary-notice"));
  assert.equal(text("#import-summary-notice"), "Update the card data on Home to get the exact printings.");
});

test("a failed paste keeps the pasted list", async () => {
  await setup({ reply: { status: 413, json: { detail: "The list is too long." } } });
  document.getElementById("import-paste-text").value = "4 Lightning Bolt";
  document.getElementById("import-paste-go").click();
  await app.until(() => toasts().length > 0);
  assert.deepEqual(toasts(), ["The list is too long."]);
  assert.ok(visible("#import-upload"));
  assert.equal(document.getElementById("import-paste-text").value, "4 Lightning Bolt");
});
