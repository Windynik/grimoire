import { test, before } from "node:test";
import assert from "node:assert/strict";
import { loadApp } from "./harness.mjs";

const decks = Array.from({ length: 6 }, (_, i) => ({
  id: `d${i + 1}`, name: `Deck ${i + 1}`, format: "commander", count: 100,
  updated: `2026-11-0${6 - i}T10:00:00`, image_url: "", commander: null,
}));

let app;
let document;
let open;

before(async () => {
  app = await loadApp({
    routes: {
      "GET /api/cache/status": () => ({
        json: { status: "ready", card_count: 30000, file_size_mb: 120.5, download_date: "2026-11-01T10:00:00" },
      }),
      "GET /api/collections": () => ({
        json: { collections: [{ job_id: "job1", name: "Test box", card_count: 3, created: null }] },
      }),
      "GET /api/decks": () => ({ json: { decks } }),
      "DELETE /api/collection/job1": () => ({ json: { ok: true } }),
    },
  });
  document = app.document;
  ({ open } = await import("../../../frontend/js/home/home.js"));
});

const text = (selector) => document.querySelector(selector)?.textContent || "";

test("a ready archive offers Update card data", async () => {
  await app.until(() => /Update card data/.test(text("#download-cache")));
  assert.match(text("#card-count"), /30,000/);
});

test("a missing archive offers Download card data", async () => {
  app.route("GET /api/cache/status", () => ({ json: { status: "missing" } }));
  open();
  await app.until(() => /Download card data/.test(text("#download-cache")));
});

test("recent decks shows at most 4 and opens one", async () => {
  const tiles = await app.until(() => {
    const found = document.querySelectorAll("#home-decks .deck-tile");
    return found.length ? found : null;
  });
  assert.equal(tiles.length, 4);
  tiles[0].click();
  await app.until(() => document.defaultView.location.hash === "#deck/d1");
  document.defaultView.location.hash = "#home";
  await app.until(() => document.getElementById("home-view").classList.contains("active"));
});

test("Delete asks first, and Cancel sends nothing", async () => {
  const del = await app.until(() => document.querySelector(".collection-del"));
  del.click();
  const cancel = await app.until(() => document.querySelector("dialog[open] .btn-secondary"));
  cancel.click();
  await app.settle();
  assert.equal(app.fetchLog.filter((r) => r.method === "DELETE").length, 0);
});

test("Import CSV goes to the import screen", async () => {
  document.getElementById("home-import").click();
  await app.until(() => document.getElementById("import-view").classList.contains("active"));
  assert.equal(document.defaultView.location.hash, "#import");
});
