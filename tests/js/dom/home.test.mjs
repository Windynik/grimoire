import { test, before } from "node:test";
import assert from "node:assert/strict";
import { loadApp } from "./harness.mjs";

const decks = Array.from({ length: 6 }, (_, i) => ({
  id: `d${i + 1}`, name: `Deck ${i + 1}`, format: "commander", count: 100,
  updated: `2026-11-0${6 - i}T10:00:00`, image_url: "", commander: null,
}));
const box = { job_id: "job1", name: "Test box", card_count: 3, created: null };
const READY = { status: "ready", card_count: 30000, file_size_mb: 120.5, download_date: "2026-11-01T10:00:00" };

let app;
let document;
let window;
let open;

before(async () => {
  app = await loadApp({});
  document = app.document;
  window = app.window;
  ({ open } = await import("../../../frontend/js/home/home.js"));
});

// Set the stubs, the storage and the hash this test needs, then open Home.
async function setup({ status = READY, collections = [box], deckList = decks, storage = {} } = {}) {
  let rows = collections.slice();
  app.route("GET /api/cache/status", () => ({ json: status }));
  app.route("GET /api/collections", () => ({ json: { collections: rows } }));
  app.route("GET /api/decks", () => ({ json: { decks: deckList } }));
  app.route("DELETE /api/collection/job1", () => {
    rows = rows.filter((c) => c.job_id !== "job1");
    return { json: { ok: true } };
  });
  window.localStorage.clear();
  Object.entries(storage).forEach(([key, value]) => window.localStorage.setItem(key, value));
  app.fetchLog.length = 0;
  if (window.location.hash !== "#home") {
    window.location.hash = "#home";
    await app.until(() => document.getElementById("home-view").classList.contains("active"));
  }
  open();
  await app.settle();
}

const text = (selector) => document.querySelector(selector)?.textContent || "";
const deletes = () => app.fetchLog.filter((r) => r.method === "DELETE");

test("a ready archive offers Update card data", async () => {
  await setup();
  await app.until(() => /Update card data/.test(text("#download-cache")));
  assert.match(text("#card-count"), /30,000/);
});

test("a missing archive offers Download card data", async () => {
  await setup({ status: { status: "missing" } });
  await app.until(() => /Download card data/.test(text("#download-cache")));
});

test("recent decks shows at most 4 and opens one", async () => {
  await setup();
  const tiles = await app.until(() => {
    const found = document.querySelectorAll("#home-decks .deck-tile");
    return found.length ? found : null;
  });
  assert.equal(tiles.length, 4);
  tiles[0].click();
  await app.until(() => window.location.hash === "#deck/d1");
});

test("recent decks has an empty state", async () => {
  await setup({ deckList: [] });
  await app.until(() => /No decks yet\. Forge one, or create one in Decks\./.test(text("#home-decks")));
});

test("collections has an empty state", async () => {
  await setup({ collections: [] });
  await app.until(() => /No collections yet\. Import a ManaBox CSV to start\./
    .test(text("#dashboard-collections")));
});

test("View sets the active collection and opens the collection screen", async () => {
  await setup();
  const view = await app.until(() => document.querySelector(".collection-view"));
  view.click();
  await app.until(() => window.location.hash === "#collection");
  assert.equal(window.localStorage.getItem("lastJobId"), "job1");
  assert.equal(window.localStorage.getItem("viewerSource"), "job1");
});

test("Delete asks first, and Cancel sends nothing", async () => {
  await setup();
  const del = await app.until(() => document.querySelector(".collection-del"));
  del.click();
  const cancel = await app.until(() => document.querySelector("dialog[open] .btn-secondary"));
  cancel.click();
  await app.settle();
  assert.equal(deletes().length, 0);
  assert.ok(document.querySelector(".collection-row"));
});

test("Delete then confirm sends DELETE, forgets the session keys, and drops the row", async () => {
  await setup({ storage: { lastJobId: "job1", viewerSource: "job1" } });
  const del = await app.until(() => document.querySelector(".collection-del"));
  del.click();
  const confirm = await app.until(() => document.querySelector("dialog[open] button[type=submit]"));
  confirm.click();
  await app.until(() => deletes().length === 1);
  assert.equal(deletes()[0].path, "/api/collection/job1");
  await app.until(() => !document.querySelector(".collection-row"));
  assert.equal(window.localStorage.getItem("lastJobId"), null);
  assert.equal(window.localStorage.getItem("viewerSource"), null);
});

test("Import CSV goes to the import screen", async () => {
  await setup();
  document.getElementById("home-import").click();
  await app.until(() => document.getElementById("import-view").classList.contains("active"));
  assert.equal(window.location.hash, "#import");
});
